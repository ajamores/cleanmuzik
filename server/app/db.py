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
    last_error            TEXT,
    reason                TEXT,
    contradictions_json   TEXT
);

-- R2 (T-300 / ADR-027). A batch = one `playlists` row + N `jobs` rows sharing its
-- `playlist_id`. Both tables are genuinely NEW, so they live in `_SCHEMA` with an
-- `IF NOT EXISTS` guard (creates them on the owner's live DB, no-ops thereafter) —
-- NOT in `_ADDED_COLUMNS`, because SQLite's `ALTER TABLE … ADD COLUMN` cannot add a
-- UNIQUE column and both tables need one (ADR-027; the T-206 lesson forbids smuggling
-- a new *column* into an existing table's CREATE, not creating a new table this way).
CREATE TABLE IF NOT EXISTS playlists (
    id                   TEXT PRIMARY KEY,
    youtube_playlist_id  TEXT NOT NULL UNIQUE,   -- the create-or-reuse key (ADR-027 seam 6)
    title                TEXT NOT NULL,          -- derived from the YouTube title (no user naming)
    jellyfin_playlist_id TEXT,                   -- NULL until the Jellyfin playlist is created (T-304)
    created_at           TEXT NOT NULL
);

-- App-side playlist↔track membership: the source of truth read three ways (re-paste
-- skip-check, aggregate counters, backfill — ADR-027). Keyed by the track's YouTube
-- video id so a re-paste's membership-check needs no round-trip to Jellyfin, and
-- UNIQUE(playlist_id, youtube_video_id) makes a double-add structurally impossible
-- (ADR-027 seam 4). `jellyfin_item_id` is NULL while the append is PENDING — the
-- durable home for ADR-027 seam 1's "write membership now, defer the Jellyfin append
-- the next scan reconciles" (never a silent drop).
CREATE TABLE IF NOT EXISTS playlist_members (
    id                TEXT PRIMARY KEY,
    playlist_id       TEXT NOT NULL REFERENCES playlists(id),
    youtube_video_id  TEXT NOT NULL,
    position          INTEGER NOT NULL,
    jellyfin_item_id  TEXT,                      -- NULL = pending append (ADR-027 seam 1)
    created_at        TEXT NOT NULL,
    UNIQUE(playlist_id, youtube_video_id)
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
    # T-206 — the reconcile Verdict's park discriminators, persisted so a parked card
    # survives a restart (ADR-010's lesson: a discriminator that lives only in the live
    # SSE event is unrecoverable after a reload). `reason` is why it parked, distinct
    # from `last_error` (why a later *resolve* re-parked it); `contradictions_json` is
    # the JSON list of senses that disagreed. NULL on any pre-T-206 row and on the R1
    # degrade/fingerprint path, which has no Verdict.
    ("reviews", "reason", "TEXT"),
    ("reviews", "contradictions_json", "TEXT"),
    # R2 (T-300 / ADR-027). Three columns on the existing `jobs` table — added via
    # ALTER, not `_SCHEMA`, because `jobs` already exists on the owner's live DB (the
    # T-206 lesson). All three are nullable-with-no-default, which is why the ALTER is
    # legal (SQLite forbids ALTER-ADD of a non-null-defaulted or UNIQUE column) and why
    # an old R1 row reads as "unknown", i.e. a single-song paste.
    #   playlist_id — nullable association → playlists.id. **NULL = single-song paste =
    #     the R1 path, byte-for-byte unchanged** (acceptance item 11); non-null = a batch
    #     member. NOT a DB-enforced FK: SQLite's ALTER ADD COLUMN cannot attach a
    #     REFERENCES clause, so despite `PRAGMA foreign_keys = ON` this link is enforced
    #     by app discipline only (T-302 only ever sets it to a just-upserted playlist id).
    #     The reverse link IS enforced — `playlist_members.playlist_id` carries a real
    #     inline FK, because that table is created whole in `_SCHEMA`.
    #   position — the track's index in the expanded playlist (stable, journal order).
    #   youtube_video_id — the source video, recorded at enqueue so exact-video dedup
    #     (T-303) can answer "do I already have this?" without guessing.
    ("jobs", "playlist_id", "TEXT"),
    ("jobs", "position", "INTEGER"),
    ("jobs", "youtube_video_id", "TEXT"),
]

# Sentinel default for `release_review(last_error=...)`. It distinguishes "the caller
# named no reason, so leave the stored one alone" from an explicit `None` ("clear it").
# A plain `None` default cannot tell those apart, and conflating them let a bare
# `release_review(id)` (the failed-hand-off requeue in routes/reviews.py) overwrite a
# persisted re-park reason with NULL — T-029, finding #2. Clearing a reason is now the
# job of `claim_review` / `reset_resolving_reviews` (finding #3), not of a bare release.
_KEEP_LAST_ERROR: str | None = object()  # type: ignore[assignment]


# Indexes for the two hot read paths ADR-027 locks in, both over the ever-growing
# `jobs` table (one row per song ever downloaded). Created AFTER `_migrate`, not in
# `_SCHEMA`, because they reference columns that `_migrate` adds — on first migration
# of a live DB the columns don't exist when `_SCHEMA` runs. `IF NOT EXISTS` so it's a
# no-op thereafter.
#   youtube_video_id — the exact-video dedup `EXISTS(job WHERE youtube_video_id=? AND
#     status='done')` on every re-pasted entry (ADR-027 seam 2 / T-303).
#   playlist_id — the batch-tally derivation, jobs grouped by playlist (seam 5 / T-312).
_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_jobs_youtube_video_id ON jobs(youtube_video_id)",
    "CREATE INDEX IF NOT EXISTS idx_jobs_playlist_id ON jobs(playlist_id)",
]


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
    # R2 batch association (T-300 / ADR-027). All three NULL on an R1 single-song paste
    # and on any row written before this migration — `playlist_id IS NULL` is the switch
    # that keeps the R1 path unchanged (acceptance item 11).
    playlist_id: str | None = None  # → playlists.id (app-enforced); NULL = single-song (R1)
    position: int | None = None  # index in the expanded playlist
    youtube_video_id: str | None = None  # source video, recorded at enqueue (T-303 dedup)


@dataclass(frozen=True)
class Playlist:
    """A row of `playlists` — one batch, keyed by its YouTube playlist id (T-300).

    `jellyfin_playlist_id` is NULL until the Jellyfin playlist is created (T-304); the
    create-or-reuse key is `youtube_playlist_id`, which is UNIQUE so a re-paste reuses
    the same row (idempotent re-paste, T-307) via the atomic upsert in `upsert_playlist`.
    """

    id: str
    youtube_playlist_id: str
    title: str
    created_at: str  # ISO-8601 UTC
    jellyfin_playlist_id: str | None = None


@dataclass(frozen=True)
class PlaylistMember:
    """A row of `playlist_members` — one track's membership in a playlist (T-300).

    The app-side source of truth read three ways (ADR-027): the re-paste skip-check,
    the aggregate counters, and backfill. `jellyfin_item_id` is NULL while the append
    is *pending* — the durable home for the deferred-append the next scan reconciles
    (ADR-027 seam 1), never a silent drop.
    """

    id: str
    playlist_id: str
    youtube_video_id: str
    position: int
    created_at: str  # ISO-8601 UTC
    jellyfin_item_id: str | None = None


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
    # The reconcile Verdict's park discriminators (T-206), persisted so a parked card
    # re-hydrates the *original* park story after a restart, not just its candidates.
    # `reason` is the Verdict's one-line "why parked" — distinct from `last_error`, which
    # is why a *later* resolve attempt re-parked. `contradictions` is the senses that
    # disagreed. Both NULL/empty on the R1 fingerprint/degrade path (no Verdict).
    reason: str | None = None
    contradictions: list[str] = field(default_factory=list)


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

    @property
    def staging_root(self) -> Path:
        """Where jobs stage their download + transcode — beside this store's DB (T-106).

        A parked review KEEPS its staging file (spec §5), because that file IS the copy
        the resolve lands. Until 2026-07-25 the root was `tempfile`'s default, inherited
        rather than chosen (the override existed so pytest could stage under `tmp_path`),
        so the OS reaped the audio out from under 9 of 10 parked reviews while their rows
        survived. The row was durable; the song wasn't.

        Derived from `db_path` rather than configured separately so the two halves of a
        parked review — the row and the audio — cannot be pointed at different places.
        That also makes the boot sweep safe by construction: a Store under a pytest
        `tmp_path` owns a staging root under that same `tmp_path`, so a test can never
        sweep the real library's parked audio no matter how it wires its worker.
        """
        return self._db_path.parent / "staging"

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
            for stmt in _INDEXES:  # after _migrate — they index columns it adds
                conn.execute(stmt)

    # --- jobs -------------------------------------------------------------

    def create_job(
        self,
        url: str,
        status: str = "queued",
        *,
        playlist_id: str | None = None,
        position: int | None = None,
        youtube_video_id: str | None = None,
    ) -> Job:
        # The batch columns are keyword-only and default None so every R1 caller
        # (`routes/jobs.py`) stays a single-song paste — `playlist_id IS NULL` — with no
        # change; a batch member (T-302) passes all three (ADR-027).
        job = Job(
            id=uuid.uuid4().hex,
            url=url,
            status=status,
            created_at=_now(),
            playlist_id=playlist_id,
            position=position,
            youtube_video_id=youtube_video_id,
        )
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO jobs "
                "(id, url, status, created_at, playlist_id, position, youtube_video_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    job.id,
                    job.url,
                    job.status,
                    job.created_at,
                    job.playlist_id,
                    job.position,
                    job.youtube_video_id,
                ),
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
        reason: str | None = None,
        contradictions: list[str] | None = None,
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
            reason=reason,
            contradictions=contradictions or [],
        )
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO reviews "
                "(id, job_id, staging_path, query, candidate_ids_json, "
                "candidate_scores_json, rec, status, reason, contradictions_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    review.id,
                    review.job_id,
                    review.staging_path,
                    review.query,
                    json.dumps(review.candidate_ids),
                    json.dumps(review.candidate_scores),
                    review.rec,
                    review.status,
                    review.reason,
                    json.dumps(review.contradictions),
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

        A standalone review-only sweep (still exercised directly by the review tests).
        The coordinated boot path uses `reconcile_orphans_on_boot`, which folds this same
        reset into one transaction with the job sweep so the two tables cannot disagree.
        The work queue is in-memory, so a row left `resolving` at boot has no worker
        coming for it and would sit invisible to the queue forever. Returns how many rows
        were reconciled.

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

    # --- playlists + membership (R2, T-300 / ADR-027) ---------------------

    def upsert_playlist(self, youtube_playlist_id: str, title: str) -> Playlist:
        """Create the `playlists` row for this YouTube playlist, or return the existing one.

        An **atomic** create-or-reuse (ADR-027 seam 6): `INSERT … ON CONFLICT DO NOTHING`
        then SELECT, in one connection/transaction — NOT SELECT-then-INSERT, which races a
        concurrent double-paste into an `IntegrityError` on the UNIQUE key. On a re-paste
        the INSERT no-ops and the SELECT returns the original row (same `id`, same
        `jellyfin_playlist_id`), which is what makes the re-paste idempotent (T-307).

        The title is only written on first insert; a re-paste keeps the original derived
        title (ON CONFLICT DO NOTHING) rather than clobbering it.
        """
        new_id = uuid.uuid4().hex
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO playlists (id, youtube_playlist_id, title, created_at) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(youtube_playlist_id) DO NOTHING",
                (new_id, youtube_playlist_id, title, _now()),
            )
            row = conn.execute(
                "SELECT * FROM playlists WHERE youtube_playlist_id = ?",
                (youtube_playlist_id,),
            ).fetchone()
        return _playlist_from_row(row)

    def get_playlist(self, playlist_id: str) -> Playlist | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM playlists WHERE id = ?", (playlist_id,)
            ).fetchone()
        return _playlist_from_row(row) if row else None

    def get_playlist_by_youtube_id(self, youtube_playlist_id: str) -> Playlist | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM playlists WHERE youtube_playlist_id = ?",
                (youtube_playlist_id,),
            ).fetchone()
        return _playlist_from_row(row) if row else None

    def set_jellyfin_playlist_id(
        self, playlist_id: str, jellyfin_playlist_id: str
    ) -> None:
        """Record the Jellyfin playlist id once it's created (T-304, at `batch.queued`)."""
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE playlists SET jellyfin_playlist_id = ? WHERE id = ?",
                (jellyfin_playlist_id, playlist_id),
            )
            # Same guard as update_job_status: an unknown id must raise, not silently
            # succeed and leave the batch without a playlist to append to.
            if cur.rowcount == 0:
                raise KeyError(f"no playlist with id {playlist_id!r}")

    def add_member(
        self,
        playlist_id: str,
        youtube_video_id: str,
        position: int,
        jellyfin_item_id: str | None = None,
    ) -> bool:
        """Record a track's membership in a playlist. A **no-op when it already exists**.

        Returns True if a row was written, False if the (playlist, video) pair was already
        a member — the append is idempotent by construction (ADR-027 seam 4:
        `UNIQUE(playlist_id, youtube_video_id)`, so a re-paste of an already-in-playlist
        video cannot double-add). `jellyfin_item_id` is None for a *pending* append (the
        file hasn't been resolved to its Jellyfin item yet — ADR-027 seam 1); T-304
        reconciles it later.
        """
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO playlist_members "
                "(id, playlist_id, youtube_video_id, position, jellyfin_item_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(playlist_id, youtube_video_id) DO NOTHING",
                (
                    uuid.uuid4().hex,
                    playlist_id,
                    youtube_video_id,
                    position,
                    jellyfin_item_id,
                    _now(),
                ),
            )
            return cur.rowcount > 0

    def list_members(self, playlist_id: str) -> list[PlaylistMember]:
        """Every membership row for a playlist, in playlist order (T-306/T-312 read this).

        `ORDER BY position, rowid` — the rowid tie-break makes order deterministic even
        if two members share a `position` (nothing enforces position-uniqueness; a
        dedup-skip re-adds at the entry's own index, which can collide). Without it
        SQLite's order among equal positions is rowid-dependent and can vary, silently
        reshuffling a backfilled playlist across reads.
        """
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM playlist_members WHERE playlist_id = ? "
                "ORDER BY position, rowid",
                (playlist_id,),
            ).fetchall()
        return [_member_from_row(row) for row in rows]

    # --- boot reconciliation ----------------------------------------------

    def reconcile_orphans_on_boot(self) -> tuple[int, int, int]:
        """Reconcile jobs AND reviews orphaned by a crash/shutdown — in one coordinated,
        ordered transaction (T-104). Returns `(reviews_reset, jobs_reviewed, jobs_errored)`.

        Replaces the two independent boot sweeps that used to run back-to-back and could
        disagree: failing every `queued`/`running` job to `error` while, separately,
        resetting every `resolving` review to `pending` left a restart mid-resolve with
        `job=error` AND `review=pending` — a dead error over a live review. That is the
        exact T-029 orphan (`_repark_after_release` in jobs.py), recreated through the boot
        door: the review is resolvable but the job it points at is a terminal `error`, so a
        reconnecting card follows the job to a dead error with no queue view to reach the
        still-pending row from.

        **Order is the whole fix — reviews first, then jobs.** Only once the reviews are
        reconciled is the set of jobs that *own a pending review* known, so a job whose
        review points back at it can settle to `review` — the same terminal shape
        `run_pipeline` uses when it first parks — and AGREE with its review. Failing jobs
        first (the old order) reproduces the bug.

        The three steps, in one transaction so the tables can never be seen half-reconciled:

        1. Reviews stranded `resolving` return to `pending` (`last_error` cleared — a crash
           is not a failed pick, T-029 finding #3). Same effect as `reset_resolving_reviews`.
        2. A `queued`/`running` job that now owns a `pending` review settles to `review`.
           The set is computed AFTER step 1, so it captures both the just-reset rows and any
           review already `pending` (job flipped to `running` by `submit_resolve`, restart
           before the resolve claimed it) — both must agree to `review`, not `error`.
        3. Every remaining `queued`/`running` orphan (no pending review — a bare interrupted
           download, or a `queued` job that never started) fails to `error`: the in-memory
           queue is gone, nothing is coming for it, and it would report `running` forever.
           Step 2's winners are already `review`, so this UPDATE no longer touches them.

        A parked-then-restarted job is untouched: `run_pipeline`'s first park already makes
        `job=review` durable, and every step here only reads `queued`/`running`.
        """
        with self._connect() as conn:
            reviews_reset = conn.execute(
                "UPDATE reviews SET status = ?, last_error = NULL WHERE status = ?",
                (REVIEW_PENDING, REVIEW_RESOLVING),
            ).rowcount
            jobs_reviewed = conn.execute(
                "UPDATE jobs SET status = 'review' "
                "WHERE status IN ('queued', 'running') "
                "AND id IN (SELECT job_id FROM reviews WHERE status = ?)",
                (REVIEW_PENDING,),
            ).rowcount
            jobs_errored = conn.execute(
                "UPDATE jobs SET status = 'error' WHERE status IN ('queued', 'running')"
            ).rowcount
        return reviews_reset, jobs_reviewed, jobs_errored


def _job_from_row(row: sqlite3.Row) -> Job:
    return Job(
        id=row["id"],
        url=row["url"],
        status=row["status"],
        created_at=row["created_at"],
        # NULL on an R1 single-song paste and on any row written before the T-300
        # migration — which is exactly a single-song paste, so the R1 read is unchanged.
        playlist_id=row["playlist_id"],
        position=row["position"],
        youtube_video_id=row["youtube_video_id"],
    )


def _playlist_from_row(row: sqlite3.Row) -> Playlist:
    return Playlist(
        id=row["id"],
        youtube_playlist_id=row["youtube_playlist_id"],
        title=row["title"],
        jellyfin_playlist_id=row["jellyfin_playlist_id"],
        created_at=row["created_at"],
    )


def _member_from_row(row: sqlite3.Row) -> PlaylistMember:
    return PlaylistMember(
        id=row["id"],
        playlist_id=row["playlist_id"],
        youtube_video_id=row["youtube_video_id"],
        position=row["position"],
        jellyfin_item_id=row["jellyfin_item_id"],
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
        # T-206; NULL/absent on the R1 path or a pre-migration row → "" / [] via the same
        # degrade-never-raise rule as candidate_scores above.
        reason=row["reason"],
        contradictions=json.loads(row["contradictions_json"] or "[]"),
    )


@lru_cache
def get_store() -> Store:
    """Cached accessor — one Store per process, path from Settings (mirrors
    get_settings). Schema init is the caller's job at startup (main.py lifespan),
    not a side effect of first access."""
    return Store(get_settings().db_path)
