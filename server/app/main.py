"""CleanMuzik backend — FastAPI application entry point (R1, T-001).

Replaces the old Express scaffold. Routes are added per ticket; R1 grows this
into the job/SSE/review surface described in spec §6. For now it stands up the
service and proves config loads.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.db import get_store
from app.routes import health

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
    yield


app = FastAPI(title="CleanMuzik", version="0.1.0", lifespan=lifespan)
app.include_router(health.router, prefix="/api")
