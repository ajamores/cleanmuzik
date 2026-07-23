---
type: meta
title: "Hot — cleanmuzik"
updated: 2026-07-23
tags:
  - meta
  - hot-cache
status: evergreen
---
# Hot — cleanmuzik (personal YouTube → Jellyfin music tool)

> This repo's own working-memory board — session continuity, loaded at session start via `/hot`.
> A cache, not a journal: rewritten each save, never appended to. Durable knowledge lives in this
> repo's stores (`docs/r1/adr.md` · `docs/learnings.md` · `docs/r1/tickets.md` · `docs/backlog/` ·
> `docs/roadmap.md` · git); business/vault learnings go to the garden via `/graft`.

## What this repo is

CleanMuzik — personal YouTube → Jellyfin music tool. Purpose, stack, constraints and read-order
are in `CLAUDE.md`; scope in `cleanmuzik-prd.md`. Not restated here.

## Current State (2026-07-23)

- **R1 is shipped.** All build tickets are on `main`; T-020 (the last) merged with a clean
  high-effort `/code-review` (no findings survived verification). `main` at `e2aec56`, pushed to
  `origin/main`, tree clean. Suites green on `main`: **server 380, client 35**.
- **Roadmap flipped:** R1 → `shipped`, R2 → `specing` (`docs/roadmap.md`).
- Merged branch `t020-review-remediation` still exists locally — safe to delete when convenient.

## ⟹ NEXT ACTIONS (in order)

1. **Start R2 — write `docs/r2/spec.md`.** Scope: playlists + migrate/clean the existing library.
   Pull relevant `docs/backlog/` items into the spec as it forms (`git mv` the ticket file into R2).
2. **Scoped architecture review of `client/src/components/TrackCard.tsx`** — one component runs the
   whole job state machine; suspected root of "every review finds another corner." Architecture, not
   visual/UX. Do before it grows further in R2.
3. Backlog to triage into R2 when specing: **T-033** (boot-recon orphan, HIGH), T-032, T-030/031.

## Optional / owner-only

- Browser eyeball still owed on the T-020 UI: watch the all-green step rail + library path + failure
  banner render on a **real scan failure**. Tests assert the logic; nobody has watched the DOM. Not
  a blocker (T-020 reviewed + merged). Drop this line if not worth doing.

## Verifying

- Owner's real servers: `:8137` (uvicorn `--reload`, real library — **do NOT POST jobs to it**) +
  `:5173`. Editing a startup module (`db.py`) re-runs the lifespan on the live DB. Tests:
  `./.venv/bin/pytest` from `server/`; `npm test` from `client/` (vitest workers flake on cold start
  under load — re-run alone if they time out before running).

## Where the rest of the context lives

- **Durable stores:** `docs/roadmap.md` · `docs/r1/adr.md` (ADR-015 newest) · `docs/learnings.md` ·
  `docs/r1/tickets.md` · `docs/backlog/` · `docs/r1/spec.md` · `docs/r1/architecture.md` ·
  `cleanmuzik-prd.md` · git.
- **Business/vault context** — the garden, via `/garden`.
