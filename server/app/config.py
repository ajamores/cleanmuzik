"""R1 configuration — loaded from the git-ignored repo-root `.env` (spec §6).

Every secret is optional at boot: a missing key degrades one capability (no
Jellyfin scan, no genre) but never stops the app or a track from landing. The
defaults here encode that "absent is not a failure" contract.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# config.py lives at server/app/config.py, so the repo root — where `.env`
# sits — is two directories up from the package. Resolving from __file__ keeps
# this correct no matter what cwd uvicorn is launched from.
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    # Jellyfin auto-scan after a track lands. Missing key → no scan, logged
    # warning, track still lands on disk (spec §6, ADR-008).
    jellyfin_url: str = "http://localhost:8096"
    jellyfin_api_key: str = ""

    # Last.fm genre via beets `lastgenre`. Missing → track lands without a
    # genre tag, which is not a failure (spec §6). Owner obtains via T-018.
    lastfm_apikey: str = ""

    # AcoustID via beets `chroma`. Optional — beets' built-in key works
    # (proven in the spike); set only to raise rate limits.
    acoustid_apikey: str = ""


@lru_cache
def get_settings() -> Settings:
    """Cached accessor — the `.env` is read once per process."""
    return Settings()
