---
type: meta
title: "Hot — cleanmuzik"
updated: 2026-07-26
tags:
  - meta
  - hot-cache
status: evergreen
---
# Hot — cleanmuzik (personal YouTube → Jellyfin music tool)

> This repo's own working-memory board — session continuity, loaded at session start via `/hot`.
> A cache, not a journal: rewritten each save, never appended. Durable knowledge lives in this repo's
> stores (`docs/r1/adr.md` · `docs/learnings.md` · `docs/r1.1/` · `docs/backlog/` · git); business/vault
> learnings go to the garden via `/graft`.

## What this repo is

CleanMuzik — personal YouTube → Jellyfin music tool. Purpose, stack, constraints and read-order are in
`CLAUDE.md`; scope in `cleanmuzik-prd.md`. Not restated here.

## Current State (2026-07-26)

- **`main` is clean** at `d4d6842` — the docs pile (ADR-019, T-034/035, the R1.1 design screens) is
  committed.
- **T-106 is committed on its own branch, not on `main`:** `worktree-t106-durable-staging` at
  **`50e1d66`**, one commit on top of `d4d6842`. 390 server tests green **there**. The worktree at
  `.claude/worktrees/t106-durable-staging` is disposable now — the branch holds the work, so pick it
  up from any checkout with `git checkout worktree-t106-durable-staging` (or review it from `main`
  with `git diff main..worktree-t106-durable-staging`).

## ⟹ LIVE THREAD — T-106 is BUILT, not DONE

Durable parked-audio staging (`docs/r1.1/tickets.md` T-106). Three gates left, in order:

1. **Owner runs `/code-review`, then `/verify`** on the worktree diff — both are user-triggered; an
   agent cannot invoke them. (Self-review already caught one regression: an unwritable data dir made
   `run_pipeline` raise, which its contract forbids. Fixed + tested.)
2. **Item 4 — the 9 dead review rows** in the live DB. Untouched; needs the real DB with the server
   stopped, not the worktree. Deletion must be **selective** (see the ticket).
3. **Merge to `main`** and confirm green there. Until then it is *built*, not *done*.

**Time-sensitive:** the Frank Ocean review is the only one whose audio still exists, and it dies on the
next reboot — resolve it, or let T-106 land and re-park something to prove the fix on.

## Also open (not the live thread)

- **Shazam build ticket** — ADR-019 is ratified; the tier ticket itself is still unwritten
  (`docs/backlog/T-035.md`, item 4).
- **T-103 escape-hatch design** — awaiting owner sign-off (ADR-016 gate). Now also **blocks showing
  T-106 through the UI**: every parked review has no candidates, so nothing in the queue is resolvable
  through the route today.
- **T-102** (lift the review lifecycle out of `TrackCard`) — renders T-106's new `staging_missing`
  flag. **T-105** reskin, **R2** migrate — later.

## Verifying

- Owner's real servers: `:8137` (uvicorn `--reload`, real library — **do NOT POST jobs to it**) + `:5173`
  (Vite — restart after any merge/checkout touching `client/`). Isolate `DB_PATH` to a temp dir, and
  monkeypatch `beets_engine.LIBRARY_DIRECTORY` (a hardcoded constant, not a setting) or a resolve lands
  in the real library. Sandbox: `yt-dlp --js-runtimes node`; `uv venv`, not `python3 -m venv`.

## Where the rest of the context lives

`docs/roadmap.md` · `docs/r1.1/` (active) · `docs/r1/adr.md` (**ADR-019** newest) · `docs/learnings.md` ·
`docs/backlog/` · `docs/r1/design/*.html` · git (tag `r1-single-song`). Business/vault → `/garden`.
