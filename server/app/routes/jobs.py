"""Job routes — paste a URL, get a job; stream its progress; poll its snapshot (T-012/13, spec §6).

Three routes:

- `POST /api/jobs {url}` → refuse a playlist (422), create a `jobs` row, hand the
  job to the worker, and return `{ job_id }`. The response returns *immediately*;
  the pipeline runs on the worker thread (spec §4).
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


@router.post("/jobs")
def create_job(payload: dict, request: Request) -> dict[str, str]:
    """Queue one YouTube song for the pipeline. Rejects a playlist URL with 422."""
    url = (payload or {}).get("url")
    if not isinstance(url, str) or not url.strip():
        raise HTTPException(status_code=422, detail="Missing 'url'.")
    url = url.strip()

    # Imported here, not at module top: download.py pulls yt-dlp, which we keep off
    # the import path of the app (T-001 lazy-engine). is_playlist_url itself is a
    # pure, network-free shape check (T-004).
    from app.download import is_playlist_url, normalize_url

    # Normalise before classifying, storing, or submitting: a scheme-less paste
    # (`youtu.be/<id>` from a text message) classifies fine but never matches
    # yt-dlp's YouTube extractors, so the job must carry the normalised URL.
    url = normalize_url(url)

    if is_playlist_url(url):
        raise HTTPException(
            status_code=422,
            detail="Playlist URLs aren't supported — paste one song URL (R1).",
        )

    job = get_store().create_job(url)
    request.app.state.worker.submit(job.id, url)
    return {"job_id": job.id}


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
