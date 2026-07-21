"""SQLite persistence — job status + parked reviews that outlive a reboot (spec §5–6, T-002).

Why this exists: the review queue is the product's spine (spec §5), and spec §7
requires that "restarting the backend preserves parked reviews". A parked review
therefore cannot live in memory — it has to be on disk. This module owns the two
tables from spec §6 and a thin DAO over them; T-007 writes a parked review here,
T-014 lists and resolves them.

Two deliberate shape choices:

- **Store candidate *IDs*, never rich candidate objects** (ADR-006 corollary /
  spec §5). A cached MusicBrainz candidate object would go stale and bloats the
  row; the resume path (T-014) re-matches from the stored MBIDs instead. So
  `reviews.candidate_ids_json` is a JSON array of MBID strings — **plus one
  exception, `candidate_scores_json`** (T-028 / ADR-010 addendum): the per-candidate
  score, a MBID → float map. It is the one field that cannot be re-derived, because
  it is beets' *tag distance against this download* — not a property of the
  recording — so a MusicBrainz re-lookup can never recover it. ADR-010 makes it the
  discriminator the owner picks on, and spec §7 says the queue survives a restart;
  storing it is what makes those two true at the same time. A map rather than a
  parallel array so it cannot drift out of order with `candidate_ids_json`, and a
  missing key degrades to `None` — which is the pre-T-028 behaviour, so legacy rows
  and duplicate parks need no special case.
- **A connection per operation, not one shared handle.** The backend runs the
  pipeline on a worker thread (spec §4) while FastAPI serves routes on the event
  loop; a single sqlite3 connection isn't safe to share across threads. Opening
  and closing per call sidesteps that entirely — negligible cost for a
  single-user tool, and it keeps the DAO stateless.

IDs are uuid4 hex strings (collision-free without a round-trip to the DB, and no
autoincrement coupling). `created_at` is an ISO-8601 UTC timestamp string —
human-legible in a `.db` browser and trivially sortable lexicographically.
"""

import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Iterator

from app.config import get_settings

# Idempotent schema (spec §6). CREATE TABLE IF NOT EXISTS so a boot on an
# existing DB is a no-op — the tables outlive the process, that's the point.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id         TEXT PRIMARY KEY,
    url        TEXT NOT NULL,
    status     TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reviews (
    id                    TEXT PRIMARY KEY,
    job_id                TEXT NOT NULL REFERENCES jobs(id),
    staging_path          TEXT NOT NULL,
    query                 TEXT NOT NULL,
    candidate_ids_json    TEXT NOT NULL,
    candidate_scores_json TEXT,
    rec                   TEXT NOT NULL,
    status                TEXT NOT NULL,
    last_error            TEXT
);
"""

# Columns added after the first release, as (table, column, DDL type). Applied by
# `_migrate` on every connect for a DB that predates them — `CREATE TABLE IF NOT
# EXISTS` is a no-op on an existing table, so a new column in `_SCHEMA` above
# would silently never appear on the owner's live DB. Nullable with no default,
# so an old row reads as "unknown", which is what it is.
_ADDED_COLUMNS = [
    ("reviews", "candidate_scores_json", "TEXT"),  # T-028
    ("reviews", "last_error", "TEXT"),  # T-029 — reason a resolve last failed (re-park)
]

# Sentinel default for `release_review(last_error=...)`. It distinguishes "the caller
# named no reason, so leave the stored one alone" from an explicit `None` ("clear it").
# A plain `None` default cannot tell those apart, and conflating them let a bare
# `release_review(id)` (the failed-hand-off requeue in routes/reviews.py) overwrite a
# persisted re-park reason with NULL — T-029, finding #2. Clearing a reason is now the
# job of `claim_review` / `reset_resolving_reviews` (finding #3), not of a bare release.
_KEEP_LAST_ERROR: str | None = object()  # type: ignore[assignment]


def _migrate(conn: sqlite3.Connection) -> None:
    """Add any `_ADDED_COLUMNS` missing from an existing DB. Idempotent.

    Runs on every `init_schema()`. Needed because `CREATE TABLE IF NOT EXISTS` does
    nothing to a table that already exists, so a column added to `_SCHEMA` would
    appear on a fresh checkout and never on the owner's live DB — the one that has
    the parked reviews spec §7 promises to keep.
    """
    for table, column, ddl_type in _ADDED_COLUMNS:
        present = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in present:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}")


@dataclass(frozen=True)
class Job:
    """A row of `jobs` — one paste-a-URL run and where it is in the pipeline."""

    id: str
    url: str
    status: str  # e.g. "queued" | "running" | "review" | "done" | "error"
    created_at: str  # ISO-8601 UTC


@dataclass(frozen=True)
class Review:
    """A row of `reviews` — a song parked for the owner to pick a match (spec §5).

    `candidate_ids` is the decoded JSON array: MusicBrainz recording MBIDs, not
    candidate objects (ADR-006). T-014 re-hydrates them on resume.

    `candidate_scores` maps MBID → score (T-028). Empty for a duplicate park (no
    candidates were scored) and for any row written before T-028; a missing key is
    `None`, i.e. "unknown", which is what every row returned before this existed.
    It is stored rather than re-derived because it is the tag distance between
    *this download* and the candidate — not a property of the recording — so no
    MusicBrainz lookup can recover it (ADR-010 addendum).
    """

    id: str
    job_id: str
    staging_path: str
    query: str
    candidate_ids: list[str]
    rec: str  # the beets `task.rec` recommendation, recorded as text
    status: str  # "pending" | "resolving" | "resolved" | "rejected" (see STATUS_* below)
    candidate_scores: dict[str, float] = field(default_factory=dict)
    # Why the last resolve attempt failed, if it re-parked this row (T-029). NULL on a
    # first park; set by `release_review`. Persisted so the reason survives a reconnect
    # or reload — the SSE `message` alone is lost the moment the stream is (finding #2).
    last_error: str | None = None


# Review lifecycle (T-014). `pending` is what the queue lists and what a resolve
# claims; `resolving` is the in-flight window between the claim and the worker
# finishing; the last two are terminal. `resolving` exists so a double-clicked
# resolve can't run twice and land two copies — see `claim_review`.
REVIEW_PENDING = "pending"
REVIEW_RESOLVING = "resolving"
REVIEW_RESOLVED = "resolved"
REVIEW_REJECTED = "rejected"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    """Thin DAO over the SQLite file. Stateless: holds a path, not a connection."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        # Row factory so reads map to columns by name, not positional index —
        # the dataclass constructors below stay readable. Commit on clean exit,
        # roll back on error, always close (see module docstring on why per-call).
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        # Per-connection pragmas (neither persists across connections in SQLite):
        # enforce the reviews→jobs foreign key — off by default, or an orphan
        # review row slips in (spec §6) — and wait rather than instantly erroring
        # if the worker thread holds a write lock while a route reads (WAL, set
        # once in init_schema, keeps that contention rare to begin with).
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_schema(self) -> None:
        """Create the tables if absent. Also ensures the DB's parent dir exists
        so a first boot on a clean checkout doesn't trip on a missing folder."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            # WAL is a property of the DB file — set once, persistent. It lets the
            # event loop read while the worker thread writes, instead of the
            # default rollback journal's whole-file lock (spec §4: pipeline on a
            # worker thread, routes on the event loop). Also why .gitignore
            # anticipates the *.db-wal / *.db-shm sidecars.
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(_SCHEMA)
            _migrate(conn)

    # --- jobs -------------------------------------------------------------

    def create_job(self, url: str, status: str = "queued") -> Job:
        job = Job(id=uuid.uuid4().hex, url=url, status=status, created_at=_now())
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO jobs (id, url, status, created_at) VALUES (?, ?, ?, ?)",
                (job.id, job.url, job.status, job.created_at),
            )
        return job

    def get_job(self, job_id: str) -> Job | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return _job_from_row(row) if row else None

    def update_job_status(self, job_id: str, status: str) -> None:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE jobs SET status = ? WHERE id = ?", (status, job_id)
            )
            # A zero-row update means the id doesn't exist — raise rather than
            # report a phantom success that leaves a job silently stuck (a wrong
            # or stale id otherwise looks identical to a real transition).
            if cur.rowcount == 0:
                raise KeyError(f"no job with id {job_id!r}")

    def fail_unfinished_jobs(self) -> int:
        """Mark every job left `queued`/`running` by a crash or shutdown as `error`.

        The job queue is in-memory (T-012): it does not survive a restart, so any
        row still `queued` or `running` at boot is orphaned — it will never be
        picked up again. Left alone it would report `running` forever (a stuck
        progress UI). Called once on worker startup so the durable status is honest
        after any restart. Returns how many rows were reconciled.
        """
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE jobs SET status = 'error' WHERE status IN ('queued', 'running')"
            )
            return cur.rowcount

    # --- reviews ----------------------------------------------------------

    def create_review(
        self,
        job_id: str,
        staging_path: str,
        query: str,
        candidate_ids: list[str],
        rec: str,
        status: str = REVIEW_PENDING,
        candidate_scores: dict[str, float] | None = None,
    ) -> Review:
        review = Review(
            id=uuid.uuid4().hex,
            job_id=job_id,
            staging_path=staging_path,
            query=query,
            candidate_ids=candidate_ids,
            rec=rec,
            status=status,
            candidate_scores=candidate_scores or {},
        )
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO reviews "
                "(id, job_id, staging_path, query, candidate_ids_json, "
                "candidate_scores_json, rec, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    review.id,
                    review.job_id,
                    review.staging_path,
                    review.query,
                    json.dumps(review.candidate_ids),
                    json.dumps(review.candidate_scores),
                    review.rec,
                    review.status,
                ),
            )
        return review

    def get_review(self, review_id: str) -> Review | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM reviews WHERE id = ?", (review_id,)
            ).fetchone()
        return _review_from_row(row) if row else None

    def get_pending_review_for_job(self, job_id: str) -> Review | None:
        """The pending review parked for `job_id`, if any (most recent wins).

        The durable counterpart to the in-memory job registry (T-012): after a
        restart the registry is empty, but a parked review survives in SQLite, so
        the reconnect snapshot recovers its id from here. Also how the pipeline
        detects a park that happened just before a later import error, so it keeps
        the staging file the review points at instead of deleting it.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM reviews WHERE job_id = ? AND status = ? "
                "ORDER BY rowid DESC LIMIT 1",
                (job_id, REVIEW_PENDING),
            ).fetchone()
        return _review_from_row(row) if row else None

    def list_reviews(self, status: str | None = None) -> list[Review]:
        """All reviews, or only those in `status` (T-014 lists the pending ones)."""
        with self._connect() as conn:
            if status is None:
                rows = conn.execute("SELECT * FROM reviews").fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM reviews WHERE status = ?", (status,)
                ).fetchall()
        return [_review_from_row(row) for row in rows]

    def update_review_status(self, review_id: str, status: str) -> None:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE reviews SET status = ? WHERE id = ?", (status, review_id)
            )
            # Same guard as update_job_status: an unknown review_id must raise,
            # not silently succeed and leave a resolved song stuck in the queue.
            if cur.rowcount == 0:
                raise KeyError(f"no review with id {review_id!r}")

    def claim_review(self, review_id: str) -> Review | None:
        """Atomically take a `pending` review to `resolving`. None if it wasn't pending.

        A compare-and-set, not a read-then-write, because the check and the claim must
        be one step (T-014). The resolve route reads the row to validate the body and
        then hands the work to the worker thread; between those two a second POST — a
        double-clicked button, the obvious real case — could pass the same check and
        enqueue a second resolve, landing the song **twice**. Doing the transition in
        SQL means exactly one caller sees rowcount 1 and the loser gets a clean 409.

        Returns the row as it was *before* the claim (still carrying `pending`), which
        is what the caller validates against — `status` is the only field the resolve
        reads. `last_error` is cleared too (T-029, finding #3): a fresh retry starts
        clean, so a reason left over from a *previous* re-park is not shown misattributed
        as the reason for this attempt. The pre-claim row still carries the old value,
        which is harmless — nothing downstream reads `last_error` off the claimed row.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM reviews WHERE id = ?", (review_id,)
            ).fetchone()
            if row is None:
                return None
            cur = conn.execute(
                "UPDATE reviews SET status = ?, last_error = NULL WHERE id = ? AND status = ?",
                (REVIEW_RESOLVING, review_id, REVIEW_PENDING),
            )
            if cur.rowcount == 0:
                return None
        return _review_from_row(row)

    def release_review(
        self, review_id: str, last_error: str | None = _KEEP_LAST_ERROR
    ) -> Review:
        """Hand a claimed review back to `pending` so a failed resolve is retryable.

        The counterpart to `claim_review`: a resolve that errors (the staging copy
        won't import, MusicBrainz is down) must leave the song in the queue rather
        than strand it in `resolving`, where nothing lists it and nothing can claim it.

        `last_error` records *why* it re-parked, persisted so the reason survives a
        reconnect/reload (T-029, finding #2) — the SSE `message` alone dies with the
        stream. Omit it (the sentinel default) and the stored reason is left untouched:
        the failed-hand-off requeue (routes/reviews.py) passes no reason and must not
        erase a reason a prior re-park persisted. Pass an explicit value to set it, or
        an explicit `None` to clear it.

        Returns the released row (via `RETURNING`), so the re-park path can re-emit its
        `review_required` from the fresh row without a second SELECT — T-029, finding #6.
        """
        with self._connect() as conn:
            if last_error is _KEEP_LAST_ERROR:
                row = conn.execute(
                    "UPDATE reviews SET status = ? WHERE id = ? RETURNING *",
                    (REVIEW_PENDING, review_id),
                ).fetchone()
            else:
                row = conn.execute(
                    "UPDATE reviews SET status = ?, last_error = ? WHERE id = ? RETURNING *",
                    (REVIEW_PENDING, last_error, review_id),
                ).fetchone()
            if row is None:
                raise KeyError(f"no review with id {review_id!r}")
        return _review_from_row(row)

    def reset_resolving_reviews(self) -> int:
        """Return every review stranded mid-resolve by a crash/shutdown to `pending`.

        The mirror of `fail_unfinished_jobs`, and for the same reason: the work queue
        is in-memory, so a row left `resolving` at boot has no worker coming for it and
        would sit invisible to the queue forever. Called once on worker startup.
        Returns how many rows were reconciled.

        `last_error` is cleared (T-029, finding #3): a crash mid-resolve is not a failed
        pick, so a reason left over from a *previous* re-park must not be shown as the
        reason this row is back in the queue after a restart.
        """
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE reviews SET status = ?, last_error = NULL WHERE status = ?",
                (REVIEW_PENDING, REVIEW_RESOLVING),
            )
            return cur.rowcount


def _job_from_row(row: sqlite3.Row) -> Job:
    return Job(
        id=row["id"],
        url=row["url"],
        status=row["status"],
        created_at=row["created_at"],
    )


def _review_from_row(row: sqlite3.Row) -> Review:
    return Review(
        id=row["id"],
        job_id=row["job_id"],
        staging_path=row["staging_path"],
        query=row["query"],
        candidate_ids=json.loads(row["candidate_ids_json"]),
        rec=row["rec"],
        status=row["status"],
        # NULL on any row written before T-028, and on a DB whose ALTER hasn't run
        # yet. Decodes to {} → every score reads `None`, which is what this endpoint
        # returned for every row before T-028 existed. Degrade, never raise: a queue
        # that 500s is a queue the owner can't empty (`_hydrate`'s rule).
        candidate_scores=json.loads(row["candidate_scores_json"] or "{}"),
        last_error=row["last_error"],  # T-029; NULL on a first park or a pre-migration row
    )


@lru_cache
def get_store() -> Store:
    """Cached accessor — one Store per process, path from Settings (mirrors
    get_settings). Schema init is the caller's job at startup (main.py lifespan),
    not a side effect of first access."""
    return Store(get_settings().db_path)
