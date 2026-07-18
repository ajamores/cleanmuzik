---
type: meta
title: "Hot — cleanmuzik"
updated: 2026-07-17
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

## Current State (2026-07-17)

- **Phase: R1 build, T-016 ∥ T-014 fan-out — both built, NEITHER integrated onto `main` yet.**
- **`main` at `66c8d7b`, green (221 tests), tree clean.** Nothing pushed this session (4 local
  commits ahead: `1ebc490`, `6c7a69a`, `66c8d7b`, and whatever origin lacks — push is the owner's call).
- **T-014 (server review API) — BUILT, not done** (done = integrated; vocab in `tickets.md`).
  `/verify`'d in isolation (263 tests, real beets import vs a temp library). On its worktree branch
  `worktree-agent-a154d865855ff4510` @ `8410f4b`.
- **T-016 (client track-card SSE) — BUILT, not done.** Reviewed (4 fixes applied), lint+build green,
  **never driven live** (rides with T-019). On `worktree-agent-aaffef646dc8b8e5c` @ `3885939`.
- Ledger `docs/r1/tickets.md`: open = **T-014, T-016, T-017, T-019** (T-014/16 land at integration).

## NEXT — integration, then T-017

1. **Integrate the two worktree branches onto `main`, T-014 FIRST** (T-017 depends on it), then T-016.
   Per `CLAUDE.md` fan-out: merge `--no-commit`, **hand-reconcile `server/app/events.py`** (main has
   4-key `candidate_row`; T-014 adds `EventBus.reopen` — both must survive) **and `docs/learnings.md`**
   (all three heads edited it), run the full suite, acceptance-check each ticket, `/code-review` the
   diff in-tree before committing.
2. **Apply T-014's one open finding (owner: accept):** `run_resolve` computes `before`/`before_ids` on
   every landing branch but only `replace` uses them — guard behind `if choice == CHOICE_REPLACE`.
3. **Then T-017** (review panel) unblocks; **T-019** owns T-016's live browser round-trip.

## Recent sessions (rolling — last 2–3)

### 2026-07-17 — T-014 built + verified; ADR-010; replace-refuse ruling; 3 restarts survived
- T-014 built + verified in isolation; its `/verify` caught two data-loss bugs (replace deleting both copies;
  dup double-count), both fixed + regression-tested. Owner ruled `replace` **refuses** the two-copy
  case (→ ADR-009 addendum) with a fast-review-UI condition (→ T-017, spec §5).
- **ADR-010**: a weak-match candidate is title+artist+score — album/year/art unreachable from a
  recording lookup. Added the **acceptance check** as DoD step 2 (`CLAUDE.md`). `66c8d7b` fixed two
  stale candidate-shape tests `6c7a69a` shipped red.
- Machine restarted 3× mid-session; all work was on disk / now committed, nothing lost.

### 2026-07-16 (session 14) — docs-only sweep; board de-journaled; `/hot` skill rewritten
- Live doc bugs fixed (`d7b620f`, `f8aeb06`); 9 ticket statuses corrected so `tickets.md` is the
  ledger. Detail: `learnings.md`.

## Where the rest of the context lives

- **Durable stores:** `docs/r1/adr.md` · `docs/learnings.md` · `docs/r1/tickets.md` · `docs/r1/spec.md`
  · `docs/r1/architecture.md` · `cleanmuzik-prd.md` · git. Read order in `CLAUDE.md`.
- **Business/vault context** — the garden, via `/garden`.
