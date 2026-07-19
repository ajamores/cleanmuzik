---
type: meta
title: "Hot — cleanmuzik"
updated: 2026-07-19
tags:
  - meta
  - hot-cache
status: evergreen
---
# Hot — cleanmuzik (personal YouTube → Jellyfin music tool)

> This repo's own working-memory board — session continuity, loaded at session start via `/hot`.
> A cache, not a journal: rewritten each save, never appended to. Durable knowledge lives in this
> repo's stores (`docs/r1/adr.md` · `docs/learnings.md` · `docs/r1/tickets.md` · git); business/vault
> learnings go to the garden via `/graft`.

## What this repo is

CleanMuzik — personal YouTube → Jellyfin music tool. Purpose, stack, constraints and read-order
are in `CLAUDE.md`; scope in `cleanmuzik-prd.md`. Not restated here.

## Current State (2026-07-19)

- **On `main`, clean and pushed** through `0a4816c`. Server suite **312 green**, client **20 green**.
- **Owner's dev servers are up**: `uvicorn --reload` on 8137, Vite proxying to it. Hazard
  (`CLAUDE.md`): editing `db.py` re-runs the lifespan against the **live** DB.
- Ledger: **T-016, T-028 done**; **T-017 built**, **T-024 built** — both owe only a **browser
  receipt**. **T-029 drafted** (code-review finding 2). Open = T-019, T-020, T-021→T-027, T-029.

## NEXT

1. **Browser verification** — the one thing blocking T-017 *and* T-024 from *done*. Needs the owner
   in a browser: park a song → panel renders → accept lands it / reject discards; a duplicate's
   three branches; and T-024's collaboration row (its outstanding **row 7**). Everything else on
   T-017 (review pass + fixes) is discharged.
2. **T-019** — the §7 acceptance pass; unblocked once T-017 is verified.
3. **T-029** — back-end: a releasable resume-failure sets job=`error` while the row is `pending`,
   orphaning the review. Fix rides T-017's new reconcile re-hydration. Verifiable over HTTP.

## Recent sessions (rolling — last 2–3)

### 2026-07-19 (c) — T-017 built, reviewed, landed
- Review panel shipped: weak-match (pick/reject, honest score bar) + duplicate (keep/replace/both).
  Added `rec` to the `track.review_required` SSE event and a narrow `GET /api/reviews/{id}` so the
  card re-hydrates a lost panel after a restart. Fresh-EventSource resume reuses T-016's reconcile.
- High-effort `/code-review` (owner-triggered): 5 code findings fixed, finding 2 → **T-029**. The
  dominant catch — a restart left a parked review showing a dead note, unresolvable — my own
  self-review had missed.
- Committed `0e41956` (feat) + `0a4816c` (docs), pushed.

### 2026-07-19 (b) — T-024 + T-028 (prerequisite T-017 didn't know it had)
- T-024 built (ADR-012, `ftintitle`); **T-028 done** — persisted candidate `score`, the field
  ADR-010 makes the picker's discriminator (was `null` on every queue row).
- Corrected `CLAUDE.md`: `localhost` sockets are **not** blocked; client test harness stood up.

## Where the rest of the context lives

- **Durable stores:** `docs/r1/adr.md` · `docs/learnings.md` · `docs/r1/tickets.md` · `docs/r1/spec.md`
  · `docs/r1/architecture.md` · `cleanmuzik-prd.md` · git. Read order in `CLAUDE.md`.
- **Business/vault context** — the garden, via `/garden`.
