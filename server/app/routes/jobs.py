"""Job routes — paste a URL, get a job; stream its progress; poll its snapshot (T-012/13, spec §6).

Three routes:

- `POST /api/jobs {url, intent?}` → create the `jobs` row(s), hand them to the
  worker, and return `{ job_id }` (one song) or `{ playlist_id, job_ids }` (an
  expanded playlist, R2/T-302). The response returns *immediately*; the pipeline
  runs on the worker thread (spec §4). `intent` is the ADR-029 acquire dial.
- `GET /api/jobs/{job_id}/events` → the **SSE stream** (T-013): the spec §6 event
  catalogue for that job, replayed-then-live off `app.state.worker.bus`. No polling
  (ADR/spec).
- `GET /api/jobs/{job_id}` → the reconnect / SSE-fallback snapshot: the durable row
  overlaid with the worker's live stage / error / review id.

Kept deliberately import-light. The heavy pipeline (beets, yt-dlp, ffmpeg) lives in
`app.jobs`, reached through `app.state.worker` set up in the lifespan — so importing
this module (and therefore `app.main`) does **not** pull beets at import time,
preserving T-001's lazy-engine property. `StreamingResponse` and `app.events` carry no
heavy deps, so the events route keeps that property. The playlist classifier is
imported inside the handler for the same reason (its module imports yt-dlp).
"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.db import get_store

router = APIRouter()

# Headers that keep an SSE stream alive end-to-end: no caching of the event log, and
# X-Accel-Buffering off so an intermediary (nginx, the Phase-1 reverse proxy) streams
# each event through instead of buffering the whole response.
_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
}

# Durable statuses that mean the pipeline is finished (mirrors app.jobs' STATUS_*).
# Kept as a local literal, NOT imported from app.jobs — that module pulls beets, and
# importing it here would break T-001's lazy-engine property. When a job is already in
# one of these and its SSE channel has been evicted, the stream must close at once
# rather than hang (see EventBus.stream's `terminal` hint).
_TERMINAL_STATUSES = frozenset({"done", "review", "error"})

# ADR-029 explicit-intent values. `single`/`playlist` are wired; `multi` is reserved
# geometry (a present-but-inert dial stop) whose build is backlog T-046, so the backend
# recognises but refuses it rather than 404-ing an unknown field.
_INTENTS = frozenset({"single", "playlist", "multi"})


@router.post("/jobs")
def create_job(payload: dict, request: Request) -> dict:
    """Queue a YouTube paste for the pipeline — one song, or a whole playlist (R2, T-302).

    Returns `{ job_id }` for a single song (the R1 shape, byte-for-byte) or
    `{ playlist_id, job_ids }` for an expanded batch.

    **Acquire intent is explicit (ADR-029), never silently inferred from URL shape.** An
    optional `intent` (`single | playlist`; `multi` reserved) is the dial's answer to the
    ambiguous `watch?v=X&list=PL…` paste. When it is **absent**, the classifier falls back
    to R1's shape inference verbatim, so R1 is unchanged. Intent lives only here at the
    accept door — it never rides onto the job, so it cannot leak into the pipeline
    (the `playlist_id IS NULL` column, not intent, is what keeps R1 non-regressing).
    """
    url = (payload or {}).get("url")
    if not isinstance(url, str) or not url.strip():
        raise HTTPException(status_code=422, detail="Missing 'url'.")
    url = url.strip()

    intent = (payload or {}).get("intent")
    if intent is not None:
        if not isinstance(intent, str) or intent not in _INTENTS:
            raise HTTPException(
                status_code=422,
                detail="Unknown 'intent' — expected 'single' or 'playlist'.",
            )
        if intent == "multi":
            raise HTTPException(
                status_code=422,
                detail="Multi-select acquire isn't available yet (reserved).",
            )

    # Imported here, not at module top: download.py pulls yt-dlp, which we keep off
    # the import path of the app (T-001 lazy-engine). Both classifiers are pure,
    # network-free shape checks (T-004 / T-302).
    from app.download import expandable_playlist_id, names_one_song, normalize_url

    # Normalise before classifying, storing, or submitting: a scheme-less paste
    # (`youtu.be/<id>` from a text message) classifies fine but never matches
    # yt-dlp's YouTube extractors, so the job must carry the normalised URL.
    url = normalize_url(url)

    # Two pure signals decide expand-vs-single: which curated playlist (if any) this URL
    # can expand into, and whether it names a single song. `expandable_playlist_id` is
    # deliberately narrower than R1's `is_playlist_url` — it expands only curated `PL…`/
    # `OLAK5uy_…` lists, never an unbounded `RD…` radio seed.
    playlist_id = expandable_playlist_id(url)
    names_song = names_one_song(url)

    if intent == "single":
        # The dial forces one song even from a `watch?v=X&list=PL…` — the visible-not-
        # silent replacement for R1's silent `noplaylist` strip (ADR-029). Still must
        # name a song: a pure playlist URL has nothing to single out.
        expand = False
    elif intent == "playlist":
        # The dial takes the whole list when there is one; a bare single URL left under
        # Playlist lands as one song, not a hard error (ADR-029 behaviour 4).
        expand = playlist_id is not None
    else:
        # Intent absent → R1 shape inference. R1 refused a playlist with 422; R2 expands
        # it instead (acceptance item 1). A `watch?v=X&list=PL…` still resolves to one
        # song here (it names one), so the R1 single path is byte-for-byte unchanged.
        expand = playlist_id is not None and not names_song

    if expand:
        return _expand_and_enqueue(url, request)

    # A channel/`@handle`/search URL, or a non-curated list with no song, names no single
    # song and carries no expandable playlist — admitting it lets download_song expand and
    # download a whole collection before the download-stage guard fires (T-027). Refuse it.
    if not names_song:
        raise HTTPException(
            status_code=422,
            detail="That URL doesn't point to a single song — paste one song's URL.",
        )

    job = get_store().create_job(url)
    request.app.state.worker.submit(job.id, url)
    return {"job_id": job.id}


def _expand_and_enqueue(url: str, request: Request) -> dict:
    """Expand a curated playlist URL → N enqueued track-jobs sharing a `playlists` row (T-302).

    The order matters and is ADR-027's: **upsert the row (atomic create-or-reuse) →
    create the Jellyfin playlist at queued-time → enqueue one job per entry.** Each job
    carries the shared `playlist_id`, its `position`, and its `youtube_video_id` (the
    T-303 dedup key, recorded at enqueue). The jobs otherwise run the unchanged R1/R1.1
    pipeline; a parked batch track routes to the same `/api/reviews` inbox (US6).
    """
    from app.download import PlaylistURLError, expand_playlist
    from app.jellyfin import create_playlist

    # expand_playlist does synchronous network I/O and raises PlaylistURLError on a
    # private/deleted/unavailable list or an upstream blip. Answer with a clean 502 rather
    # than letting it surface as a 500 — nothing has been written yet, so this is a safe
    # bail-out (the upsert/create/enqueue below only run for a list we actually expanded).
    try:
        expanded = expand_playlist(url)
    except PlaylistURLError as exc:
        raise HTTPException(
            status_code=502,
            detail="Couldn't expand that playlist from YouTube — it may be private or "
            "unavailable. Check the link and try again.",
        ) from exc

    # An empty (or all-deleted) playlist has nothing to queue. Refuse it *before* writing
    # anything — otherwise we'd leave a phantom `playlists` row and a stray empty Jellyfin
    # playlist with no signal that zero tracks were enqueued.
    if not expanded.entries:
        raise HTTPException(
            status_code=422,
            detail="That playlist has no playable tracks to queue.",
        )

    store = get_store()

    # Atomic create-or-reuse (ADR-027 seam 6): a re-paste reuses the original row (same
    # id, same title, same jellyfin_playlist_id) — the foundation of idempotent re-paste.
    playlist = store.upsert_playlist(expanded.youtube_playlist_id, expanded.title)

    # Create-at-queued (ADR-027 seam 3), gated so a re-paste never re-creates: on reuse the
    # row already carries its jellyfin_playlist_id. `create_playlist` degrades to None on an
    # absent/failed Jellyfin (owner-settled) — the batch still expands and lands; a NULL id
    # falls to T-306's create-if-missing backfill (which is also the recovery path if a
    # first paste degraded here and a later re-paste finds Jellyfin healthy again).
    #
    # The `is None` check-then-create is deliberately NOT hardened against two *simultaneous*
    # first-pastes of the same brand-new playlist (both would see NULL and each POST a
    # Jellyfin playlist). This is a single-user, no-auth tool (ADR-004); that race needs one
    # human to double-submit the same new list in the same instant, and its only residue is
    # one empty orphan Jellyfin playlist — the `playlists` row still ends with a valid id and
    # no track is lost. Not worth a compare-and-set for a cosmetic single-user edge.
    if playlist.jellyfin_playlist_id is None:
        jellyfin_playlist_id = create_playlist(playlist.title)
        if jellyfin_playlist_id is not None:
            store.set_jellyfin_playlist_id(playlist.id, jellyfin_playlist_id)

    worker = request.app.state.worker
    job_ids: list[str] = []
    for position, entry in enumerate(expanded.entries, start=1):
        job = store.create_job(
            entry.url,
            playlist_id=playlist.id,
            position=position,
            youtube_video_id=entry.video_id,
        )
        worker.submit(job.id, entry.url)
        job_ids.append(job.id)

    return {"playlist_id": playlist.id, "job_ids": job_ids}


@router.get("/jobs/{job_id}/events")
async def stream_job_events(job_id: str, request: Request) -> StreamingResponse:
    """SSE stream of the spec §6 event catalogue for one job (T-013).

    404s an unknown job (a stream for a job that never existed is a client error, not
    an empty stream). Otherwise returns a `text/event-stream` fed by the worker's
    `EventBus`: the generator replays events already emitted this process (so a card
    that connects just after POST doesn't miss `job.queued`), then live-streams the
    rest with `ping` keepalives, and closes when the job reaches a terminal state.
    Starlette cancels the generator on client disconnect; the bus unsubscribes in its
    `finally`.
    """
    job = get_store().get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"No job {job_id}.")
    bus = request.app.state.worker.bus
    return StreamingResponse(
        bus.stream(job_id, terminal=job.status in _TERMINAL_STATUSES),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@router.get("/jobs/{job_id}")
def get_job(job_id: str, request: Request) -> dict:
    """Status snapshot for reconnect / SSE fallback (spec §6).

    Durable lifecycle (`status`, `url`, `created_at`) comes from SQLite so it
    answers even after a restart; the live worker registry overlays the current
    stage, the failing stage + message, or the parked review id while the job is (or
    recently was) in flight this process.

    After a restart the registry is empty. The parked `review_id` is still recovered
    from the durable reviews table so the reconnect-to-review flow survives; the
    fine-grained `stage`/`error` of a past run are process-lifetime only (the spec §6
    `jobs` schema has no column for them) and are simply absent post-restart.
    """
    store = get_store()
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"No job {job_id}.")

    snapshot: dict = {
        "job_id": job.id,
        "url": job.url,
        "status": job.status,
        "created_at": job.created_at,
    }
    # No landing path/tags here: the landing detail rides the terminal SSE event, not the
    # durable row (ADR-015). A card recovers the path from the replayed `track.done` /
    # `track.error`; after a restart (empty replay buffer) it shows a bare status and the
    # owner re-scans — the file is at a deterministic library path regardless.

    live = request.app.state.worker.registry.get(job_id)
    if live is not None:
        if live.stage is not None:
            snapshot["stage"] = live.stage
        if live.review_id is not None:
            snapshot["review_id"] = live.review_id
        if live.error is not None:
            snapshot["error"] = live.error
    elif job.status == "review":
        # Cold registry (restart): recover the parked review id from SQLite.
        pending = store.get_pending_review_for_job(job_id)
        if pending is not None:
            snapshot["review_id"] = pending.id
    return snapshot
