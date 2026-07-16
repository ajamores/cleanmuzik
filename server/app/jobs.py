"""Job orchestration — the pipeline spine run on a worker thread (T-012, spec §4/§6).

Every ticket before this built one stage in isolation; this module is where they
finally run as one job. `run_pipeline` walks a single song through the full spine —
download (T-004) → transcode (T-005) → normalize (T-006) → the fingerprint-trust
import (T-007, which also tags / arts / genres / lyrics / organizes and does
acquire-time dedup) → Jellyfin scan (T-010) — sequentially, one track at a time.

## Why a single worker thread draining a queue (ADR-001)

The pipeline must never run on the asyncio event loop: beets shells out to fpcalc,
ffmpeg transcodes, yt-dlp downloads — all blocking, all seconds long. And ADR-001
forbids parallelizing the pipeline at all (it would trip AcoustID/download rate
limits). So there is exactly **one** `JobWorker` thread, and `POST /api/jobs` only
*enqueues* — even two near-simultaneous pastes run strictly one-after-another. The
"sequential queue" in the ticket title is that queue.

## Two places state lives, on purpose

- **SQLite `jobs.status`** (T-002) is the durable lifecycle — `queued → running →
  {done | review | error}` — and it is the part that must survive a restart (spec
  §7 is about parked *reviews* surviving; a job's coarse status rides along).
- **The in-memory `JobRegistry`** holds the *live* detail a reconnecting client
  wants but that needn't outlive the process: the current stage, the failing stage
  + message, the parked review id. After a restart there is no in-flight job, so
  losing this is correct, not a gap. `GET /api/jobs/{id}` overlays the two.

The fine-grained per-stage *streaming* (SSE, the spec §6 event catalogue) is T-013;
this module marks the stage and records the outcome, and the registry is the seam
T-013 builds the stream on top of.

## Staging cleanup contract (from the import seam)

The seam (`finalize_outcomes`) fixes the rule and this module honours it: a
**"parked"** outcome *retains* its staging file — it IS the copy the owner resolves
— while **"landed"**, **"skipped"**, and any **error** are safe to delete. So the
staging dir is removed on every terminal path except a park.
"""

import logging
import os
import queue
import shutil
import tempfile
import threading
from dataclasses import dataclass, replace
from pathlib import Path

import acoustid
from mediafile import MediaFile

from app.config import Settings, get_settings
from app.db import Store
from app.download import download_song
from app.import_seam import import_song
from app.jellyfin import JellyfinScanError, trigger_scan
from app.normalize import normalize_title
from app.transcode import transcode_to_mp3_320

logger = logging.getLogger("cleanmuzik")

# Stage names — the spec §6 `track.error` vocabulary ("download|transcode|identify
# |tag|land|scan"). The gate (import_song) folds identify → tag → land into one
# atomic call, so run_pipeline can only attribute a failure inside it coarsely: a
# missing fingerprint backend is "identify", any other beets apply/organize error is
# "land". T-013's finer emission can subdivide if a real case ever needs it.
STAGE_DOWNLOAD = "download"
STAGE_TRANSCODE = "transcode"
STAGE_IDENTIFY = "identify"
STAGE_LAND = "land"
STAGE_SCAN = "scan"

# Durable + live status values (mirrors app.db.Job.status examples).
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_REVIEW = "review"
STATUS_ERROR = "error"


@dataclass(frozen=True)
class JobState:
    """Live, in-memory snapshot of one job — what the reconnect route overlays.

    Frozen so the route can read a reference without a lock racing a mutation; the
    registry swaps the whole object under its lock on every update. The durable
    `url` / `created_at` live in the SQLite row, not here — this holds only the
    volatile, process-lifetime detail (the current stage, a failure, a parked id).
    """

    job_id: str
    status: str
    stage: str | None = None
    review_id: str | None = None
    error: str | None = None


# Cap on retained job states — the registry keeps recent jobs so a client can still
# reconnect just after one finishes, but must not grow without bound on a long-lived
# always-on host (Phase 1). Oldest terminal states fall off first; the durable SQLite
# row still answers a snapshot for an evicted job.
_REGISTRY_CAP = 256


class JobRegistry:
    """Thread-safe map of job_id → live `JobState`. Written by the worker thread,
    read by the route on the event loop; a lock plus whole-object replacement keeps
    reads consistent without copying. Insertion-ordered so eviction is oldest-first."""

    def __init__(self, cap: int = _REGISTRY_CAP) -> None:
        self._states: dict[str, JobState] = {}
        self._lock = threading.Lock()
        self._cap = cap

    def start(self, job_id: str) -> None:
        with self._lock:
            self._states[job_id] = JobState(job_id, STATUS_RUNNING, STAGE_DOWNLOAD)
            self._evict_locked()

    def set_stage(self, job_id: str, stage: str) -> None:
        with self._lock:
            state = self._states.get(job_id)
            if state is not None:
                self._states[job_id] = replace(state, stage=stage)

    def finish(
        self,
        job_id: str,
        *,
        status: str,
        stage: str | None = None,
        review_id: str | None = None,
        error: str | None = None,
    ) -> JobState | None:
        with self._lock:
            state = self._states.get(job_id)
            if state is None:
                return None
            updated = replace(
                state, status=status, stage=stage, review_id=review_id, error=error
            )
            self._states[job_id] = updated
            return updated

    def get(self, job_id: str) -> JobState | None:
        with self._lock:
            return self._states.get(job_id)

    def _evict_locked(self) -> None:
        # Caller holds the lock. Drop oldest entries past the cap; the one just
        # inserted is newest, so it is never the eviction target.
        while len(self._states) > self._cap:
            oldest = next(iter(self._states))
            del self._states[oldest]


class _StageFailure(Exception):
    """Internal: a stage failed. Carries which stage so run_pipeline's single
    handler can record it (spec §7 forced-failure names the stage) without a tower
    of nested try/except around each step."""

    def __init__(self, stage: str, message: str) -> None:
        super().__init__(f"{stage}: {message}")
        self.stage = stage
        self.message = message


def _read_normalized_query(mp3_path: Path) -> str:
    """The normalized title (T-006) to record on a parked review, read off the
    transcoded MP3's embedded tags (carried through by transcode's -map_metadata).

    Best-effort: this feeds the review-queue *display* (spec §5 "the normalized
    query that was searched"), not the fingerprint gate, so an unreadable tag
    degrades to an empty query rather than failing the job. beets matches on the
    file's own tags regardless.
    """
    try:
        media = MediaFile(os.fspath(mp3_path))
    except Exception as exc:  # noqa: BLE001 — a tag read must not fail the job
        logger.warning("could not read tags off %s (%s) — empty query", mp3_path, exc)
        return ""
    title = media.title or ""
    if not title:
        return ""
    return normalize_title(title, media.artist or None)


def run_pipeline(
    job_id: str,
    url: str,
    *,
    store: Store,
    registry: JobRegistry,
    settings: Settings | None = None,
    staging_root: Path | None = None,
    download_fn=download_song,
    transcode_fn=transcode_to_mp3_320,
    import_fn=import_song,
    scan_fn=trigger_scan,
) -> JobState:
    """Run one song through the whole spine on the calling (worker) thread.

    Sequential and blocking by contract (ADR-001) — the caller is `JobWorker`'s
    thread, never the event loop. Updates the durable `jobs.status` and the live
    `registry` as it goes, and returns the terminal `JobState`. Never raises: every
    failure becomes an `error` outcome with the failing stage recorded and the
    staging directory cleaned up. The stage functions are injectable so the
    orchestration is unit-testable offline (matches the seam's `dominance_fn`).

    Precondition: `job_id` names a row already created via `store.create_job` — the
    seam parks reviews against it as a foreign key.
    """
    s = settings or get_settings()
    registry.start(job_id)  # constructs the state at stage "download"
    _set_status(store, job_id, STATUS_RUNNING)

    # One staging dir per job — download/transcode both write here, and it is the
    # single thing to remove on cleanup. Owned here (not left to download_fn's
    # default) so cleanup is unconditional regardless of where a failure lands.
    # `staging_root` (default: the system temp) lets tests keep staging under a
    # tmp_path pytest cleans, rather than leaking real /tmp dirs on the parked path.
    staging_dir = Path(tempfile.mkdtemp(prefix="cleanmuzik-", dir=staging_root))
    retain_staging = False

    try:
        # 1. Download bestaudio into staging (playlist URLs were refused at the route).
        try:
            source = download_fn(url, staging_dir)
        except Exception as exc:  # noqa: BLE001 — attributed to the stage below
            raise _StageFailure(STAGE_DOWNLOAD, str(exc)) from exc

        # 2. Transcode to MP3 320 CBR (ADR-002), alongside the source in staging.
        registry.set_stage(job_id, STAGE_TRANSCODE)
        try:
            mp3 = transcode_fn(source)
        except Exception as exc:  # noqa: BLE001
            raise _StageFailure(STAGE_TRANSCODE, str(exc)) from exc

        # 3. Normalize the title for the review-queue display (pure, no failure path).
        query = _read_normalized_query(mp3)

        # 4. The gate: identify → tag → art → genre → lyrics → organize, plus
        #    acquire-time dedup. import_song swallows its own transient AcoustID
        #    errors (it parks); what escapes is a vanished fingerprint backend
        #    (identify) or a beets apply/organize failure (land).
        registry.set_stage(job_id, STAGE_IDENTIFY)
        try:
            outcomes = import_fn(mp3, store=store, job_id=job_id, query=query, settings=s)
        except acoustid.NoBackendError as exc:
            raise _StageFailure(STAGE_IDENTIFY, f"fingerprint backend unavailable: {exc}") from exc
        except Exception as exc:  # noqa: BLE001 — a beets tag/land failure
            # choose_item may have parked a review (writing its row) *before* a later
            # beets stage raised. That review's staging_path points into this dir, so
            # deleting it would orphan a review the owner can't resolve — data loss.
            # Detect the committed park and honour it (retain staging, report review)
            # rather than treat the whole job as a land failure.
            parked = store.get_pending_review_for_job(job_id)
            if parked is not None:
                retain_staging = True
                logger.warning(
                    "import raised after parking %s (%s) — keeping staging, "
                    "treating as review",
                    job_id, exc,
                )
                return _finish(
                    store, registry, job_id,
                    status=STATUS_REVIEW, review_id=parked.id,
                )
            raise _StageFailure(STAGE_LAND, str(exc)) from exc

        # 5. Interpret the seam's receipt. One singleton yields one outcome; guard
        #    the shapes rather than assume. Park wins (it retains staging), then a
        #    real landing (which triggers a scan), else a skip (duplicate kept /
        #    beets-skipped — nothing new landed, so no scan).
        parked = next((o for o in outcomes if o.action == "parked"), None)
        if parked is not None:
            retain_staging = True
            return _finish(
                store, registry, job_id,
                status=STATUS_REVIEW, review_id=parked.review_id,
            )

        landed = any(o.action == "landed" for o in outcomes)
        if landed:
            # 6. Nudge Jellyfin so the track appears in seconds (T-010). A missing
            #    config degrades to a warning (still landed); a present-but-failed
            #    config is a genuine scan-stage error (the file stays on disk).
            registry.set_stage(job_id, STAGE_SCAN)
            try:
                scan_fn(settings=s)
            except JellyfinScanError as exc:
                raise _StageFailure(STAGE_SCAN, str(exc)) from exc
            return _finish(store, registry, job_id, status=STATUS_DONE)

        # No outcome at all: the song neither landed nor parked (e.g. beets skipped
        # the task before choose_item could decide). That is a silent vanish, not a
        # success — surface it as an error the owner can act on, not a false "done".
        if not outcomes:
            return _finish(
                store, registry, job_id, status=STATUS_ERROR, stage=STAGE_IDENTIFY,
                error="the song neither landed nor parked — nothing to show",
            )

        # All skipped (duplicate already in the library, or beets skipped it): the
        # job succeeded — nothing new to land or scan.
        return _finish(store, registry, job_id, status=STATUS_DONE)

    except _StageFailure as failure:
        logger.warning(
            "job %s failed at %s: %s", job_id, failure.stage, failure.message
        )
        return _finish(
            store, registry, job_id,
            status=STATUS_ERROR, stage=failure.stage, error=failure.message,
        )
    except Exception as exc:  # noqa: BLE001 — never let the worker thread die
        logger.exception("job %s failed unexpectedly", job_id)
        return _finish(store, registry, job_id, status=STATUS_ERROR, error=str(exc))
    finally:
        # The seam's contract: only a parked song keeps its staging file.
        if not retain_staging:
            shutil.rmtree(staging_dir, ignore_errors=True)


def _finish(
    store: Store,
    registry: JobRegistry,
    job_id: str,
    *,
    status: str,
    stage: str | None = None,
    review_id: str | None = None,
    error: str | None = None,
) -> JobState:
    """Record a terminal outcome to both the durable row and the live registry."""
    _set_status(store, job_id, status)
    state = registry.finish(
        job_id, status=status, stage=stage, review_id=review_id, error=error
    )
    # finish() only returns None if the job was never started, which can't happen —
    # run_pipeline calls registry.start() before any _finish. Fall back defensively.
    return state or JobState(job_id, status, stage, review_id, error)


def _set_status(store: Store, job_id: str, status: str) -> None:
    """Update the durable job status, tolerating a vanished row (shouldn't happen —
    the job is created before the pipeline — but a missing row must not crash the
    worker mid-run)."""
    try:
        store.update_job_status(job_id, status)
    except KeyError:
        logger.error("job %s vanished before status could be set to %s", job_id, status)


class JobWorker:
    """The single background thread that runs queued jobs one at a time (ADR-001).

    Owns the `JobRegistry`. `submit` enqueues (called from the route on the event
    loop); the thread drains the queue and calls `run_pipeline` for each. Stopped
    with a sentinel so a clean shutdown doesn't abandon an in-flight job's cleanup.
    """

    def __init__(self, store: Store, settings: Settings | None = None) -> None:
        self._store = store
        self._settings = settings
        self.registry = JobRegistry()
        self._queue: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        # Reconcile jobs orphaned by a previous crash/shutdown before accepting new
        # work: the queue is in-memory, so anything still `queued`/`running` in the
        # durable table will never run again and must not report `running` forever.
        reconciled = self._store.fail_unfinished_jobs()
        if reconciled:
            logger.warning(
                "marked %d interrupted job(s) as error on startup", reconciled
            )
        self._thread = threading.Thread(
            target=self._run, name="cleanmuzik-worker", daemon=True
        )
        self._thread.start()
        logger.info("job worker started")

    def submit(self, job_id: str, url: str) -> None:
        self._queue.put((job_id, url))

    def stop(self, timeout: float = 5.0) -> None:
        """Signal shutdown and wait briefly for the worker to idle.

        Best-effort: the sentinel makes the loop exit once the *current* job returns,
        but a real pipeline job can run far longer than `timeout` (a download alone
        can), so shutdown does not block on it. A job still in flight when the process
        exits is reconciled to `error` on the next `start()` (fail_unfinished_jobs) —
        that boot sweep, not this join, is what keeps the durable status honest.
        """
        if self._thread is None:
            return
        self._queue.put(None)  # sentinel — the loop exits after the current job
        self._thread.join(timeout=timeout)
        self._thread = None
        logger.info("job worker stopped")

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            try:
                if item is None:
                    return
                job_id, url = item
                # run_pipeline never raises, but guard anyway: the worker thread
                # outliving one bad job matters more than any single job.
                run_pipeline(
                    job_id, url, store=self._store,
                    registry=self.registry, settings=self._settings,
                )
            except Exception:  # noqa: BLE001 — the loop must survive any job
                logger.exception("worker loop caught an unexpected error")
            finally:
                self._queue.task_done()
