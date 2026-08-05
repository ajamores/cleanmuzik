---
name: verify
description: How to /verify a cleanmuzik pipeline change end-to-end without polluting the real Jellyfin library.
---

# Verifying cleanmuzik pipeline changes

The real dev server (`uvicorn :8137`) points at the **real** library
(`LIBRARY_DIRECTORY = /mnt/c/Users/aj_am/Music/CleanMuzik`, a hardcoded constant in
`app/beets_engine.py`) and the real data dir `~/cleanmuzik-data`. Never drive an
end-to-end acquire/resolve against it — it writes tagged MP3s into the real library.

## Isolate, then drive the real routes

Isolation has two knobs (both required):

1. **`DB_PATH` env** → a temp data dir. `Store.staging_root` is `db_path.parent/staging`
   and the beets item DB is `db_path.parent/beets_library.db`, so this one env var
   isolates staging **and** the beets catalogue.
2. **`LIBRARY_DIRECTORY`** must be patched in **both** modules — it is copied by value:
   - `app.beets_engine.LIBRARY_DIRECTORY` (read by `configure_beets` → `config["directory"]`)
   - `app.import_seam.LIBRARY_DIRECTORY` (read by `get_library` → `library.Library(db, dir)`)

   It is **not** env-overridable, so a plain second `uvicorn` still lands in the real
   library. Use a launcher shim that sets `DB_PATH`/`JELLYFIN_API_KEY=""` and patches
   both globals before `uvicorn.run`. A working shim lives in the scratchpad as
   `run_isolated.py` (T-106 verify, 2026-08-05) — copy its shape.

Launch it on a spare port (8138) with `PYTHONPATH=server`:

```bash
cd server
export T106_ROOT=/some/temp/dir PYTHONPATH=$PWD
mkdir -p "$T106_ROOT/data" "$T106_ROOT/library"
nohup ./.venv/bin/python /path/to/run_isolated.py > inst.log 2>&1 &
```

Boot log must show both `LIBRARY_DIRECTORY` lines pointing at the temp dir and
`jellyfin_api_key=unset` before you trust the run.

## The routes (all over HTTP, real ASGI stack)

- `POST /api/jobs {url}` → `{job_id}`; poll `GET /api/jobs/{id}` until `status:"review"`
  (parked), `"done"` (auto-landed), or `"error"`.
- `GET /api/reviews` → the parked queue (row keys: `review_id`, `rec`, `candidates[].candidate_id`,
  `staging_missing`, `guess`).
- `POST /api/reviews/{id}/search {artist,title}` → re-query MusicBrainz (T-103 exit).
- `POST /api/reviews/{id}/resolve {choice}` → `choice` is a recording MBID (candidate or
  off-list re-searched), `"reject"`, or `"keep_untagged"` (+`artist`/`title`). Then poll the
  job to `done`.

## Restart = kill the process and relaunch

A genuine restart proves durable staging + the boot sweep. **Do not `pkill -f run_isolated.py`**
— the pattern self-matches the wrapping shell (exit 144). Kill by PID. On relaunch, the boot
log emits `swept N orphaned staging dir(s) on startup`; a `cleanmuzik-*` dir with no pending
review is swept, a parked review's dir and any non-prefixed dir survive.

## Reliable fixtures

- **Parks reliably** (weak/no match, AcoustID+Shazam both miss): Nines "Franklin"
  `https://www.youtube.com/watch?v=D5QjfJao9FQ`. Correct recording (off original candidate
  list, found via re-search "Nines"/"Outro"): `f5d1bcfb-f66e-400a-948a-e7f9127160de`.

## Confirm the landed file

`mediafile.MediaFile(path)` → assert `bitrate == 320000` (ADR-002), `mb_trackid` matches the
resolve choice, `art` bytes > 0. Then confirm **nothing** landed in the real library:
`find /mnt/c/Users/aj_am/Music/CleanMuzik -mmin -15` must be empty.
