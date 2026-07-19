---
type: meta
title: "Hot — cleanmuzik"
updated: 2026-07-18
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

- **On `main`, nothing committed.** Uncommitted: `server/app/download.py` + tests (classifier),
  `server/app/beets_engine.py` (`original_date` reverted — inert on singletons), and `docs/`
  (ADR-011 rejected, 3 learnings, T-016 receipt, T-021→T-027). Rationale for each is in those
  files, not here.
- `.env` is git-ignored and **machine-local**: `JELLYFIN_URL` → WSL gateway IP.
- Suite **284 green**. Ledger: **T-016 DONE**; open = T-017, T-019, T-020, T-021→T-027.
- **RE-REVIEW OWED.** A 23-agent review found 9 defects; 7 are fixed in this tree and **the fixes
  are themselves unreviewed**. T-026 and T-027 were left unfixed on purpose — each ticket says why.

## NEXT

1. **Re-review the working tree** (the fixes for the 9 findings are unreviewed), then commit + push.
   Nothing from this session is landed. Suggested commits: the classifier fix, the ADR-011
   rejection + revert, the docs/findings batch.
2. **Decide T-026** — one owner call, blocks nothing else.
3. **Finish the run list** (`docs/r1/tickets.md`, "First owner-driven browser session") — rows
   **2, 3, 4, 6** are unrun. Needs the owner in a browser; rows 3–4 are T-020's only evidence, and
   row 6 now re-tests the changed classifier.
4. Then **T-017** (review panel UI) — reuses T-016's EventSource pattern, now proven live.

**Standing setup note:** two terminals — `cd server && ./.venv/bin/uvicorn app.main:app --reload
--port 8137`, and `cd client && npm run dev`. `.env` lives at the **repo root** and `--reload` only
watches `server/`, so an `.env` edit needs a manual uvicorn restart (`get_settings` is `lru_cache`d).

## Recent sessions (rolling — last 2–3)

### 2026-07-18/19 — first browser session ever; rows 1 + 5 pass, then a review that bit back
- **Nothing could be tested until four defects were fixed**, none visible to a green suite. The
  review then found 9 more in those same fixes. All durable output is filed; see the stores.
- Still open: **WSL mirrored networking** (`.wslconfig` → `networkingMode=mirrored`) is the durable
  fix for the Jellyfin URL; the gateway IP in `.env` moves when WSL restarts, and is untracked.

### 2026-07-18 (earlier) — T-016 integration: scope cut, not patched
- Two pre-commit reviews on the merge: 8 defects, then 10. Cut the give-up policy to T-020 rather
  than patch a 4th time. Also fixed a dead Vite proxy port (`fbf2da3`).

## Where the rest of the context lives

- **Durable stores:** `docs/r1/adr.md` · `docs/learnings.md` · `docs/r1/tickets.md` · `docs/r1/spec.md`
  · `docs/r1/architecture.md` · `cleanmuzik-prd.md` · git. Read order in `CLAUDE.md`.
- **Business/vault context** — the garden, via `/garden`.
