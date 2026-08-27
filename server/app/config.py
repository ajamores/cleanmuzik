"""R1 configuration — loaded from the git-ignored repo-root `.env` (spec §6).

Every secret is optional at boot: a missing key degrades one capability (no
Jellyfin scan, no genre) but never stops the app or a track from landing. The
defaults here encode that "absent is not a failure" contract.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# config.py lives at server/app/config.py, so the repo root — where `.env`
# sits — is two directories up from the package. Resolving from __file__ keeps
# this correct no matter what cwd uvicorn is launched from.
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"

# The `server/` dir is one up from the package. The SQLite DB (T-002) defaults
# under it, keeping the git-ignored data file next to the code that owns it and
# independent of cwd — same __file__ anchoring as ENV_FILE above.
SERVER_DIR = Path(__file__).resolve().parents[1]

# The descriptive User-Agent MusicBrainz etiquette (and ADR-001) requires on every
# direct call to their API — sent by both the ISRC lookup (app/isrc.py) and the
# cover-art fetch (app/artwork.py). One home so the app identity + contact URL can
# never drift between the two modules (or leave one stuck on a stale value).
MUSICBRAINZ_USER_AGENT = (
    "CleanMuzik/0.1 (personal music library; +https://github.com/ajamores/cleanmuzik)"
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    # Jellyfin auto-scan after a track lands. Missing key → no scan, logged
    # warning, track still lands on disk (spec §6, ADR-008).
    jellyfin_url: str = "http://localhost:8096"
    jellyfin_api_key: str = ""

    # RETAINED BUT INERT since T-224 (ADR-033): the `lastgenre` plugin is gone, so this
    # key no longer feeds genre — genre now comes from the Shazam record. Kept only so an
    # existing `.env` with LASTFM_APIKEY still loads without error; safe to delete once the
    # spec §6 / .env.example references are retired in a docs pass.
    lastfm_apikey: str = ""

    # AcoustID via beets `chroma`. Optional — beets' built-in key works
    # (proven in the spike); set only to raise rate limits.
    acoustid_apikey: str = ""

    # Anthropic key for the R1.5 reconcile adjudicator (T-200, spec §6). Field name
    # mirrors `lastfm_apikey`/`acoustid_apikey`, so pydantic binds it to env var
    # ANTHROPIC_APIKEY — deliberately NOT the SDK default ANTHROPIC_API_KEY, which is
    # read explicitly here (reconcile.make_reconcile_fn). Missing → reconcile disabled,
    # pipeline degrades to the R1 fingerprint-only gate (T-205): an eyes-open fallback,
    # not a failure (spec §6 degrade row).
    anthropic_apikey: str = ""

    # On-disk SQLite store (T-002). Must live on disk, not in-memory, so parked
    # reviews survive a restart (spec §7). Overridable via `.env` (e.g. a test
    # DB); the parent dir is created at startup by Store.init_schema().
    # Staging (T-106) is deliberately NOT a separate setting: it is derived from this
    # path as `Store.staging_root`, so the review row and the audio it points at always
    # live in the same data dir. See that property for why.
    db_path: Path = SERVER_DIR / "data" / "cleanmuzik.db"

    # Hard wall-clock cap for the Shazam subprocess (T-202, spec §5). Loaded from
    # `.env` like every other setting — a bare `os.environ` read misses .env-only
    # values. Bounded `> 0`: a zero/negative cap would time out every call
    # instantly and silently disable the whole Shazam sense, so a bad value fails
    # fast at boot with a clear pydantic error rather than degrading in the dark.
    shazam_timeout_s: float = Field(default=8.0, gt=0)


@lru_cache
def get_settings() -> Settings:
    """Cached accessor — the `.env` is read once per process."""
    return Settings()
