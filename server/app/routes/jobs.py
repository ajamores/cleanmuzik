"""Job routes — paste a URL, get a job; poll its snapshot (T-012, spec §6).

Two routes:

- `POST /api/jobs {url}` → refuse a playlist (422), create a `jobs` row, hand the
  job to the worker, and return `{ job_id }`. The response returns *immediately*;
  the pipeline runs on the worker thread (spec §4).
- `GET /api/jobs/{job_id}` → the reconnect / SSE-fallback snapshot: the durable row
  overlaid with the worker's live stage / error / review id.

Kept deliberately import-light. The heavy pipeline (beets, yt-dlp, ffmpeg) lives in
`app.jobs`, reached through `app.state.worker` set up in the lifespan — so importing
this module (and therefore `app.main`) does **not** pull beets at import time,
preserving T-001's lazy-engine property. The playlist classifier is imported inside
the handler for the same reason (its module imports yt-dlp).
"""

from fastapi import APIRouter, HTTPException, Request

from app.db import get_store

router = APIRouter()


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
    from app.download import is_playlist_url

    if is_playlist_url(url):
        raise HTTPException(
            status_code=422,
            detail="Playlist URLs aren't supported — paste one song URL (R1).",
        )

    job = get_store().create_job(url)
    request.app.state.worker.submit(job.id, url)
    return {"job_id": job.id}


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
