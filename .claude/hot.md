---
type: meta
title: "Hot — cleanmuzik"
updated: 2026-07-24
tags:
  - meta
  - hot-cache
status: evergreen
---
# Hot — cleanmuzik (personal YouTube → Jellyfin music tool)

> This repo's own working-memory board — session continuity, loaded at session start via `/hot`.
> A cache, not a journal: rewritten each save, never appended to. Durable knowledge lives in this
> repo's stores (`docs/r1/adr.md` · `docs/learnings.md` · `docs/r1.1/` · `docs/backlog/` ·
> `docs/roadmap.md` · git); business/vault learnings go to the garden via `/graft`.

## What this repo is

CleanMuzik — personal YouTube → Jellyfin music tool. Purpose, stack, constraints and read-order
are in `CLAUDE.md`; scope in `cleanmuzik-prd.md`. Not restated here.

## Current State (2026-07-24)

- **On `main`, tree clean, pushed.** R1.1 is `in-build`. The filing (spec + tickets + ADR-017/018 +
  roadmap row + backlog moves) is committed (`afe34f3`).
- **T-104 and T-101 are DONE — merged to `main`** (`90d5854`, `700df62`), both suites green there
  (backend 383, client 42 + lint/tsc).
  - **T-104** — boot reconciliation: one transactional `Store.reconcile_orphans_on_boot()` (reviews
    first, then jobs that own a pending review settle to `review`, then remaining orphans → `error`).
    Superseded backlog T-033.
  - **T-101** — durable Needs-review inbox in `App.tsx`, fetched on cold load; live freshness via a
    per-card `onReviewParked`/`onReviewResolved` nudge (no global EventSource). A cold-loaded review
    shows but its Review action is **disabled** — resolving it in place is T-102.

## ⟹ NEXT ACTIONS (in order)

1. **T-101 browser `/verify`** — owner-only, still pending: cold-load hydration + `EventSource`
   freshness through the Vite proxy. Can't run headless. The one open item on the two landed tickets.
2. **T-102** — lift the review lifecycle out of `TrackCard` into the inbox row (re-home `ReviewPanel`
   + its re-hydration/keep-which/re-park paths); this is what makes a cold-loaded row **resolvable**.
   Depends on T-101 (landed). The seam props are already additive for it.
3. **T-103** — no-candidate park exits (reject required; keep-untagged only if cheap — design in-ticket).
   Depends on T-101 + T-102.
4. **T-105** — Signal Path reskin (ADR-018), last, skins the finished structure. Depends on T-101/T-102.

## Deferred (right time, not now)

- **Candidate-art thumbnails in the picker** — needs a per-candidate art lookup (ADR-010); own ticket.
- **T-032** (job-card reload restore) — deferred by design (ADR-017: cards are ephemeral); backlog.
- **Security-review pass** — timed to the Tailscale/phase-1 move (ADR-004), not before.
- **R2** (playlists + migrate) — blocked on R1.1; migrate is a firehose into this same queue.

## Verifying

- Owner's real servers: `:8137` (uvicorn `--reload`, real library — **do NOT POST jobs to it**) +
  `:5173`. Editing a startup module (`db.py`) re-runs the lifespan on the live DB. Tests:
  `./.venv/bin/pytest` from `server/`; `npm test` from `client/` (vitest cold start ~60s — don't call
  it a hang; re-run alone if it times out). R1.1 inbox is browser-behaviour → needs `/verify`.

## Where the rest of the context lives

- **Durable stores:** `docs/roadmap.md` · `docs/r1.1/` (active) · `docs/r1/adr.md` (ADR-018 newest) ·
  `docs/learnings.md` · `docs/r1/tickets.md` · `docs/r1/design/*.html` (signed-off gates) ·
  `docs/backlog/` · `cleanmuzik-prd.md` · git (tag `r1-single-song`).
- **Business/vault context** — the garden, via `/garden`.
