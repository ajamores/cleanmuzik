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
from app.db import (
    REVIEW_REJECTED,
    REVIEW_RESOLVED,
    Store,
)
from app.download import download_song
from app.events import EventBus, candidate_row
from app.import_seam import (
    ResolveError,
    get_library,
    import_song,
    items_for_recording,
    resolve_import,
)
from app.jellyfin import JellyfinScanError, trigger_scan
from app.normalize import normalize_title
from app.reviews import CHOICE_REJECT, CHOICE_REPLACE, ResolveRequest
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

    def start(self, job_id: str, stage: str = STAGE_DOWNLOAD) -> None:
        """Track `job_id` as running at `stage`, replacing any previous state.

        `stage` is a parameter because a resumed job (T-014 resolve) re-enters the
        pipeline mid-way — its file is long since downloaded — so starting it at
        "download" would report a stage that isn't happening. It also *replaces* a
        terminal state on purpose: a resolved review's job is genuinely running again.
        """
        with self._lock:
            self._states[job_id] = JobState(job_id, STATUS_RUNNING, stage)
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
    bus: EventBus | None = None,
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

    ## SSE emission (T-013)

    Each stage transition also publishes its spec §6 event to `bus` — wired into the
    *same* `registry.start` / `registry.set_stage` call sites and outcome branches, so
    the streamed sequence is exactly the state machine, never a parallel copy of it.
    `job.queued` opens it; a terminal event (`track.done` / `track.review_required`) or
    `track.error` closes it, and `_finish` fires `bus.close` on every path (a duplicate
    *skip* has no §6 event, so the sentinel — not an event name — is what ends the
    stream). `bus` defaults to a throwaway `EventBus`: a caller with no SSE (the offline
    orchestration tests) simply never subscribes, so emission is a harmless no-op and
    every call site stays unconditional.

    Precondition: `job_id` names a row already created via `store.create_job` — the
    seam parks reviews against it as a foreign key.
    """
    s = settings or get_settings()
    bus = bus or EventBus()  # no subscribers ⇒ emission just buffers into a discarded bus
    bus.publish(job_id, "job.queued", {"job_id": job_id, "url": url})
    registry.start(job_id)  # constructs the state at stage "download"
    # pct is omitted, not invented: the download stage doesn't report progress (spec §6
    # marks pct optional). The event still fires so the card leaves "queued".
    bus.publish(job_id, "track.downloading", {"job_id": job_id})
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
        bus.publish(job_id, "track.transcoding", {"job_id": job_id})
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
        bus.publish(job_id, "track.identifying", {"job_id": job_id})
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
                # The rich candidate rows were lost when the seam raised (they ride the
                # in-memory Outcome, never the row). Recover what the durable row does
                # keep — the candidate MBIDs — as id-only rows so the event is honest
                # about what's known rather than empty. T-014 re-hydrates the rest.
                bus.publish(job_id, "track.review_required", {
                    "job_id": job_id,
                    "review_id": parked.id,
                    "query": query,
                    "candidates": _id_only_candidates(parked.candidate_ids),
                })
                return _finish(
                    store, registry, job_id, bus=bus,
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
            bus.publish(job_id, "track.review_required", {
                "job_id": job_id,
                "review_id": parked.review_id,
                "query": query,
                "candidates": parked.candidates or [],
            })
            return _finish(
                store, registry, job_id, bus=bus,
                status=STATUS_REVIEW, review_id=parked.review_id,
            )

        landed = next((o for o in outcomes if o.action == "landed"), None)
        if landed is not None:
            # The tags/art/organize already happened inside the gate; emit tagging
            # here (with the chosen match) so the card shows the match before the
            # scan, matching spec §6's identifying → tagging → done ordering.
            bus.publish(job_id, "track.tagging", {
                "job_id": job_id, "chosen": landed.chosen or {},
            })
            # 6. Nudge Jellyfin so the track appears in seconds (T-010). A missing
            #    config degrades to a warning (still landed); a present-but-failed
            #    config is a genuine scan-stage error (the file stays on disk).
            registry.set_stage(job_id, STAGE_SCAN)
            try:
                scan_fn(settings=s)
            except JellyfinScanError as exc:
                raise _StageFailure(STAGE_SCAN, str(exc)) from exc
            bus.publish(job_id, "track.done", {
                "job_id": job_id, "path": landed.landed_path, "tags": landed.tags or {},
            })
            return _finish(store, registry, job_id, bus=bus, status=STATUS_DONE)

        # No outcome at all: the song neither landed nor parked (e.g. beets skipped
        # the task before choose_item could decide). That is a silent vanish, not a
        # success — surface it as an error the owner can act on, not a false "done".
        if not outcomes:
            return _finish(
                store, registry, job_id, bus=bus, status=STATUS_ERROR,
                stage=STAGE_IDENTIFY,
                error="the song neither landed nor parked — nothing to show",
            )

        # All skipped (duplicate already in the library, or beets skipped it): the
        # job succeeded — nothing new to land or scan. No §6 event fits a "nothing
        # landed" success, so the stream closes on the sentinel (bus.close in _finish)
        # and the client falls back to the GET /api/jobs snapshot (status=done).
        return _finish(store, registry, job_id, bus=bus, status=STATUS_DONE)

    except _StageFailure as failure:
        logger.warning(
            "job %s failed at %s: %s", job_id, failure.stage, failure.message
        )
        return _finish(
            store, registry, job_id, bus=bus,
            status=STATUS_ERROR, stage=failure.stage, error=failure.message,
        )
    except Exception as exc:  # noqa: BLE001 — never let the worker thread die
        logger.exception("job %s failed unexpectedly", job_id)
        return _finish(
            store, registry, job_id, bus=bus, status=STATUS_ERROR, error=str(exc)
        )
    finally:
        # The seam's contract: only a parked song keeps its staging file.
        if not retain_staging:
            shutil.rmtree(staging_dir, ignore_errors=True)


def run_resolve(
    job_id: str,
    review_id: str,
    request: ResolveRequest,
    *,
    store: Store,
    registry: JobRegistry,
    settings: Settings | None = None,
    bus: EventBus | None = None,
    lib=None,
    resolve_fn=resolve_import,
    scan_fn=trigger_scan,
) -> JobState:
    """Resume a parked import on the owner's decision and emit the tail (T-014, spec §6).

    The resolve twin of `run_pipeline`, and like it: runs on the worker thread (ADR-001
    — this re-runs a beets import, which is blocking and heavy, so it must never touch
    the event loop), never raises, and returns the terminal `JobState`. Its SSE channel
    was **reopened synchronously by `JobWorker.submit_resolve` before the route
    returned** — see that method for why the worker cannot be the one to reopen it.

    `job_id` is passed in (not read off the review) precisely so this function can still
    reach `_finish` — and therefore `bus.close` — when the review row is gone: every
    exit routes through `_finish`, so the reopened channel is never left hanging and the
    durable status is never stranded at `running`. That is why the whole body, including
    the review lookup and `registry.start`, sits inside the `try`.

    ## Staging cleanup — on every branch (spec §5)

    A park is the one terminal path that KEEPS its staging file, because that file IS
    the copy being resolved. This function is where that retention finally ends, so
    every *successful* branch removes the staging dir: accept and `keep_both` and
    `replace` (beets copied out of it), `reject` and `keep_existing` (discarded). A
    **failed** resolve deliberately keeps it and returns the review to `pending` — the
    song must stay resolvable, and deleting the file would strand the row forever.

    ## `replace` lands before it deletes (ADR-009)

    Never `DuplicateAction.REMOVE`, whose delete-then-copy loses both copies if the
    copy fails. The order here is: import the new copy → confirm it is on disk →
    only then remove the old one. See `_replace_existing`.
    """
    s = settings or get_settings()
    bus = bus or EventBus()

    try:
        registry.start(job_id, stage=STAGE_LAND)

        review = store.get_review(review_id)
        if review is None:
            # Claimed a moment ago by the route, so this is a torn/vanished row. Raise
            # rather than early-return: the channel `submit_resolve` reopened must be
            # closed by `_finish`, or the stream hangs at `running` forever. Inside the
            # try, it is — that is the whole reason `job_id` is a parameter.
            raise _StageFailure(
                STAGE_LAND,
                f"no review {review_id} — it was resolved or discarded already",
            )

        staging_path = Path(review.staging_path)

        if not request.lands:
            # reject / keep_existing: nothing to land. No §6 event fits "the owner
            # discarded it" (same shape as a duplicate skip), so the stream just
            # closes on the sentinel and the card falls back to GET /api/jobs.
            _remove_staging(staging_path)
            store.update_review_status(
                review_id,
                REVIEW_REJECTED if request.choice == CHOICE_REJECT else REVIEW_RESOLVED,
            )
            logger.info("review %s resolved as %s — nothing landed", review_id, request.choice)
            return _finish(store, registry, job_id, bus=bus, status=STATUS_DONE)

        if not staging_path.is_file():
            # Staging lives under the system temp dir, so an OS sweep can take the
            # file while the SQLite row survives. Fail with the cause named rather
            # than let beets report a confusing "no such file".
            raise _StageFailure(
                STAGE_LAND,
                f"the staging copy for this review is gone ({staging_path}) — "
                f"nothing to land; discard the review and re-download the song",
            )

        lib = lib if lib is not None else get_library(s)
        before_ids: set = set()
        if request.choice == CHOICE_REPLACE:
            # Snapshot the library BEFORE the import: this is what tells the new copy
            # from the old ones afterwards. Only `replace` reads it — after landing,
            # a query by recording id returns BOTH copies, and deleting "the duplicate"
            # without this set could delete the file we just landed. The other choices
            # never touch existing files, so they never pay for this query.
            before = items_for_recording(lib, request.recording_id)
            before_ids = {item.id for item in before}

            if len(before) > 1:
                # Spec §6 and ADR-009's addendum both say `replace` deletes "THE
                # existing library file" — singular. They don't say which one to delete
                # when two library files share a recording id, and that state is
                # reachable: it is exactly what `keep_both` creates. Deleting all of
                # them would destroy the copy the owner deliberately kept as distinct —
                # an ADR-009-class loss arriving through a door the ADR didn't
                # anticipate. So refuse, before the import lands anything: a click that
                # cannot identify its target is not consent to delete every candidate
                # for it. Checked here rather than in _replace_existing so nothing has
                # landed and nothing needs unwinding.
                paths = ", ".join(os.fsdecode(i.path) for i in before if i.path)
                raise _StageFailure(
                    STAGE_LAND,
                    f"{len(before)} library files share this recording id ({paths}) — "
                    f"'replace' cannot tell which one to delete, and deleting both would "
                    f"destroy a copy you chose to keep. Use 'keep_both' or 'keep_existing', "
                    f"or remove the unwanted copy yourself first.",
                )

        try:
            outcomes = resolve_fn(
                staging_path,
                store=store,
                job_id=job_id,
                recording_id=request.recording_id,
                query=review.query,
                suffix=request.suffix,
                lib=lib,
                settings=s,
            )
        except ResolveError as exc:
            raise _StageFailure(STAGE_LAND, str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 — a beets apply/organize failure
            raise _StageFailure(STAGE_LAND, str(exc)) from exc

        landed = next((o for o in outcomes if o.action == "landed"), None)
        if landed is None:
            raise _StageFailure(
                STAGE_LAND, "the resolved song did not land — nothing to show"
            )

        final_path = landed.landed_path
        if request.choice == CHOICE_REPLACE:
            final_path = _replace_existing(
                lib, request.recording_id, before_ids, landed
            )

        bus.publish(job_id, "track.tagging", {"job_id": job_id, "chosen": landed.chosen or {}})

        # Point of no return: the upgrade is on disk and, for `replace`, the old copy is
        # already gone. The resolve is committed — so commit the row and drop staging
        # *before* the scan. A Jellyfin scan is a downstream best-effort (T-010): if it
        # fails now, the song has still landed, and rolling the review back to `pending`
        # (what `_release` does on a _StageFailure) would re-queue an import that already
        # happened and leave the queue contradicting the library — the ADR-009-class
        # inconsistency finding. So a scan failure is reported as an error but the review
        # stays RESOLVED, mirroring how `run_pipeline` treats a post-landing scan failure.
        _remove_staging(staging_path)
        store.update_review_status(review_id, REVIEW_RESOLVED)

        registry.set_stage(job_id, STAGE_SCAN)
        try:
            scan_fn(settings=s)
        except JellyfinScanError as exc:
            logger.warning(
                "review %s landed at %s but the Jellyfin scan failed: %s",
                review_id, final_path, exc,
            )
            return _finish(
                store, registry, job_id, bus=bus,
                status=STATUS_ERROR, stage=STAGE_SCAN, error=str(exc),
            )

        bus.publish(job_id, "track.done", {
            "job_id": job_id, "path": final_path, "tags": landed.tags or {},
        })
        logger.info("review %s resolved as %s — landed at %s", review_id, request.choice, final_path)
        return _finish(store, registry, job_id, bus=bus, status=STATUS_DONE)

    except _StageFailure as failure:
        # Every _StageFailure here is pre-commit (nothing landed yet — the scan-stage
        # failure is handled inline above, after the commit), so releasing the review
        # back to `pending` for a retry is always correct.
        logger.warning("resolve %s failed at %s: %s", review_id, failure.stage, failure.message)
        _release(store, review_id)
        return _finish(
            store, registry, job_id, bus=bus,
            status=STATUS_ERROR, stage=failure.stage, error=failure.message,
        )
    except Exception as exc:  # noqa: BLE001 — never let the worker thread die
        logger.exception("resolve %s failed unexpectedly", review_id)
        _release(store, review_id)
        return _finish(store, registry, job_id, bus=bus, status=STATUS_ERROR, error=str(exc))


def _replace_existing(lib, recording_id: str, before_ids: set, landed) -> str | None:
    """Delete the owner's old copies — AFTER the upgrade is verified on disk (ADR-009).

    The one deletion R1 performs, and the ordering is the entire reason ADR-009 exists:
    beets' own `DuplicateAction.REMOVE` deletes the old file *before* it copies the new
    one, so a copy failure loses both. Here the copy has already happened and is
    confirmed present before anything is removed; if the confirmation fails we raise
    with both copies still on disk.

    Returns the new copy's final path. beets refuses to clobber, so the upgrade first
    lands beside the old file under a uniquified name (`Title.1.mp3`); once the old
    file is gone the canonical path is free, so the item is re-organized onto it and
    the library isn't left with a cosmetic `.1`. That last step is best-effort — a
    failure there leaves a correctly-tagged file at a slightly ugly path, which is not
    worth failing an otherwise-complete replace over.
    """
    after = items_for_recording(lib, recording_id)
    new_items = [item for item in after if item.id not in before_ids]
    old_items = [item for item in after if item.id in before_ids]

    if not new_items:
        raise _StageFailure(
            STAGE_LAND,
            "the upgraded copy is not in the library after the import — refusing to "
            "delete the existing file (ADR-009: never leave zero copies)",
        )
    new_item = new_items[0]
    new_path = Path(os.fsdecode(new_item.path))
    if not new_path.is_file():
        raise _StageFailure(
            STAGE_LAND,
            f"the upgraded copy is not on disk at {new_path} — refusing to delete "
            f"the existing file (ADR-009: never leave zero copies)",
        )

    for item in old_items:
        old_path = os.fsdecode(item.path)
        # delete=True removes the file AND the row, and prunes a now-empty artist
        # directory. This is the owner's explicit click, not the app's initiative.
        item.remove(delete=True)
        logger.info("replace: removed the superseded copy at %s", old_path)

    try:
        new_item.move()  # the canonical path is free now — reclaim it
    except Exception as exc:  # noqa: BLE001 — cosmetic only, the file is landed
        logger.warning(
            "replace: could not re-organize %s onto its canonical path (%s) — "
            "the upgrade is landed and correct, just not tidily named",
            new_path, exc,
        )
    # Re-read AFTER the move: the whole point of it is that the path changed, so the
    # landed_path the import reported is stale by now and would misname track.done.
    return os.fsdecode(new_item.path) if new_item.path else None


def _release(store: Store, review_id: str) -> None:
    """Return a failed resolve's review to the queue so the owner can retry it."""
    try:
        store.release_review(review_id)
    except KeyError:
        logger.error("review %s vanished before it could be released", review_id)


def _remove_staging(staging_path: Path) -> None:
    """Remove a resolved review's staging dir — the end of spec §5's retention.

    Removes the whole directory, not just the MP3: `run_pipeline` makes one
    `tempfile.mkdtemp(prefix="cleanmuzik-")` per job holding both the original
    download and the transcode, so unlinking the file alone would leak the dir and
    the source forever — the disk fills one park at a time. The prefix is checked
    before an rmtree: a hand-edited or malformed `staging_path` should cost us the
    one file, never a recursive delete of whatever directory it happens to name.
    """
    parent = staging_path.parent
    if parent.name.startswith("cleanmuzik-"):
        shutil.rmtree(parent, ignore_errors=True)
        return
    logger.warning(
        "staging path %s is not inside a cleanmuzik staging dir — removing just the "
        "file rather than its parent",
        staging_path,
    )
    try:
        staging_path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("could not remove staging file %s (%s)", staging_path, exc)


def _finish(
    store: Store,
    registry: JobRegistry,
    job_id: str,
    *,
    bus: EventBus,
    status: str,
    stage: str | None = None,
    review_id: str | None = None,
    error: str | None = None,
) -> JobState:
    """Record a terminal outcome to the durable row, the live registry, and the SSE bus.

    The single terminal choke point, so it also owns SSE closure: it emits `track.error`
    for a failure (the success/park events are emitted at their branch, where the rich
    payload is in hand) and then `bus.close` on *every* path — including a skip, which
    has no §6 event — so no stream is ever left hanging.
    """
    # Capture the live stage BEFORE finish() overwrites it: an unattributed error (the
    # defensive catch-all passes stage=None) is best named by whatever stage the job
    # was in, which is always one of spec §6's six names.
    prev = registry.get(job_id)
    _set_status(store, job_id, status)
    state = registry.finish(
        job_id, status=status, stage=stage, review_id=review_id, error=error
    )
    if status == STATUS_ERROR:
        error_stage = stage or (prev.stage if prev else None) or STAGE_LAND
        bus.publish(job_id, "track.error", {
            "job_id": job_id, "stage": error_stage, "message": error or "",
        })
    bus.close(job_id)
    # finish() only returns None if the job was never started, which can't happen —
    # run_pipeline calls registry.start() before any _finish. Fall back defensively.
    return state or JobState(job_id, status, stage, review_id, error)


def _id_only_candidates(candidate_ids: list[str]) -> list[dict]:
    """Minimal `track.review_required.candidates[]` rows from bare MBIDs — the fallback
    when the rich rows were lost (the seam raised after parking). Only `candidate_id`
    is known; the display fields degrade to null and T-014 re-hydrates them."""
    return [candidate_row(cid) for cid in candidate_ids]


def _set_status(store: Store, job_id: str, status: str) -> None:
    """Update the durable job status, tolerating a vanished row (shouldn't happen —
    the job is created before the pipeline — but a missing row must not crash the
    worker mid-run)."""
    try:
        store.update_job_status(job_id, status)
    except KeyError:
        logger.error("job %s vanished before status could be set to %s", job_id, status)


@dataclass(frozen=True)
class _PipelineWork:
    """Work item: run one URL through the full acquire pipeline (`POST /api/jobs`)."""

    job_id: str
    url: str


@dataclass(frozen=True)
class _ResolveWork:
    """Work item: resume a parked import on the owner's decision (T-014 resolve).

    The queue carries two *kinds* of work rather than a second thread on purpose:
    ADR-001 allows exactly one worker, and a resolve re-runs a beets import — the same
    blocking, rate-limit-sensitive work a pipeline run does. Sharing the one queue is
    what keeps "sequential, one track at a time" true across both entry points; a
    resolve simply waits its turn behind a running download, as it must.
    """

    job_id: str
    review_id: str
    request: ResolveRequest


class JobWorker:
    """The single background thread that runs queued jobs one at a time (ADR-001).

    Owns the `JobRegistry`. `submit` / `submit_resolve` enqueue (called from the routes
    on the event loop); the thread drains the queue and runs each work item. Stopped
    with a sentinel so a clean shutdown doesn't abandon an in-flight job's cleanup.
    """

    def __init__(self, store: Store, settings: Settings | None = None) -> None:
        self._store = store
        self._settings = settings
        self.registry = JobRegistry()
        # The SSE fan-out (T-013). Written by this worker thread via run_pipeline,
        # read by the /events route on the loop; main.py binds the loop at startup.
        self.bus = EventBus()
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
        # Same reasoning for reviews claimed by a resolve that never finished: the
        # work queue is in-memory, so a `resolving` row has no worker coming for it
        # and would be invisible to the queue forever. Return them to `pending`.
        released = self._store.reset_resolving_reviews()
        if released:
            logger.warning(
                "returned %d interrupted review(s) to the queue on startup", released
            )
        self._thread = threading.Thread(
            target=self._run, name="cleanmuzik-worker", daemon=True
        )
        self._thread.start()
        logger.info("job worker started")

    def submit(self, job_id: str, url: str) -> None:
        self._queue.put(_PipelineWork(job_id, url))

    def submit_resolve(self, job_id: str, review_id: str, request: ResolveRequest) -> None:
        """Re-open the job's stream, mark it running, and enqueue the resolve.

        **Everything before the `put` happens synchronously inside the resolve request,
        before it answers `{ok: true}`.** That ordering is the whole design, and both
        halves of it are load-bearing:

        - **`bus.reopen`** — the job's channel was closed by `_finish` when it parked
          (`close()` fires on every terminal path), and `publish()` silently drops into
          a closed channel. Without reopening first, the worker's `track.tagging` /
          `track.done` would vanish with no error and the card would never move.
        - **`status → running`** — `GET /api/jobs/{id}/events` passes
          `terminal=(status in {done, review, error})`, and a parked job sits at
          `review`. A client re-subscribing while the row still said `review` would be
          handed `terminal=True` → replay-and-return → a dead stream.

        Neither can be left to the worker thread: it is sequential (ADR-001) and may be
        minutes into someone else's download, while T-017 opens its new EventSource the
        instant this POST returns. Doing it here closes that race by construction — by
        the time the client can possibly connect, the channel is open and the status is
        `running`. The replay buffer then covers the remaining gap, delivering whatever
        the worker emitted before the subscriber actually attached.

        Note the guarantee is *ordering within the request*, not thread identity: the
        resolve route is a sync `def`, so FastAPI runs it in its threadpool rather than
        on the loop (deliberately — this method does blocking SQLite, which has no
        business on the event loop; `POST /api/jobs` is sync for the same reason).
        Nothing here needs the loop: `reopen` only takes the bus lock, and `publish`'s
        `call_soon_threadsafe` is designed for exactly this off-loop call.

        `job.queued` is re-emitted because it is true again: the job is queued, possibly
        behind a long download. It also gives the reopened episode a first event, so the
        card leaves "Needs review" immediately instead of sitting on pings.
        """
        job = self._store.get_job(job_id)
        self.bus.reopen(job_id)
        self.bus.publish(job_id, "job.queued", {
            "job_id": job_id, "url": job.url if job else "",
        })
        _set_status(self._store, job_id, STATUS_RUNNING)
        self._queue.put(_ResolveWork(job_id, review_id, request))

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
                # Neither runner raises, but guard anyway: the worker thread
                # outliving one bad item matters more than any single item.
                if isinstance(item, _PipelineWork):
                    run_pipeline(
                        item.job_id, item.url, store=self._store,
                        registry=self.registry, settings=self._settings, bus=self.bus,
                    )
                elif isinstance(item, _ResolveWork):
                    run_resolve(
                        item.job_id, item.review_id, item.request, store=self._store,
                        registry=self.registry, settings=self._settings, bus=self.bus,
                    )
                else:
                    logger.error("worker got an unknown work item: %r", item)
            except Exception:  # noqa: BLE001 — the loop must survive any item
                logger.exception("worker loop caught an unexpected error")
            finally:
                self._queue.task_done()
