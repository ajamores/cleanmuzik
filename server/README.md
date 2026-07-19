# CleanMuzik backend (FastAPI)

The Python backend. Replaces the old Express scaffold (dropped in T-001). Grows
per R1 ticket into the job / SSE / review surface described in `docs/r1/spec.md` §6.

## Run

From this `server/` directory:

```bash
uv venv .venv                                  # one-time: create the venv (uv, not python -m venv)
uv pip install --python .venv/bin/python -r requirements.txt
./.venv/bin/uvicorn app.main:app --reload --port 8137
```

Then `GET http://127.0.0.1:8137/api/health` → `{"status": "ok"}`.

On boot the app logs which capabilities are wired (Jellyfin URL/key, Last.fm,
AcoustID) **without printing any secret** — a receipt that the git-ignored
repo-root `.env` was found and parsed.

## Config

Secrets load from the git-ignored `.env` at the **repo root** (not here) — see
`.env.example` and spec §6. Every key is optional at boot: a missing one
degrades a single capability (no Jellyfin scan, no genre) but never stops the
service. `app/config.py` owns the loading.

**Editing `.env` needs a manual uvicorn restart — `--reload` will not pick it up.**
Two reasons compound: `--reload` watches `server/` only, and the `.env` lives a
directory above it; and `get_settings` is `lru_cache`d, so even a reload that did
fire would serve the values read at first call. Restart the process after any
`.env` change, or you will debug a stale value.

## Layout

```
app/
  main.py            FastAPI app + startup config receipt
  config.py          pydantic-settings, reads repo-root .env
  beets_engine.py    T-003: beets config + explicit plugin loading (ADR-007)
  download.py        T-004: yt-dlp download stage + playlist classifier
  routes/
    health.py        GET /api/health
tests/
  test_download.py   playlist-classifier unit tests (no network)
```

## beets engine (T-003)

`app/beets_engine.py` builds the beets config programmatically and — crucially —
calls `beets.plugins.load_plugins()` explicitly at startup (ADR-007; the library
API never auto-loads plugins, only the `beet` CLI does). On boot the lifespan runs
`log_smoke_check()`, which logs a receipt that all six plugins
(`musicbrainz chroma lastgenre fetchart embedart lyrics`) loaded and that `chroma`
can reach `fpcalc`.

**`fpcalc` (Chromaprint)** is a system binary `chroma` shells out to for
fingerprinting — it is *not* a pip dependency. Provide it one of two ways:

```bash
# Debian/Ubuntu (needs sudo):
sudo apt install libchromaprint-tools

# No sudo — static binary, point the FPCALC env var at it:
curl -L -o fpcalc.tar.gz \
  https://github.com/acoustid/chromaprint/releases/download/v1.5.1/chromaprint-fpcalc-1.5.1-linux-x86_64.tar.gz
tar xzf fpcalc.tar.gz
export FPCALC="$PWD/chromaprint-fpcalc-1.5.1-linux-x86_64/fpcalc"
```

Without `fpcalc` the service still boots but logs `beets engine DEGRADED` and every
song falls through to the review queue (no acoustic identity). No AcoustID or
Last.fm API key is required — beets ships working built-in keys; owner keys only
raise rate limits / override the genre source.

## Tests

`requirements-dev.txt` adds `pytest` and the test client used to verify routes
without a socket (`fastapi.testclient.TestClient`). Run from this directory:

```bash
uv pip install --python .venv/bin/python -r requirements-dev.txt   # once
./.venv/bin/pytest -v
```

The playlist classifier (`app.download.is_playlist_url`) is a pure function and
its tests need no network; the real `download_song` is verified by hand against a
live YouTube URL.
