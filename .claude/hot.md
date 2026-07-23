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
> git); business/vault learnings go to the garden via `/graft`.

## What this repo is

CleanMuzik — personal YouTube → Jellyfin music tool. Purpose, stack, constraints and read-order
are in `CLAUDE.md`; scope in `cleanmuzik-prd.md`. Not restated here.

## Current State (2026-07-23)

- **On branch `t020-review-remediation` (off `main`).** Suites green: **server 380, client 35**,
  lint + build clean. **Not yet committed / merged.**
- **High-effort `/code-review` ran** over the T-020 descope + doc corrections. 5 findings:
  - **#1, #3, #4 fixed** (all `TrackCard.tsx`): scan-error rail no longer paints Land failed while
    showing the library path (`ERROR_STEP.scan → RAIL.length`); shared `LandingDetail` fragment kills
    the done/error copy-paste (ADR-010) and the empty-`<ul>` chip case. Regression asserts added.
    Lesson filed → `docs/learnings.md` (2026-07-23).
  - **#2 skipped** — it *is* ADR-015 (restart loses best-effort path; owner accepted doc-only).
  - **#5 skipped** — `_finish` `status` default; plausible cleanup, owner's call, not applied.

## ⟹ NEXT ACTIONS (in order)

1. **Fresh `/code-review` on the full branch** next session (covers the 3 fixes too) → then merge to
   `main` green. That closes every R1 ticket. Owner then: flip `docs/roadmap.md` R1 → `shipped`,
   R2 → `specing`.
2. **Scoped architecture review of `TrackCard.tsx`** next session — is one component running the whole
   job state machine doing too much; should the state machine leave the view. (Root of "every review
   finds another corner": too many interacting states + branches in one render. Visual/UX review = not
   needed; *architecture* review = yes.)
3. Backlog when scheduled: **T-033** (boot-recon orphan, HIGH), T-032, T-030/031.
4. Browser-only receipt still owed: watch the all-green rail + path + banner render on a real scan
   failure (DOM render needs a browser — owner's to do).

## Uncommitted → two logical commits (about to land)

1. **T-020 descope (ADR-015) + review fixes** — `server/app/{db,jobs,routes/jobs}.py`,
   `client/src/{api.ts,components/TrackCard*.tsx}`, both server test files,
   `docs/r1/{adr,spec,tickets}.md` + `docs/learnings.md`.
2. **Backlog filing (unrelated)** — `docs/backlog/{T-032.md,T-033.md,README.md}` + this board.

## Verifying

- Owner's real servers: `:8137` (uvicorn `--reload`, real library — **do NOT POST jobs to it**) +
  `:5173`. Editing a startup module (`db.py`) re-runs the lifespan on the live DB. Tests:
  `./.venv/bin/pytest` from `server/`; `npm test` from `client/` (vitest workers flake on cold start
  under load — re-run alone if they time out before running).

## Where the rest of the context lives

- **Durable stores:** `docs/r1/adr.md` (ADR-015 newest) · `docs/learnings.md` · `docs/r1/tickets.md` ·
  `docs/backlog/` · `docs/r1/spec.md` · `docs/r1/architecture.md` · `cleanmuzik-prd.md` · git.
- **Business/vault context** — the garden, via `/garden`.
