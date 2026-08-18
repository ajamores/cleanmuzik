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
from datetime import datetime, timezone
from pathlib import Path

import acoustid
from mediafile import MediaFile

from app.config import Settings, get_settings
from app.db import (
    REVIEW_REJECTED,
    REVIEW_RESOLVED,
    Review,
    Store,
)
from app.download import curated_list_kind, download_song
from app.events import EventBus, candidate_row
from app.import_seam import (
    ResolveError,
    get_library,
    import_song,
    items_for_recording,
    resolve_asis_import,
    resolve_import,
)
from app.jellyfin import (
    JellyfinAppendError,
    JellyfinScanError,
    ResolveStatus,
    append_to_playlist,
    create_playlist,
    get_playlist_item_ids,
    resolve_item_id,
    trigger_scan,
)
from app.normalize import normalize_title
from app.reviews import (
    CHOICE_KEEP_UNTAGGED,
    CHOICE_REJECT,
    CHOICE_REPLACE,
    ResolveRequest,
    guess_terms,
)
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
# T-303: an exact-video re-paste — already in the library, so the pipeline is skipped and
# the owned file is added to the playlist instead. A DISTINCT terminal status (not folded
# into `done`) because the batch tally (T-305/T-312) counts skips as their own bucket, and
# that tally is derived straight off `jobs.status` grouped by `playlist_id` (ADR-027 seam 5).
STATUS_SKIPPED = "skipped"


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
    of nested try/except around each step.

    `terminal` marks a resolve failure that re-trying cannot fix — the staging copy is
    gone, so no candidate the owner picks will ever land (T-029, finding #3). Such a
    failure ends the job as `error` rather than re-parking it into an unwinnable retry
    loop. Default False: an ordinary failure (MusicBrainz briefly down, a refused
    `replace`) IS retryable and re-parks."""

    def __init__(self, stage: str, message: str, *, terminal: bool = False) -> None:
        super().__init__(f"{stage}: {message}")
        self.stage = stage
        self.message = message
        self.terminal = terminal


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


# How many pending appends the *opportunistic* on-land drain resolves per landed track
# (ADR-027 seam-1 amendment, T-304). Small on purpose: each land drains a few of the
# oldest-and-most-likely-indexed pending members in the gaps the pipeline already owns,
# so a batch's playlist fills as it runs without the worker ever polling a just-landed
# file's own (least-settled) index. The background tick + boot sweep drain the tail with
# no such cap.
_ON_LAND_DRAIN_LIMIT = 5

# How many pending appends the background tick + boot sweep drain per pass (T-304). Larger
# than the on-land cap because the tick owns the *tail* — a batch's final tracks have no
# later land to trail them, so this pass, not the opportunistic drain, is what guarantees
# they eventually join the playlist. Still bounded so one pass can't monopolise the worker.
_TICK_DRAIN_LIMIT = 50

# How long a pending append may sit un-completed before it is flagged stuck (T-313). This
# replaced the give-up *counter*, which conflated retry-count with wall-clock: a fast batch
# burned a 20-try cap in seconds (dropping healthy tracks) and an outage's retries counted
# toward it too (a permanent silent drop). The replacement is a plain wall-clock bound: real
# time elapsed since the row was written at land time. It is measured from `created_at`, so a
# long outage's downtime *does* count toward it — but unlike the old counter that is harmless,
# because "stuck" is non-fatal: the row stays drainable and keeps retrying, and the flag is
# CLEARED the moment the append finally lands (`mark_member_appended`). So a track merely
# waiting out an outage may flash stuck on recovery and then un-flag itself the instant it
# indexes; only a genuinely never-completing row (never-indexable file, or a stale/deleted
# container) stays flagged — which is exactly the visibility we want. Comfortably past any
# normal scan latency. The flag is visibility, never a give-up (the surface is T-305/T-310).
_STUCK_AFTER_S = 45 * 60


def _is_past_stuck_ceiling(created_at: str, now: datetime) -> bool:
    """True if a pending row written at `created_at` has waited past `_STUCK_AFTER_S` (T-313).

    `created_at` is the ISO-8601 UTC string `_now()` writes. A malformed OR tz-naive value
    can't come from our own writes; if one somehow does — the parse fails, or the aware/naive
    subtraction raises `TypeError` — treat it as not-yet-stuck (never flag on data we can't
    trust), so the row keeps retrying rather than being marked on bad data. Both the parse and
    the subtraction are inside the guard so neither escapes to the caller's per-member handler.
    """
    try:
        started = datetime.fromisoformat(created_at)
        elapsed = (now - started).total_seconds()
    except (ValueError, TypeError):
        return False
    return elapsed > _STUCK_AFTER_S


def reconcile_pending_appends(
    store: Store,
    *,
    settings: Settings | None = None,
    limit: int,
    resolve_fn=resolve_item_id,
    append_fn=append_to_playlist,
    precheck_fn=get_playlist_item_ids,
    create_fn=create_playlist,
) -> int:
    """Drain pending Jellyfin appends; return how many pending members it cleared this pass.

    The return counts every member that reached the *appended* state this pass — real POSTs
    **plus** crash-recovery stamps (a row whose item the pre-check found already in the
    playlist, stamped without a re-POST). It is "rows cleared from the pending set", not "POSTs
    issued"; the two differ by the crash-recovered rows (repair 3, bug 2).

    The heart of ADR-027 seam 1 (as amended by T-304, reframed by T-313): a track's
    membership row was written durably at land time with `jellyfin_item_id = NULL` + its
    `landed_path`, but the Jellyfin append was deferred because a just-landed file isn't
    indexed yet. This pass resolves each pending member's path → its Jellyfin item id and
    appends it, once Jellyfin has caught up. Runs on the worker thread only (opportunistically
    after a land, on the background tick, and at boot), so it never contends with the
    sequential pipeline for the SQLite write lock (ADR-001's single-writer spirit).

    T-313 retired the give-up *counter* that made this "a retry tally used as a clock" — the
    root of T-304's three shipped bugs. The pass now branches on a 3-state resolve and a
    per-pass pre-check of each playlist's current members. Per member, in order:

    - **No `jellyfin_playlist_id`** on the parent playlist → the Jellyfin playlist itself was
      never created (config absent at expansion, or the create POST degraded). **Create it now**
      (T-306 create-if-missing) so a parked-then-resolved member can still join, and persist the
      new id (refreshing the per-pass cache so a second member of the same playlist reuses it and
      cannot double-create). If the create still fails (Jellyfin absent/flaky), defer the member
      untouched — no stuck flag: the container's fault, not the member's — and retry next pass.
    - **Pre-check unreadable** (`precheck_fn` → `None`: Jellyfin unreachable, or the stored
      playlist id is stale/deleted) → skip *every* member of this playlist this pass and defer
      untouched, **no stuck flag** — exactly like resolve-UNREACHABLE. The two `None` causes
      (transient outage vs. missing container) are indistinguishable at this layer, so flagging
      here would paint a whole backlog stuck on any multi-minute outage — the very outage/give-up
      conflation the reframe exists to kill. We never blind-append when we cannot first read the
      playlist (repair 3). A persistently-unreadable container is logged once per pass. Note the
      recovery split: a **NULL** id (never created) is fixed by T-306 create-if-missing *above*,
      before the pre-check runs; a **stale/deleted non-null** id reaches here and is only
      deferred+logged — create-if-missing does NOT fire for it (that guards NULL only). Auto-
      recovering a stale id is a tracked follow-up, not this pass's job. Only a
      *reachable-but-unindexed* row (NOT_INDEXED, below) is ever flagged stuck.
    - **Resolve UNREACHABLE** → defer this member untouched: no append, no stuck flag, no
      state change. The pre-check just succeeded, so this is a transient blip on the resolve
      call — an outage must strand nothing and spend no budget (repair 2, bug 3).
    - **Resolve NOT_INDEXED** → keep waiting; if the row has sat past the wall-clock ceiling
      (`_STUCK_AFTER_S`) flag it stuck (visible, still retried — repair 5). Never a drop.
    - **Resolve RESOLVED** → if the item is already in the pre-checked set, the POST already
      happened (a crash between POST and stamp, or a prior run): stamp without re-POSTing
      (repair 3, bug 2). Otherwise append; on success stamp and add the id to the per-pass set
      (so two rows resolving to the same item can't double-POST). A present-but-failed append
      (`JellyfinAppendError`) or a degraded no-op leaves the row pending with no penalty and no
      stuck flag (repair 4) — the disease must not survive on the append organ.

    Never raises: a reconcile failure must not kill the worker loop or a job that landed
    fine. Individual members degrade; the pass returns the count that succeeded.
    """
    pending = store.list_pending_appends(limit)
    if not pending:
        return 0
    playlists: dict[str, object] = {}  # cache: one get_playlist per playlist per pass
    item_ids: dict[str, set[str] | None] = {}  # cache: one pre-check GET per playlist per pass
    now = datetime.now(timezone.utc)
    appended = 0
    for member in pending:
        # Each member is isolated: a store error on one (e.g. a row deleted out from under
        # us between the query and the UPDATE) must not abort the drain for the rest — the
        # "never raises" contract, and ADR-003's one-failure-continues, applied per member.
        try:
            if member.playlist_id not in playlists:
                playlists[member.playlist_id] = store.get_playlist(member.playlist_id)
            playlist = playlists[member.playlist_id]
            jf_playlist_id = getattr(playlist, "jellyfin_playlist_id", None)
            if not jf_playlist_id:
                # T-306 create-if-missing: the container was never created (config absent at
                # expansion, or the create POST degraded — both leave a NULL id). Create it now
                # so a parked-then-resolved member can join, rather than skipping its container
                # forever. A still-absent/-flaky Jellyfin returns None: defer untouched (no stuck
                # — the container's fault, not the member's), retried next pass.
                title = getattr(playlist, "title", None)
                if not title:
                    continue  # no name to create the playlist under — nothing to recover here
                jf_playlist_id = create_fn(title, settings=settings)
                if not jf_playlist_id:
                    continue  # create still failing — defer, retry a later pass
                store.set_jellyfin_playlist_id(member.playlist_id, jf_playlist_id)
                # Refresh the per-pass cache so a later member of THIS playlist reads the new
                # id and does not create a second container (the double-create guard).
                playlists[member.playlist_id] = store.get_playlist(member.playlist_id)

            past_ceiling = _is_past_stuck_ceiling(member.created_at, now)

            # Pre-check the playlist's current members, once per playlist per pass. None means
            # we can't read the container — Jellyfin is unreachable, or the stored playlist id is
            # stale. Defer the whole playlist untouched (never blind-append) and — crucially — do
            # NOT flag stuck: this is indistinguishable from resolve-UNREACHABLE (both are "can't
            # read"), so flagging would paint the backlog stuck on any outage, the conflation the
            # reframe kills. Log once per playlist per pass so a persistently-missing container is
            # still visible in the log (T-306's create-if-missing is its real recovery).
            if jf_playlist_id not in item_ids:
                item_ids[jf_playlist_id] = precheck_fn(jf_playlist_id, settings=settings)
                if item_ids[jf_playlist_id] is None:
                    logger.warning(
                        "Jellyfin playlist %s unreadable this pass (unreachable, or the stored "
                        "id is stale) — deferring its pending appends untouched", jf_playlist_id,
                    )
            current = item_ids[jf_playlist_id]
            if current is None:
                continue  # can't read membership → defer, no stuck (like resolve-UNREACHABLE)

            result = resolve_fn(member.landed_path, settings=settings)
            if result.status is ResolveStatus.UNREACHABLE:
                continue  # transient blip on the resolve call — defer untouched, spend nothing
            if result.status is ResolveStatus.NOT_INDEXED:
                # Answered, but the file isn't indexed yet. Keep waiting — but if it has sat
                # past the ceiling, flag it stuck so a never-indexable file is *visible*
                # (still retried), never a silent drop.
                if past_ceiling:
                    store.mark_member_stuck(member.id)
                    logger.warning(
                        "Jellyfin append for %s (%s) is stuck — landed but not indexed past "
                        "the ceiling; flagged visible and still retried, not dropped",
                        member.youtube_video_id, member.landed_path,
                    )
                continue

            item_id = result.item_id
            if item_id in current:
                # Already in the playlist — the POST landed on a prior pass but its stamp was
                # lost to a crash (bug 2), or a prior run appended it. Stamp without re-POSTing;
                # transport/timing-independent, so no double-add.
                store.mark_member_appended(member.id, item_id)
                appended += 1
                continue

            try:
                ok = append_fn(jf_playlist_id, item_id, settings=settings)
            except JellyfinAppendError as exc:
                # A present-but-failed append (5xx / 401) — an outage on the *append* organ.
                # Leave pending, no penalty, no stuck; a later pass retries (repair 4, bug 3).
                logger.warning(
                    "Jellyfin append failed for %s (item %s) — left pending: %s",
                    member.youtube_video_id, item_id, exc,
                )
                continue
            if not ok:
                # Append degraded to a no-op (config went absent between the resolve and the
                # append). Do NOT stamp it done — that would drop the track from the playlist
                # while marking it added (silent loss). Leave it pending, no penalty.
                logger.warning(
                    "Jellyfin append degraded to a no-op for %s (item %s) — left pending",
                    member.youtube_video_id, item_id,
                )
                continue
            store.mark_member_appended(member.id, item_id)
            current.add(item_id)  # per-pass refresh: a later row resolving to the same item
            appended += 1        # must see it as present and not double-POST
        except Exception as exc:  # noqa: BLE001 — one bad member must not abort the pass
            logger.warning(
                "reconcile: skipping member %s after an unexpected error: %s",
                member.id, exc,
            )
    return appended


def _record_pending_membership(store: Store, job_id: str, landed_path: str) -> None:
    """Record a landed member's playlist slot as a pending append (T-304). No-op for R1.

    Gated on the job being a batch member (`playlist_id IS NOT NULL`): a single-song R1
    paste writes nothing here, so its land path is byte-for-byte the R1 one (acceptance
    item 11). For a member, `add_member` is idempotent (`UNIQUE(playlist_id,
    youtube_video_id)`), so a re-paste of an already-landed track is a harmless no-op.
    Best-effort: the file has landed and `track.done` must still fire, so a membership
    write that fails is logged, not raised — the row is recoverable on a re-paste, a
    dropped `track.done` is not.
    """
    try:
        job = store.get_job(job_id)
        if job is None or job.playlist_id is None:
            return  # R1 single-song path — untouched
        if not landed_path:
            # A member that landed with no canonical path can never be resolved by path,
            # so a pending row would be an undrainable dead letter (silent loss — the one
            # thing a walk-away owner can't catch). Shouldn't happen — a real landing
            # always has a path — so surface it loudly rather than record an unresolvable
            # row. The track is still on disk; the batch tally (T-312, jobs-by-status)
            # still counts it done.
            logger.warning(
                "member job %s landed with no path — cannot record a resolvable "
                "playlist membership; the track is on disk but won't auto-append", job_id,
            )
            return
        store.add_member(
            job.playlist_id,
            job.youtube_video_id,
            job.position,
            jellyfin_item_id=None,  # pending — the reconcile pass resolves + appends
            landed_path=landed_path,
        )
    except Exception as exc:  # noqa: BLE001 — a membership write must not fail a landed job
        logger.warning(
            "could not record playlist membership for job %s (%s) — "
            "recoverable on re-paste", job_id, exc,
        )


def _drain_after_land(store: Store, job_id: str, *, settings: Settings | None) -> None:
    """Opportunistically drain a few pending appends after a member lands (T-304). No-op for R1.

    Gated on the job being a batch member so the R1 path issues no extra query. Best-effort
    and bounded (`_ON_LAND_DRAIN_LIMIT`): `reconcile_pending_appends` never raises, but the
    gate lookup might, and a landed job must still reach `track.done` regardless.
    """
    try:
        job = store.get_job(job_id)
        if job is None or job.playlist_id is None:
            return  # R1 single-song path — untouched
        reconcile_pending_appends(store, settings=settings, limit=_ON_LAND_DRAIN_LIMIT)
    except Exception as exc:  # noqa: BLE001 — a drain must not fail a landed job
        logger.warning("post-land drain failed for job %s (%s)", job_id, exc)


def _try_skip_duplicate(
    job,
    *,
    store: Store,
    registry: JobRegistry,
    bus: EventBus,
    settings: Settings | None,
) -> JobState | None:
    """Exact-video dedup: skip an already-owned playlist entry, add its file instead (T-303).

    Returns the terminal `JobState` when the entry is skipped, or `None` to fall through to
    the normal pipeline. Gated by the caller to batch members (`playlist_id IS NOT NULL`), so
    a single-song R1 paste never reaches here — it keeps landing (or ADR-009-parking) exactly
    as in R1 (acceptance item 11).

    On a hit the entry is *not* downloaded/transcoded/identified/tagged. Instead:
      1. the owned file is added to this playlist (membership-guarded `add_member`, so a
         re-add of a video already in *this* playlist is a harmless no-op — ADR-027 seam 4),
         carrying the canonical `landed_path` so the append is drainable;
      2. a few pending appends are opportunistically drained (the just-added member's file
         landed long ago, so it is already indexed and usually appends on this very pass);
      3. `track.skipped` is emitted and the job ends `skipped`.

    Silent by contract — it must NOT route through the ADR-009 duplicate-park keep/replace
    prompt (that is for a different-bitrate library duplicate offered as a choice; an exact
    re-paste of a video already in *this* library is just "already have it"). A genuinely
    different upload of the same song has a different video id, misses here, and is treated
    as new (US13 — no wanted song is silently swapped out).
    """
    path = store.landed_path_for_video(job.youtube_video_id)
    if path is None or not os.path.exists(path):
        # Not owned, owned-but-unlocatable (no durable path), or the recorded file is GONE
        # — deleted, or moved by the migrate/clean job (this app's own second flow rewrites
        # library paths). A stale path can never resolve, so skipping would strand the song:
        # neither re-downloaded nor a working playlist entry, under a `skipped` status that
        # reads as success. Fall through to the normal pipeline instead — a re-acquire re-lands
        # the file and re-stamps its current path (US13: no wanted song silently missing).
        return None
    # Owned + locatable. Record the playlist slot durably (pending append), then let the
    # standard reconcile drain resolve+append it — the file is long-since indexed, so this
    # usually appends immediately. Best-effort: the skip's terminal state must still fire.
    try:
        store.add_member(
            job.playlist_id,
            job.youtube_video_id,
            job.position,
            jellyfin_item_id=None,  # pending — the reconcile pass resolves + appends
            landed_path=path,
        )
    except Exception as exc:  # noqa: BLE001 — a membership write must not fail the skip
        logger.warning(
            "could not record membership for skipped job %s (%s) — recoverable on re-paste",
            job.id, exc,
        )
    bus.publish(job.id, "track.skipped", {
        "job_id": job.id,
        "youtube_video_id": job.youtube_video_id,
        "position": job.position,
        "path": path,
    })
    _drain_after_land(store, job.id, settings=settings)
    return _finish(store, registry, job.id, bus=bus, status=STATUS_SKIPPED)


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
    # `list_kind` rides the opening event (T-026): "album" / "playlist" / None, so the
    # card can tell the owner the other tracks weren't taken. Computed from the URL, so
    # it must ride EVERY `job.queued` — the resolve-reopen one too (see `submit_resolve`)
    # — because `reopen()` clears the replay buffer, and a browser that reloads after a
    # review resolve rebuilds the card from the resume episode's buffer alone.
    bus.publish(job_id, "job.queued", {
        "job_id": job_id,
        "url": url,
        "list_kind": curated_list_kind(url),
    })
    registry.start(job_id)  # constructs the state at stage "download"
    # Exact-video dedup (T-303), BEFORE any download/transcode/identify/tag work but AFTER
    # registry.start so the skip's `_finish` updates a live state (not a phantom terminal).
    # Gated to batch members (`playlist_id IS NOT NULL`): a single-song R1 paste skips this
    # entirely and runs byte-for-byte (acceptance item 11). Per-entry order is membership-check
    # → video-dedup → process (ADR-027 seam 4); the membership-check is `add_member`'s own
    # UNIQUE guard, applied inside the skip. A hit ends the job here as `skipped`.
    job = store.get_job(job_id)
    if job is not None and job.playlist_id is not None and job.youtube_video_id:
        skipped = _try_skip_duplicate(
            job, store=store, registry=registry, bus=bus, settings=s,
        )
        if skipped is not None:
            return skipped
    # pct is omitted, not invented: the download stage doesn't report progress (spec §6
    # marks pct optional). The event still fires so the card leaves "queued".
    bus.publish(job_id, "track.downloading", {"job_id": job_id})
    _set_status(store, job_id, STATUS_RUNNING)

    # One staging dir per job — download/transcode both write here, and it is the
    # single thing to remove on cleanup. Owned here (not left to download_fn's
    # default) so cleanup is unconditional regardless of where a failure lands.
    # The root defaults to the store's own (T-106) and is durable: a park retains this
    # dir, and the system temp is not a place to leave something for days — see
    # `Store.staging_root`. The parameter still overrides it so tests stage under a
    # `tmp_path` pytest cleans.
    root = staging_root if staging_root is not None else store.staging_root
    try:
        root.mkdir(parents=True, exist_ok=True)
        staging_dir = Path(tempfile.mkdtemp(prefix="cleanmuzik-", dir=root))
    except OSError as exc:
        # Nowhere to put the download — an unwritable or full data dir. This function
        # never raises (the worker thread must survive and the job's SSE channel must be
        # closed by `_finish`), and there is no staging dir yet for the `finally` below
        # to clean, so it settles here rather than entering the try at all.
        logger.warning("could not create a staging dir under %s: %s", root, exc)
        return _finish(
            store, registry, job_id, bus=bus, status=STATUS_ERROR,
            stage=STAGE_DOWNLOAD,
            error=f"could not create a staging directory under {root}: {exc}",
        )
    retain_staging = False

    try:
        # 1. Download bestaudio into staging (playlist URLs were refused at the route).
        #    `download_fn` now returns the path AND sense 1 — the yt-dlp `SourceSignals`
        #    (R1.5, T-201) — which threads through to the import seam as reconcile evidence.
        try:
            source, signals = download_fn(url, staging_dir)
        except Exception as exc:  # noqa: BLE001 — attributed to the stage below
            raise _StageFailure(STAGE_DOWNLOAD, str(exc)) from exc

        # 2. Transcode to MP3 320 CBR (ADR-002), alongside the source in staging.
        registry.set_stage(job_id, STAGE_TRANSCODE)
        bus.publish(job_id, "track.transcoding", {"job_id": job_id})
        try:
            mp3 = transcode_fn(source)
        except Exception as exc:  # noqa: BLE001
            raise _StageFailure(STAGE_TRANSCODE, str(exc)) from exc

        # The source download has done its job: nothing downstream reads it (the query,
        # the import and the resolve all take the MP3), and MP3 320 is the output format
        # by ADR-002 — there is no re-transcode path that would want the original back.
        # Under the durable root a parked review retains this dir indefinitely, so
        # keeping the source doubles the footprint of every park for a file no resolve
        # ever opens. Best-effort: the MP3 is already on disk, and failing to tidy up is
        # not a reason to fail a job that otherwise succeeded.
        if Path(source) != Path(mp3):
            try:
                Path(source).unlink(missing_ok=True)
            except OSError as exc:
                logger.warning(
                    "could not remove the transcode source %s (%s)", source, exc
                )

        # 3. Normalize the title for the review-queue display (pure, no failure path).
        query = _read_normalized_query(mp3)

        # 4. The gate: identify → tag → art → genre → lyrics → organize, plus
        #    acquire-time dedup. import_song swallows its own transient AcoustID
        #    errors (it parks); what escapes is a vanished fingerprint backend
        #    (identify) or a beets apply/organize failure (land).
        registry.set_stage(job_id, STAGE_IDENTIFY)
        bus.publish(job_id, "track.identifying", {"job_id": job_id})
        try:
            outcomes = import_fn(
                mp3, store=store, job_id=job_id, query=query, settings=s,
                source_signals=signals,
            )
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
                _emit_review_required(
                    bus, job_id,
                    review_id=parked.id, rec=parked.rec, query=query,
                    candidates=_id_only_candidates(parked.candidate_ids),
                    staging_path=parked.staging_path,
                    reason=parked.reason,
                    contradictions=parked.contradictions,
                )
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
            _emit_review_required(
                bus, job_id,
                review_id=parked.review_id, rec=parked.rec, query=query,
                candidates=parked.candidates or [],
                staging_path=mp3,
                reason=parked.reason,
                contradictions=parked.contradictions,
            )
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
            # 6a. If this is a playlist member (T-304), record its membership NOW —
            #     durably, with the canonical path, `jellyfin_item_id` still NULL. This
            #     is tied to the LAND, not the scan, so the pending append survives even
            #     if the scan below fails: the file is on disk, its playlist slot is
            #     recorded, and the reconcile pass drains it whenever Jellyfin catches up.
            #     Gated on `playlist_id`, so a single-song R1 job touches none of this
            #     (acceptance item 11 — the R1 path stays byte-for-byte).
            _record_pending_membership(store, job_id, landed.landed_path)
            # 6b. Nudge Jellyfin so the track appears in seconds (T-010). A missing
            #    config degrades to a warning (still landed); a present-but-failed
            #    config is a genuine scan-stage error (the file stays on disk).
            registry.set_stage(job_id, STAGE_SCAN)
            try:
                scan_fn(settings=s)
            except JellyfinScanError as exc:
                # The song already landed on disk; only the Jellyfin nudge failed. Report
                # the scan error but carry the landing path/tags on the error event so the
                # card still shows where the song went (ADR-015). Mirrors run_resolve via
                # the shared helper so the two branches cannot drift.
                logger.warning(
                    "job %s landed at %s but the Jellyfin scan failed: %s",
                    job_id, landed.landed_path, exc,
                )
                return _finish_scan_failed(
                    store, registry, job_id, bus=bus,
                    path=landed.landed_path, tags=landed.tags, exc=exc,
                )
            # 6c. Opportunistic drain (T-304): resolve+append a few of the OLDEST pending
            #     members — the earlier tracks Jellyfin has had time to index by now — so
            #     the playlist fills as the batch runs, at ~0 marginal cost, and never on
            #     the R1 path. On a small batch the just-landed member is among the oldest
            #     and gets one resolve attempt too; that simply misses (not indexed yet)
            #     and is retried later — a single cheap local call, never a blocking poll.
            #     Best-effort by contract.
            _drain_after_land(store, job_id, settings=s)
            # Announce the landing: `_finish` publishes `track.done` built from the path/tags
            # below (ADR-015 — they ride the event, not a durable row).
            return _finish(
                store, registry, job_id, bus=bus, landed=True,
                landed_path=landed.landed_path, landed_tags=landed.tags,
            )

        # No outcome at all: the song neither landed nor parked (e.g. beets skipped
        # the task before choose_item could decide). That is a silent vanish, not a
        # success — surface it as an error the owner can act on, not a false "done".
        if not outcomes:
            return _finish(
                store, registry, job_id, bus=bus, status=STATUS_ERROR,
                stage=STAGE_IDENTIFY,
                error="the song neither landed nor parked — nothing to show",
            )

        # All outcomes are "skipped": beets accepted a match but then refused to
        # copy the file (its own duplicate stage, despite our neutralization, or an
        # internal skip). This should not happen after the ADR-009 amendment (all
        # duplicates park), but if it does, surface it as an error — not a false
        # "Done" — so the owner sees something went wrong.
        return _finish(
            store, registry, job_id, bus=bus, status=STATUS_ERROR,
            stage=STAGE_LAND,
            error="the song was identified but not imported — "
                  "it may already be in your library under a different name",
        )

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

    # Flips true at the point of no return (staging dropped, row RESOLVED). Past it the
    # resolve is committed, so neither error handler may `_release` the row back to
    # `pending` — that would re-queue an import that already landed and strand it with
    # its staging copy gone (the ADR-009-class inconsistency the commit-then-scan
    # reorder exists to prevent). Post-commit code (set_stage, scan, the `track.done`
    # publish) can still raise; a failure there is reported as a job error, but the
    # review stays RESOLVED.
    committed = False
    # Bound before the try so the error handlers below can pass it to `_reject`: a
    # failure at `registry.start`/`get_review` lands there with the row's path never
    # read, and a bare `staging_path` would raise UnboundLocalError *inside* the handler
    # that exists to keep this function from raising at all.
    staging_path: Path | None = None

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
            # The file can be gone while the SQLite row survives — a crash between park
            # and resolve, a hand-cleaned staging dir, or (before T-106 moved staging off
            # the system temp) an OS sweep. This is TERMINAL (T-029, finding #3):
            # the copy the review exists to land is gone, so no candidate the owner
            # picks can ever succeed — re-parking would only loop. End the job as
            # `error` with the cause named, rather than let beets report a confusing
            # "no such file" or re-park an unwinnable review.
            raise _StageFailure(
                STAGE_LAND,
                f"the staging copy for this review is gone ({staging_path}) — "
                f"nothing to land; discard the review and re-download the song",
                terminal=True,
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
            if request.choice == CHOICE_KEEP_UNTAGGED:
                outcomes = resolve_asis_import(
                    staging_path,
                    store=store,
                    job_id=job_id,
                    query=review.query,
                    manual_title=request.manual_title,
                    manual_artist=request.manual_artist,
                    manual_album=request.manual_album,
                    manual_year=request.manual_year,
                    lib=lib,
                    settings=s,
                )
            else:
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
        committed = True

        # T-306: a parked playlist member has just been resolved — record its membership NOW,
        # durably, with the canonical path and a NULL jellyfin_item_id, exactly as
        # run_pipeline's land branch does (6a). This was the silent gap: the resolve path
        # never recorded membership, so a parked batch member resolved later never joined its
        # playlist. Tied to the LAND (this commit), not the scan below, so the slot survives a
        # scan failure and the reconcile pass drains it whenever Jellyfin catches up. A
        # single-song (null-playlist) resolve writes nothing here — the R1 path is untouched.
        _record_pending_membership(store, job_id, final_path)

        registry.set_stage(job_id, STAGE_SCAN)
        try:
            scan_fn(settings=s)
        except JellyfinScanError as exc:
            logger.warning(
                "review %s landed at %s but the Jellyfin scan failed: %s",
                review_id, final_path, exc,
            )
            # The song is on disk; report the scan error but carry the path/tags on the
            # error event so the card still shows where it went (ADR-015). Same shared
            # helper as run_pipeline, so the two branches cannot drift.
            return _finish_scan_failed(
                store, registry, job_id, bus=bus,
                path=final_path, tags=landed.tags, exc=exc,
            )

        logger.info("review %s resolved as %s — landed at %s", review_id, request.choice, final_path)
        # T-306: opportunistically drain a few pending appends now the member is recorded —
        # symmetric with run_pipeline's 6c. The just-resolved file isn't indexed yet, so this
        # mostly clears OLDER members Jellyfin has caught up on; this member's own row drains on
        # a later pass. Best-effort, bounded, and never on the R1 (null-playlist) path.
        _drain_after_land(store, job_id, settings=s)
        # Announce the landing on the resolve path too. `final_path` reflects a REPLACE
        # choice; `landed=True` (not a non-None path) marks the landing, so even a REPLACE
        # whose moved item yields no path still announces track.done (ADR-015).
        return _finish(
            store, registry, job_id, bus=bus, landed=True,
            landed_path=final_path, landed_tags=landed.tags,
        )

    except _StageFailure as failure:
        # `_StageFailure` is only ever raised pre-commit (the scan-stage failure is
        # handled inline above, not re-raised), so `committed` is False here today. The
        # guard is kept anyway so the invariant "never release a committed resolve"
        # holds by construction, not by the reader tracing every raise site.
        logger.warning("resolve %s failed at %s: %s", review_id, failure.stage, failure.message)
        if not committed and not failure.terminal:
            # Releasable AND retryable: the row goes back to `pending`, so the JOB must
            # agree — settle it to `review`, not `error` (T-029). Reporting `error` here
            # while the row is pending orphans the review: the card follows the job to a
            # dead `error` and there is no queue view to reach the still-pending row from.
            return _repark_after_release(
                store, registry, job_id, review_id,
                bus=bus, stage=failure.stage, error=failure.message,
            )
        if not committed and failure.terminal:
            # Unwinnable (staging gone): don't re-park a review no retry can resolve.
            # Discard the dead row so it leaves the queue, and end the job as `error`
            # with the cause — the two agree, and the owner re-downloads (finding #3).
            _reject(store, review_id, staging_path)
        return _finish(
            store, registry, job_id, bus=bus,
            status=STATUS_ERROR, stage=failure.stage, error=failure.message,
        )
    except Exception as exc:  # noqa: BLE001 — never let the worker thread die
        # Post-commit (set_stage, a non-JellyfinScanError scan failure, the `track.done`
        # publish): the song is already filed. Report a job error but leave the row
        # RESOLVED — releasing it would re-queue an import that already landed.
        #
        # Pre-commit: unlike a `_StageFailure` — an *anticipated*, likely-transient
        # failure worth re-parking (MusicBrainz down, a beets apply glitch) — an
        # arbitrary exception is unclassified and most likely deterministic. Re-parking
        # it hands the owner the panel again with no error ever surfaced, and re-picking
        # hits the same fault forever: a silent loop with no terminal state (T-029, #5).
        # So treat it as terminal — discard the row so its state and the job's `error`
        # AGREE (not the pending/error orphan T-029 removed), and name the cause. This
        # mirrors the terminal `_StageFailure` branch above; only a `_StageFailure` is
        # retryable, everything else errors.
        logger.exception("resolve %s failed unexpectedly", review_id)
        if not committed:
            _reject(store, review_id, staging_path)
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


def _release(store: Store, review_id: str, last_error: str) -> Review | None:
    """Return a failed resolve's review to the queue so the owner can retry it.

    `last_error` is persisted on the row (T-029) so the reason survives a reconnect —
    the SSE `message` alone would be lost with the stream (finding #2). Returns the
    released row (reused by the re-park emit, finding #6), or `None` if the row vanished
    before it could be released — the torn/vanished case the caller reports as an error.
    A locked-DB / unexpected failure is *not* swallowed here: it propagates so the
    re-park's own guard settles the job to `error` rather than letting it escape."""
    try:
        return store.release_review(review_id, last_error=last_error)
    except KeyError:
        logger.error("review %s vanished before it could be released", review_id)
        return None


def _reject(store: Store, review_id: str, staging_path: Path | None = None) -> None:
    """Discard a review the system cannot resolve (T-029 terminal path, finding #3).

    Used when the staging copy is gone: no retry can land it, so the row leaves the
    queue rather than re-parking into an unwinnable loop. Tolerates a vanished row.

    Removes the staging dir too, matching the owner-discard branch. A rejected row is a
    dead end — nothing in the UI can retry from it — and `reviews.staging_path` is NOT
    NULL, so the row goes on naming the dir and `sweep_orphan_staging` goes on counting
    it as a claim. Under the durable root (T-106) that combination strands the audio
    permanently: the OS no longer reaps it and no code path can. Cleanup runs even if
    the row already vanished — the dir is ours either way.
    """
    try:
        store.update_review_status(review_id, REVIEW_REJECTED)
    except KeyError:
        logger.error("review %s vanished before it could be discarded", review_id)
    if staging_path is not None:
        _remove_staging(staging_path)


def _repark_after_release(
    store: Store,
    registry: JobRegistry,
    job_id: str,
    review_id: str,
    *,
    bus: EventBus,
    stage: str | None,
    error: str,
) -> JobState:
    """Return a pre-commit resolve failure to the queue AND settle the job to `review`.

    T-029. A releasable resolve failure sends the row back to `pending` so the song
    stays resolvable — but the job was being settled to `error`, and the two must agree
    or the review is orphaned (the card follows the job to a dead `error`, and there is
    no standalone queue view to reach the still-pending row from). So on this path:

    - release the row (`pending`), then re-emit `track.review_required` — a *live* card
      re-renders the resolve panel with no new client machinery, and a card that lost the
      stream re-hydrates via `GET /api/jobs/{id}` → `review` → `GET /api/reviews/{id}`,
      exactly the restart path T-017 already handles;
    - carry the reason in the event's `message` so the owner learns the pick failed
      rather than being silently re-parked (do not lose the reason);
    - settle the job to `STATUS_REVIEW` (not `error`) so the durable snapshot matches the
      row — the same terminal shape `run_pipeline` uses when it first parks.

    If the row is gone (a torn/vanished review — `_release` could not release it), there
    is nothing to re-park: report the error, as before.

    Every step past the release is wrapped: a *secondary* failure here (a locked DB on
    the release UPDATE, an emit or finish that raises) must never escape run_resolve,
    whose contract is "never raises". An escape would strand the job `running` with its
    SSE stream open and the card hanging forever — the exact orphan T-029 removes, one
    layer down (finding #1). On any such secondary failure we fall through to a terminal
    `error`; the worker-loop backstop is the outer net if even that `_finish` raises.
    """
    message = f"That match couldn't be applied — {error}"
    try:
        # Persist the reason on the row (finding #2) and reuse the returned row for the
        # emit — one UPDATE ... RETURNING, no second SELECT (finding #6). The SSE
        # `message` below is the live path; the row is the durable one the client
        # re-hydrates from. `None` means the row was torn/vanished — nothing to re-park.
        review = _release(store, review_id, last_error=message)
        if review is None:
            return _finish(
                store, registry, job_id, bus=bus,
                status=STATUS_ERROR, stage=stage, error=error,
            )
        # id-only candidates: the rich display fields ride the in-memory Outcome, gone
        # once the resolve failed. The durable row keeps the MBIDs; on the client a
        # re-park re-hydrates the rich rows via GET /api/reviews/{id}, the same recovery
        # the post-park land failure and the restart path use.
        _emit_review_required(
            bus, job_id,
            review_id=review_id, rec=review.rec, query=review.query,
            candidates=_id_only_candidates(review.candidate_ids),
            staging_path=review.staging_path,
            message=message,
            reason=review.reason,
            contradictions=review.contradictions,
        )
        return _finish(
            store, registry, job_id, bus=bus,
            status=STATUS_REVIEW, review_id=review_id,
        )
    except Exception:  # noqa: BLE001 — finding #1: a re-park must never escape run_resolve
        logger.exception("re-park of review %s failed; settling the job to error", review_id)
        return _finish(
            store, registry, job_id, bus=bus,
            status=STATUS_ERROR, stage=stage, error=error,
        )


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


def sweep_orphan_staging(store: Store) -> int:
    """Remove staging dirs under `store.staging_root` that no review row points at (T-106).

    The other half of moving staging off the system temp. `/tmp` was doing the app's
    garbage collection for free: a staging dir is only removed at resolve time, and a
    review can sit unresolved indefinitely, so a durable root without this sweep trades
    a broken queue for a filling disk. Owning the retention means owning the cleanup.

    An orphan is a `cleanmuzik-*` dir named by **no** review row — the debris of a job
    that crashed between `mkdtemp` and its `finally`, or of a row deleted by hand. Every
    row counts as a claim, not just the pending ones: a `resolving` row is mid-resolve
    and its file is exactly what's being landed, and matching on status would make this
    depend on reconciliation order for no gain.

    Boot-only, and it must run **before** the worker thread starts — a dir belonging to
    a job running right now has no review row yet, so sweeping concurrently would delete
    a live download. `JobWorker.start` is the one caller for that reason.

    The root is read off the store rather than passed in so a sweep can only ever touch
    the data dir belonging to the store whose rows it just consulted — a test Store under
    a `tmp_path` cannot reach the real library's staging.
    """
    staging_root = store.staging_root
    if not staging_root.is_dir():
        return 0
    claimed = set()
    for review in store.list_reviews():
        if not review.staging_path:
            continue
        # The row names the file; the dir that gets removed is its parent, matching
        # `_remove_staging`. resolve() so a symlinked root can't make a claimed dir
        # look unclaimed and get swept.
        claimed.add(Path(review.staging_path).parent.resolve())
    removed = 0
    failed = 0
    for child in staging_root.iterdir():
        # Same prefix guard as `_remove_staging`: anything else under the root was put
        # there by something that isn't us, and is not ours to recursively delete.
        if not child.name.startswith("cleanmuzik-") or not child.is_dir():
            continue
        if child.resolve() in claimed:
            continue
        shutil.rmtree(child, ignore_errors=True)
        # Count what actually went, not what was attempted: `ignore_errors` swallows a
        # permission failure, and a log line claiming a sweep that didn't happen is
        # exactly what misleads the next person reading it.
        if child.exists():
            failed += 1
        else:
            removed += 1
    if failed:
        # The failure needs its own line, or it is indistinguishable from "nothing to
        # sweep": `ignore_errors` discarded the exception, the return value counts only
        # successes, and the caller logs only when something went. A root where deletes
        # keep failing (a held file handle, a permission problem) would otherwise fill
        # the data dir in complete silence — the "broken queue for a filling disk" trade
        # this function exists to prevent, minus any way to notice.
        logger.warning(
            "could not remove %d orphaned staging dir(s) under %s — they stay until the "
            "cause is cleared, and the data dir grows meanwhile",
            failed, staging_root,
        )
    return removed


def _finish(
    store: Store,
    registry: JobRegistry,
    job_id: str,
    *,
    bus: EventBus,
    status: str = STATUS_DONE,
    stage: str | None = None,
    review_id: str | None = None,
    error: str | None = None,
    landed_path: str | None = None,
    landed_tags: dict | None = None,
    landed: bool = False,
) -> JobState:
    """Record a terminal outcome to the durable row, the live registry, and the SSE bus.

    The single terminal choke point, so it also owns SSE closure: it emits the terminal §6
    event — `track.error` for a failure, `track.done` for a landing — then `bus.close` on
    *every* path, including a skip (which has no §6 event), so no stream is left hanging.

    Only the coarse `status` is durable (spec §7 keeps a job's status across a restart). The
    landing detail (`landed_path` / `landed_tags`) rides the terminal EVENT, not the row
    (ADR-015): the file is at a deterministic library path, so R1 shows *where the song went*
    in the moment rather than persisting it — a restart between the event and a reconnect
    shows a bare status, and the owner re-scans. `landed=True` marks a landing and is the sole
    marker, because a REPLACE resolve can land with a null path, so `landed_path is not None`
    cannot stand in for it. A clean landing takes the default `status='done'` and announces
    `track.done`; a song that reached disk whose Jellyfin scan then failed passes
    `status=STATUS_ERROR` and still carries its path/tags — on the `track.error` event, so the
    card shows the landing even though the scan is a genuine error the owner must fix. A
    skip-`done` and every non-landing outcome leave `landed=False` and carry no detail.
    """
    # Capture the live stage BEFORE finish() overwrites it: an unattributed error (the
    # defensive catch-all passes stage=None) is best named by whatever stage the job
    # was in, which is always one of spec §6's six names.
    prev = registry.get(job_id)
    _set_status(store, job_id, status)
    # Stamp the canonical library path on the landing's own row so a later re-paste of the
    # same video can add the owned file to a playlist without re-downloading it (T-303).
    # Tied to `landed` (a real landing), not to `status`: a scan-failed landing is on disk
    # but ends `error`, so its path is stamped yet never read (the dedup source filters on
    # `status='done'`). A REPLACE-resolve can land with no path — nothing to stamp, so the
    # video reads as unlocatable later and is re-processed rather than skipped. Best-effort:
    # a stamp must not fail the landing it trails (the `track.done` below is the priority).
    if landed and landed_path is not None:
        try:
            store.set_landed_path(job_id, landed_path)
        except Exception as exc:  # noqa: BLE001 — a dedup stamp must not fail a landed job
            logger.warning(
                "could not stamp landed_path for job %s (%s) — re-download on re-paste",
                job_id, exc,
            )
    state = registry.finish(
        job_id, status=status, stage=stage, review_id=review_id, error=error
    )
    if status == STATUS_ERROR:
        error_stage = stage or (prev.stage if prev else None) or STAGE_LAND
        payload: dict = {"job_id": job_id, "stage": error_stage, "message": error or ""}
        if landed:
            # A song that reached disk whose scan then failed: carry where it went on the
            # error event so the card can still show the file is in the library (ADR-015).
            payload["path"] = landed_path
            payload["tags"] = landed_tags or {}
        bus.publish(job_id, "track.error", payload)
    elif landed:
        bus.publish(job_id, "track.done", {
            "job_id": job_id, "path": landed_path, "tags": landed_tags or {},
        })
    bus.close(job_id)
    # finish() only returns None if the job was never started, which can't happen —
    # run_pipeline calls registry.start() before any _finish. Fall back defensively.
    return state or JobState(job_id, status, stage, review_id, error)


def _finish_scan_failed(
    store: Store,
    registry: JobRegistry,
    job_id: str,
    *,
    bus: EventBus,
    path: str | None,
    tags: dict | None,
    exc: Exception,
) -> JobState:
    """Terminal for a song that landed on disk but whose Jellyfin scan then failed.

    A present-but-failed scan config is a real error the owner must fix (T-010), so the job
    ends `error` at the scan stage — but the file IS in the library, so the landing path/tags
    ride the `track.error` event (ADR-015) and the card shows where it went. Shared by
    `run_pipeline` and `run_resolve` so the two scan-failure branches cannot drift (the
    T-016-class "fixed one branch, missed the other" failure — the sync-sensitive duplication
    this ticket set out to remove)."""
    return _finish(
        store, registry, job_id, bus=bus, landed=True,
        status=STATUS_ERROR, stage=STAGE_SCAN, error=str(exc),
        landed_path=path, landed_tags=tags,
    )


def _id_only_candidates(candidate_ids: list[str]) -> list[dict]:
    """Minimal `track.review_required.candidates[]` rows from bare MBIDs — the fallback
    when the rich rows were lost (the seam raised after parking). Only `candidate_id`
    is known; the display fields degrade to null and T-014 re-hydrates them."""
    return [candidate_row(cid) for cid in candidate_ids]


def _emit_review_required(
    bus: EventBus,
    job_id: str,
    *,
    review_id: str,
    rec: str | None,
    query: str,
    candidates: list[dict],
    staging_path,
    message: str | None = None,
    reason: str | None = None,
    contradictions: list[str] | None = None,
) -> None:
    """Publish the spec §6 `track.review_required` event — the one emit shape, in one
    place (T-029, finding #4). Three paths park a job: `run_pipeline`'s rich park and its
    post-park recovery, plus `run_resolve`'s re-park. They differ only in `candidates`
    (rich vs id-only) and whether a re-park `message` rides along; sharing this stops a
    future contract change (as `message` just was) from being applied to two of three.

    `staging_path` is here only to build `guess` — the re-search form's pre-fill (T-103).
    The **guess** is built here rather than by each caller so all three park paths carry
    it: the live park is the everyday case the owner fixes on the spot, and a pre-fill
    present only on the `GET /api/reviews` re-hydration would be empty exactly when it
    matters most."""
    payload = {
        "job_id": job_id,
        "review_id": review_id,
        "rec": rec,
        "query": query,
        "candidates": candidates,
        "guess": guess_terms(staging_path, query),
        # The reconcile Verdict's park story (T-206). Carried on the live event so the
        # card shows why it parked without a fetch, and kept in step with the durable row
        # (which GET /api/reviews re-hydrates from after a reload). Null/[] on the R1 path.
        "reason": reason,
        "contradictions": contradictions or [],
    }
    if message is not None:
        payload["message"] = message
    bus.publish(job_id, "track.review_required", payload)


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


@dataclass(frozen=True)
class _ReconcileWork:
    """Work item: drain pending Jellyfin appends (T-304, the background tick + boot sweep).

    Runs on the same one queue as pipeline/resolve work so the reconcile pass executes on
    the worker thread — serialized behind any in-flight download (ADR-001) and never
    contending for the SQLite write lock. `limit` caps the pass; the tick uses a larger
    bound than the opportunistic on-land drain because it owns the tail (a batch's last
    tracks, which have no later land to piggyback on).
    """

    limit: int


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

    def start(self, *, sweep_staging: bool = False) -> None:
        """Reconcile a previous run's leftovers, then take work.

        `sweep_staging` gates the one destructive step (T-106) and defaults to OFF, so
        starting a worker is safe by default. The sweep reasons that a dir with no review
        row belongs to a crashed job — true for the process that owns the data dir, false
        for a *second* process against the same `DB_PATH`, where such a dir may be a
        download in flight in the first one. Since verifying against the real server is
        routine here, a bare `JobWorker(store).start()` in a script or REPL must not be
        able to delete the owner's in-progress download. `app.main`'s lifespan is the one
        caller that opts in, because it is the one that owns the data dir.
        """
        if self._thread is not None:
            return
        # Reconcile jobs AND reviews orphaned by a previous crash/shutdown before
        # accepting new work — one coordinated pass, reviews first. The in-memory queue
        # does not survive a restart, so anything still `queued`/`running`/`resolving` in
        # the durable tables will never be picked up again and must not report `running`
        # forever. Order is the fix (T-104): a job whose review reconciles back to
        # `pending` settles to `review` — agreeing with it — not `error`; failing jobs
        # first (the old two-sweep order) recreated the T-029 orphan through the boot
        # door. See Store.reconcile_orphans_on_boot for the ordering rationale.
        reviews_reset, jobs_reviewed, jobs_errored = (
            self._store.reconcile_orphans_on_boot()
        )
        if jobs_errored:
            logger.warning(
                "marked %d interrupted job(s) as error on startup", jobs_errored
            )
        if reviews_reset or jobs_reviewed:
            logger.warning(
                "returned %d interrupted review(s) to the queue on startup "
                "(%d job(s) settled to review to agree with them)",
                reviews_reset, jobs_reviewed,
            )
        # Then the disk side of the same reconciliation (T-106): staging dirs no review
        # row claims. Deliberately after the row sweep — that pass can only ever return
        # a review to `pending`, never delete one, so no dir claimed a moment ago becomes
        # unclaimed here. Best-effort: an unsweepable disk is a disk-space problem, not a
        # reason to refuse to accept jobs.
        if sweep_staging:
            try:
                orphan_dirs = sweep_orphan_staging(self._store)
                if orphan_dirs:
                    logger.warning(
                        "swept %d orphaned staging dir(s) on startup", orphan_dirs
                    )
            except Exception as exc:  # noqa: BLE001 — best-effort by design (see above)
                logger.warning("could not sweep orphaned staging dirs: %s", exc)
        self._thread = threading.Thread(
            target=self._run, name="cleanmuzik-worker", daemon=True
        )
        self._thread.start()
        # Boot sweep (T-304): drain any appends left pending by a previous run's tail
        # (`playlist_members.jellyfin_item_id IS NULL`) right away, rather than waiting for
        # the first background tick. Restart-safe by construction — the pending rows are
        # durable and carry their `landed_path`, so a crash mid-batch loses no membership.
        self.submit_reconcile()
        logger.info("job worker started")

    def submit(self, job_id: str, url: str) -> None:
        self._queue.put(_PipelineWork(job_id, url))

    def submit_reconcile(self, limit: int = _TICK_DRAIN_LIMIT) -> None:
        """Enqueue a pending-append drain pass (T-304 background tick).

        Called from the lifespan loop on a timer. It only enqueues — the drain itself runs
        on the worker thread when it reaches the front, so it never races the pipeline for
        the SQLite lock. Cheap when there's nothing pending (`list_pending_appends` returns
        empty and the pass is a no-op), so a steady tick against an idle worker is fine.
        """
        self._queue.put(_ReconcileWork(limit))

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
        prior_status = job.status if job else None
        self.bus.reopen(job_id)
        try:
            # `list_kind` rides this reopen too (T-026, review finding): `reopen()` just
            # cleared the replay buffer, so a card that reloads after the resolve rebuilds
            # from this episode alone — omit it here and the playlist/album note is lost
            # for good on a genuinely curated URL.
            self.bus.publish(job_id, "job.queued", {
                "job_id": job_id,
                "url": job.url if job else "",
                "list_kind": curated_list_kind(job.url) if job else None,
            })
            _set_status(self._store, job_id, STATUS_RUNNING)
            self._queue.put(_ResolveWork(job_id, review_id, request))
        except Exception:
            # Undo this method's partial hand-off before re-raising. The route releases
            # the *review*; only this method knows what it touched on the *job*, so it
            # owns that rollback. Without it a failed `put` would leave the job stranded
            # at `running` with a reopened-but-silent channel: `GET /api/jobs` shows it
            # working forever and the client's EventSource waits on an event that never
            # comes. `close` re-parks the stream; the status returns to what it was.
            self.bus.close(job_id)
            if prior_status is not None:
                _set_status(self._store, job_id, prior_status)
            raise

    def stop(self, timeout: float = 5.0) -> None:
        """Signal shutdown and wait briefly for the worker to idle.

        Best-effort: the sentinel makes the loop exit once the *current* job returns,
        but a real pipeline job can run far longer than `timeout` (a download alone
        can), so shutdown does not block on it. A job still in flight when the process
        exits is reconciled on the next `start()` (reconcile_orphans_on_boot) — that
        boot sweep, not this join, is what keeps the durable status honest.
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
                elif isinstance(item, _ReconcileWork):
                    # Drain pending Jellyfin appends (T-304). Never raises; runs here so
                    # it's serialized with pipeline/resolve work, no lock contention.
                    reconcile_pending_appends(
                        self._store, settings=self._settings, limit=item.limit,
                    )
                else:
                    logger.error("worker got an unknown work item: %r", item)
            except Exception:  # noqa: BLE001 — the loop must survive any item
                logger.exception("worker loop caught an unexpected error")
                # Both runners are contracted never to raise; if one does anyway (a
                # secondary failure escaping run_resolve's re-park — T-029 #1), its job is
                # stranded `running` with an open SSE channel and the card hangs forever.
                # Backstop it: close the stream, then settle the job to `error`. Close
                # FIRST and independently, so the card is unhung even if the durable write
                # fails too (e.g. the same locked DB that caused the escape). Each step is
                # guarded so the backstop itself can never kill the worker thread.
                job_id = getattr(item, "job_id", None)
                if job_id is not None:
                    try:
                        self.bus.close(job_id)
                    except Exception:  # noqa: BLE001
                        logger.exception("backstop: could not close the stream for %s", job_id)
                    try:
                        _set_status(self._store, job_id, STATUS_ERROR)
                    except Exception:  # noqa: BLE001
                        logger.exception("backstop: could not error-set job %s", job_id)
            finally:
                self._queue.task_done()
