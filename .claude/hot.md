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

- **On `main`, clean**, through `2cd39f5`. Server suite **309 green**; client suite **4 green**
  (new — `npm run test` in `client/`).
- **The owner's dev servers are up**: `uvicorn --reload` on 8137, Vite on 8137's proxy. Note the
  hazard now in `CLAUDE.md`: editing `db.py` re-runs the lifespan against the **live** DB.
- Ledger: **T-016, T-028 done**; **T-024 built** (needs browser row 7); open = T-017, T-019, T-020,
  T-021→T-027.

## NEXT

1. **T-017 — review panel UI.** The session's remaining work; nothing blocks it now. Harness,
   prerequisite and design inputs are all in place — read T-017's ticket first, it carries a
   measured score table that constrains the design.
2. **Browser rows 2, 3, 4, 6, 7** — needs the owner in a browser. Row 7 is T-024's only receipt.
3. Then **T-019** (the §7 acceptance pass, unblocked once T-017 lands).

**Ticket triage is discharged** — the answer was that T-021–T-027 were already triaged in the
writing; only T-024 was urgent (it corrupted the library on every collaboration). T-026 is still
parked with option (c) as the standing recommendation.

## Recent sessions (rolling — last 2–3)

### 2026-07-19 (b) — T-024 + a prerequisite T-017 didn't know it had
- T-024 built (ADR-012, `ftintitle`); **T-028 found and done** — the review queue could never
  supply `score`, the field ADR-010 makes the picker's discriminator. Caught by the DoD acceptance
  check on T-017's *ticket*, before writing any of it.
- **`localhost` sockets are not blocked** — `CLAUDE.md` said they were and that claim had scoped
  three tickets around a wall that doesn't exist. Corrected there; autopsy in `learnings.md`.
- Client test harness (vitest + testing-library) stood up, mutation-checked.

### 2026-07-19 (a) — re-review of the unreviewed fixes; 2 defects, both fixed
- The fixes for the 9 review findings had never been reviewed. Two defects found and fixed in
  `6c7c4ee`; lessons in `learnings.md`.

## Where the rest of the context lives

- **Durable stores:** `docs/r1/adr.md` · `docs/learnings.md` · `docs/r1/tickets.md` · `docs/r1/spec.md`
  · `docs/r1/architecture.md` · `cleanmuzik-prd.md` · git. Read order in `CLAUDE.md`.
- **Business/vault context** — the garden, via `/garden`.
