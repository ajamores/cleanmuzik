"""Review routes — list the queue, resolve a row (T-014, spec §6).

- `GET /api/reviews` → every pending review, candidates re-hydrated from the stored
  MusicBrainz IDs (ADR-006 stores IDs, never candidate objects).
- `POST /api/reviews/{review_id}/resolve` → validate the body against the row's `rec`,
  claim the row, and hand the resume to the worker. Returns `{ok: true}` immediately;
  the tail streams over the job's SSE channel, exactly like the acquire path.

Import-light, like `routes/jobs.py`: `app.reviews`' own module scope carries no beets,
and the heavy work is reached through `app.state.worker` (set up in the lifespan). So
importing this module — and therefore `app.main` — doesn't pull the engine (T-001).
"""

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request

from app.db import get_store
from app.reviews import ResolveValidationError, hydrate_reviews, validate_resolve_body

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/reviews")
async def list_reviews(request: Request) -> list[dict]:
    """The parked queue (spec §6). Blocks on MusicBrainz, so it runs off the loop.

    `hydrate_reviews` is network-bound — a lookup per candidate — and would stall
    every other request if it ran on the event loop. It goes to a thread rather than
    to the job worker: it is a read, and queueing it behind a running import (the
    worker is sequential, ADR-001) would leave the queue page hanging for the length
    of a download. ADR-001 governs the *pipeline*, which this isn't.
    """
    return await asyncio.to_thread(hydrate_reviews, get_store())


@router.post("/reviews/{review_id}/resolve")
def resolve_review(review_id: str, payload: dict, request: Request) -> dict[str, bool]:
    """Apply the owner's decision and resume the import (spec §6).

    Validates *before* it claims, so a bad body leaves the row exactly as it was and
    the owner can just re-send. The claim is then atomic (`claim_review`): a
    double-clicked button must not enqueue two resolves and land the song twice.

    Returns as soon as the work is handed over — the resume runs on the worker thread
    (ADR-001: it re-runs a beets import). By the time this returns, the job's SSE
    channel is already re-opened and its status is back to `running`, so the client can
    safely open a fresh EventSource on the next line (see `JobWorker.submit_resolve`).
    """
    store = get_store()
    review = store.get_review(review_id)
    if review is None:
        raise HTTPException(status_code=404, detail=f"No review {review_id}.")
    if review.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Review {review_id} is already {review.status}.",
        )

    try:
        resolve_request = validate_resolve_body(review, payload)
    except ResolveValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Re-read under the compare-and-set: the row above was only a candidate for
    # validation, and could have been claimed since. The loser of a double-click
    # gets this 409 rather than a second landing.
    claimed = store.claim_review(review_id)
    if claimed is None:
        raise HTTPException(
            status_code=409, detail=f"Review {review_id} is already being resolved."
        )

    try:
        request.app.state.worker.submit_resolve(review.job_id, review_id, resolve_request)
    except Exception as exc:  # noqa: BLE001 — the claim must not outlive a failed hand-off
        # `claim_review` flipped the row to `resolving`. If the hand-off to the worker
        # raises, nothing downstream will ever clear that (run_resolve never got the
        # work), and the review would be stranded: invisible to `GET /api/reviews` and
        # un-retryable (a second POST 409s on the claim). Release it back to `pending`
        # so the owner can simply try again.
        store.release_review(review_id)
        logger.error("resolve hand-off for review %s failed: %s", review_id, exc)
        raise HTTPException(
            status_code=500,
            detail="Could not start the resolve — it was returned to the queue; please try again.",
        ) from exc
    return {"ok": True}
