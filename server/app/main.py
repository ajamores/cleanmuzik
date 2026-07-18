"""CleanMuzik backend — FastAPI application entry point (R1, T-001).

Replaces the old Express scaffold. Routes are added per ticket; R1 grows this
into the job/SSE/review surface described in spec §6. For now it stands up the
service and proves config loads.
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.db import get_store
from app.routes import health, jobs, reviews

logger = logging.getLogger("cleanmuzik")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Configure logging at startup, not import time, so merely importing
    # app.main (e.g. under TestClient) doesn't mutate the root logger.
    logging.basicConfig(level=logging.INFO)
    # Log which capabilities are wired without ever printing a secret — a
    # boot-time receipt that the `.env` was found and parsed (T-001 done-when).
    s = get_settings()
    logger.info(
        "config loaded: jellyfin_url=%s jellyfin_api_key=%s lastfm_apikey=%s acoustid_apikey=%s",
        s.jellyfin_url,
        "set" if s.jellyfin_api_key else "unset",
        "set" if s.lastfm_apikey else "unset",
        "set" if s.acoustid_apikey else "unset",
    )
    # Idempotent — creates the SQLite tables (and data dir) if absent so parked
    # reviews outlive a restart (spec §7, T-002). No-op on an existing DB.
    get_store().init_schema()
    logger.info("sqlite store ready at %s", s.db_path)
    # Stand up the beets engine and log a boot receipt that all six plugins loaded
    # and chroma can reach fpcalc (T-003 / ADR-007). A degraded engine warns but
    # doesn't stop the service — a track can still land tag-only.
    #
    # Imported here, not at module top, so `import app.main` (and route tests)
    # don't hard-require the heavy beets package. Run on a thread: the fpcalc
    # `-version` probe shells out and would otherwise block the event loop.
    from app.beets_engine import log_smoke_check

    await asyncio.to_thread(log_smoke_check, s)

    # Start the single job worker (ADR-001: one track at a time on a worker thread,
    # never the event loop). Imported here, not at module top, so the beets/yt-dlp
    # pipeline stays off `import app.main`'s path (T-001 lazy-engine). The route
    # layer reaches it via app.state.worker.
    from app.jobs import JobWorker

    worker = JobWorker(get_store(), s)
    worker.start()
    # Bind the running loop so the worker thread can hand SSE events to it via
    # call_soon_threadsafe (T-013). Done here — the lifespan runs on the loop — so
    # cross-thread delivery works from the very first event, before any subscriber.
    worker.bus.bind_loop(asyncio.get_running_loop())
    app.state.worker = worker
    try:
        yield
    finally:
        worker.stop()


app = FastAPI(title="CleanMuzik", version="0.1.0", lifespan=lifespan)
app.include_router(health.router, prefix="/api")
app.include_router(jobs.router, prefix="/api")
app.include_router(reviews.router, prefix="/api")
