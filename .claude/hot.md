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

- **On `main`, clean and pushed** through `6c7c4ee`. Only `.claude/worktrees/` is untracked.
  Suite **295 green** at this head.
- `.env` is git-ignored and **machine-local**: `JELLYFIN_URL` → WSL gateway IP.
- Ledger: **T-016 DONE**; open = T-017, T-019, T-020, T-021→T-027.
- **Re-review debt is discharged.** `757bda5..b3385ef` was reviewed; two defects found and fixed
  in `6c7c4ee` (URL normalisation discarded before download; a stale `noplaylist` comment).
  T-026 and T-027 remain unfixed on purpose; each ticket says why.
- **Ticket triage is the next thing the owner wants** (deferred to next session by his call).
  7 new tickets in one session is too many. **T-021 + T-024 are the only two touching whether the
  acquire flow is trustworthy.** T-022 and T-023 are checks/won't-fix dressed as build tickets;
  T-025 may be R2. Reasoning in `b3385ef`.

## NEXT

1. **Ticket triage + decide T-026** — owner calls, ~15 min, block nothing. **Start here** — he
   asked to open the next session with this.
2. **Finish the run list** (`docs/r1/tickets.md`, "First owner-driven browser session") — rows
   **2, 3, 4, 6** unrun. Needs the owner in a browser; rows 3–4 are T-020's only evidence. Row 6
   now tests the changed classifier **and** the scheme-less URL path. **Paste one link without
   `https://`** — that path was verified by extractor-regex inference, never actually downloaded
   (sandbox blocks sockets).
3. Then **T-017** (review panel UI) — reuses T-016's EventSource pattern, now proven live.

**Standing setup note:** two terminals — the server per `server/README.md`, and
`cd client && npm run dev`. (The `.env`-needs-a-restart caveat now lives in that README.)

## Recent sessions (rolling — last 2–3)

### 2026-07-19 — re-review of the unreviewed fixes; 2 defects, both fixed
- The fixes for the 9 review findings had never been reviewed. Classifier logic held up under 11
  edge shapes; all docs claims checked out. The two defects and their lessons are in `learnings.md`
  and `6c7c4ee`. Triage deferred to next session at the owner's request.

### 2026-07-18/19 — first browser session ever; rows 1 + 5 pass, then a review that bit back
- **Nothing could be tested until four defects were fixed**, none visible to a green suite. The
  review then found 9 more in those same fixes. All durable output is filed; see the stores.
- Still open: **WSL mirrored networking** (`.wslconfig` → `networkingMode=mirrored`) is the durable
  fix for the Jellyfin URL; the gateway IP in `.env` moves when WSL restarts, and is untracked.

## Where the rest of the context lives

- **Durable stores:** `docs/r1/adr.md` · `docs/learnings.md` · `docs/r1/tickets.md` · `docs/r1/spec.md`
  · `docs/r1/architecture.md` · `cleanmuzik-prd.md` · git. Read order in `CLAUDE.md`.
- **Business/vault context** — the garden, via `/garden`.
