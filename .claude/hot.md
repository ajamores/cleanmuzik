---
type: meta
title: "Hot — cleanmuzik"
updated: 2026-08-30
tags:
  - meta
  - hot-cache
status: evergreen
---
# Hot — cleanmuzik (personal YouTube → Jellyfin music tool)

> This repo's own working-memory board — session continuity, loaded at session start via `/hot`.
> A cache, not a journal: rewritten each save, never appended. Durable knowledge lives in this repo's
> stores (`docs/roadmap.md` · `docs/r1/adr.md` · `docs/backlog/` · `docs/learnings.md` · git);
> business learnings go to the garden via `/graft`.

## What this repo is

CleanMuzik — personal YouTube → Jellyfin music tool. Purpose, stack, constraints, read-order in
`CLAUDE.md`; scope in `cleanmuzik-prd.md`. Not restated here. R1/R1.1/R1.5/R2 shipped; **no release is
`in-build`** (R2.5 migrate/clean is next, still `backlog`).

## Current State (2026-08-30)

- **On branch `t226-remove-beets` (pushed to origin, NOT integrated to `main`).** Working on **T-226**
  (remove beets entirely — the spine rewrite; `docs/backlog/T-226.md` now carries the full status). It's a
  4-step sub-wave; owner scheduled the whole thing but **checkpointed A–C before step D**.
- **Steps A–C DONE, reviewed (findings fixed), 834 tests green:**
  - **A** — `app/pathing.py`, plain-Python mover (byte-verified vs beets 2.12).
  - **B** — recording-id UFID frame + `app/library_scan.py` filesystem dedup replacing the beets DB;
    `_replace_existing` now plain-Python file ops. Autouse `isolated_library` conftest fixture keeps the
    scan off the real `/mnt/c` library.
  - **C** — `app/mb_client.py` direct-HTTP MB + one shared 1-req/s limiter; `fetch_original_date` off beets.
  - **A–C still leave `beets` a dependency** — they're scaffolding. Step D is the actual removal.
- **Working tree:** only pre-existing noise (`README.md` modified, `.vscode/`, the untracked `t219_*`
  corpus). **Never `git add -A` here** (`[[no-blanket-git-add]]`) — stage explicit paths.

## Next actions (owner-chosen order)

1. **/verify A–C** end-to-end without polluting the real library. Isolated-server shim is written at
   `…/scratchpad/run_isolated.py` (port 8138; patches `LIBRARY_DIRECTORY` in both modules + `DB_PATH`).
   Load-bearing proof: land a track → its file carries the UFID `mb_trackid` → the filesystem scan detects
   a re-acquire as a duplicate; confirm `/mnt/c/.../CleanMuzik` untouched. (fpcalc on PATH; keys in `.env`.)
2. **Integrate A–C to `main`** as a reviewed increment (suite green there); T-226 stays open on D.
3. **Then step D** — retire `ImportSession`/`session.run()` for a plain driver, own candidate types,
   organize via `pathing`, drop `beets`/`chroma`/`mb_thin`, pin `mediafile`, retire `lastfm_apikey`.
   **Acceptance is owner-gated:** the ADR-030 measured compare over the live 16-track corpus
   (`t219_compare.py`, generalised) — outcomes unchanged, Frank Ocean/Coldplay still park, speed ≥.

## Where the rest of the context lives

Read-order + rules: `CLAUDE.md`. Scope: `cleanmuzik-prd.md`. Releases: `docs/roadmap.md`. Decisions:
`docs/r1/adr.md`. Lessons: `docs/learnings.md`. This ticket: `docs/backlog/T-226.md`. Garden (business):
`/graft`.
