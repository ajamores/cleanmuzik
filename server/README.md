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

## Layout

```
app/
  main.py            FastAPI app + startup config receipt
  config.py          pydantic-settings, reads repo-root .env
  download.py        T-004: yt-dlp download stage + playlist classifier
  routes/
    health.py        GET /api/health
tests/
  test_download.py   playlist-classifier unit tests (no network)
```

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
