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
  `reviews.candidate_ids_json` is a JSON array of MBID strings, nothing more.
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
from dataclasses import dataclass
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
    id                 TEXT PRIMARY KEY,
    job_id             TEXT NOT NULL REFERENCES jobs(id),
    staging_path       TEXT NOT NULL,
    query              TEXT NOT NULL,
    candidate_ids_json TEXT NOT NULL,
    rec                TEXT NOT NULL,
    status             TEXT NOT NULL
);
"""


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
    """

    id: str
    job_id: str
    staging_path: str
    query: str
    candidate_ids: list[str]
    rec: str  # the beets `task.rec` recommendation, recorded as text
    status: str  # e.g. "pending" | "resolved" | "rejected"


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

    # --- reviews ----------------------------------------------------------

    def create_review(
        self,
        job_id: str,
        staging_path: str,
        query: str,
        candidate_ids: list[str],
        rec: str,
        status: str = "pending",
    ) -> Review:
        review = Review(
            id=uuid.uuid4().hex,
            job_id=job_id,
            staging_path=staging_path,
            query=query,
            candidate_ids=candidate_ids,
            rec=rec,
            status=status,
        )
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO reviews "
                "(id, job_id, staging_path, query, candidate_ids_json, rec, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    review.id,
                    review.job_id,
                    review.staging_path,
                    review.query,
                    json.dumps(review.candidate_ids),
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
    )


@lru_cache
def get_store() -> Store:
    """Cached accessor — one Store per process, path from Settings (mirrors
    get_settings). Schema init is the caller's job at startup (main.py lifespan),
    not a side effect of first access."""
    return Store(get_settings().db_path)
