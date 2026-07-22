---
type: meta
title: "Hot — cleanmuzik"
updated: 2026-07-21
tags:
  - meta
  - hot-cache
status: evergreen
---
# Hot — cleanmuzik (personal YouTube → Jellyfin music tool)

> This repo's own working-memory board — session continuity, loaded at session start via `/hot`.
> A cache, not a journal: rewritten each save, never appended to. Durable knowledge lives in this
> repo's stores (`docs/r1/adr.md` · `docs/learnings.md` · `docs/r1/tickets.md` · `docs/backlog/` ·
> git); business/vault learnings go to the garden via `/graft`.

## What this repo is

CleanMuzik — personal YouTube → Jellyfin music tool. Purpose, stack, constraints and read-order
are in `CLAUDE.md`; scope in `cleanmuzik-prd.md`. Not restated here.

## Current State (2026-07-21)

- **On `main`, clean tree.** T-022 and T-027 both landed + suite green on `main` (375 tests).
- **R1 has ONE ticket left: T-020** (front-end). Everything else in the R1 set is done.
- **T-027 done** (`704da64`): reproduce showed the playlist-shape hole was a **channel/@handle** URL
  (not a `list=` URL — `noplaylist=True` collapses those). Fix C+A: `create_job` rejects
  `not names_one_song(url)` (now YouTube-host-only) with 422 so a channel never starts a job +
  downloads the whole channel; belt-and-braces guard in `download_song` fails honestly on the
  download stage. `/code-review` (high): 3 findings, all resolved.

## Next session — T-020 (the last R1 ticket)

- **T-020** (front-end): amend spec §6 to add `path`+`tags` to the `GET /api/jobs/{id}` snapshot,
  build the stream-reattach story, verify stream-offline (Playwright MCP can emulate offline).
  Then R1 is complete → T-019's close (its only open gate was the tag-quality defects, now landed).

## Notes for later (not blocking)

- **Reload loses all cards.** `App.tsx` holds the job list in component state and doesn't restore
  it across a browser reload, so any "survives reload" work is latent until a *job-restore-on-reload*
  capability exists (server fixes + unit tests already cover the mechanisms).

## Verifying

- Owner's real servers: `:8137` (uvicorn `--reload`, real library — **do NOT POST jobs to it**) +
  `:5173`. `--reload` re-runs the lifespan on any edit to a startup-state module (`db.py`); pure
  request-path edits (download.py, routes) are safe.
- Browser `/verify` works here (Playwright MCP over an isolated backend). Rebuild the throwaway
  harness from the T-026/T-029 notes if needed. Hazard: WSL `/mnt/c` Vite serves a **stale bundle** —
  start with `--force` (`learnings.md` 2026-07-21).

## Recent sessions (rolling — last 2–3)

### 2026-07-21 — T-027 done (channel-URL guard + front-door reject)
- Reproduce-first found the real hole (channel/@handle downloads whole channel). C+A fix,
  `/code-review` high (3 findings resolved incl. YouTube-host tightening), suite 375, landed `704da64`.

### 2026-07-21 — T-022 closed won't-change (measurement)
- Measured audio inventory JSless vs node across 3 tracks: identical. No code change; ticket records
  the finding + a one-line re-enable path.

## Where the rest of the context lives

- **Durable stores:** `docs/r1/adr.md` · `docs/learnings.md` · `docs/r1/tickets.md` ·
  `docs/backlog/` · `docs/r1/spec.md` · `docs/r1/architecture.md` · `cleanmuzik-prd.md` · git.
  Read order in `CLAUDE.md`.
- **Business/vault context** — the garden, via `/garden`.
