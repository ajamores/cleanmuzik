---
type: meta
title: "Hot — cleanmuzik"
updated: 2026-08-21
tags:
  - meta
  - hot-cache
status: evergreen
---
# Hot — cleanmuzik (personal YouTube → Jellyfin music tool)

> This repo's own working-memory board — session continuity, loaded at session start via `/hot`.
> A cache, not a journal: rewritten each save, never appended. Durable knowledge lives in this repo's
> stores (`docs/roadmap.md` · `docs/r1/adr.md` · `docs/r2/` · `docs/backlog/` · `docs/learnings.md` · git);
> business learnings go to the garden via `/graft`.

## What this repo is

CleanMuzik — personal YouTube → Jellyfin music tool. Purpose, stack, constraints, read-order in
`CLAUDE.md`; scope in `cleanmuzik-prd.md`. Not restated here.

## Current State (2026-08-21)

- **On `main`, clean tree** (only `.vscode/` untracked). **727 server tests green.** **`main` pushed —
  in sync with `origin/main`.**
- **R2 (Playlists) SHIPPED 2026-08-21** — roadmap flipped `in-build`→`shipped`; T-311 (the last ticket)
  passed the full acceptance sweep live against the real Jellyfin. **All R2 tickets closed + pushed.**
- **T-316 shipped** (found *by* T-311): the pipeline lands POSIX `/mnt/c/…` paths but Jellyfin reports
  `C:\…\`, so the exact resolve match never succeeded — no landed track ever joined its playlist. Fixed
  (library-relative, case-folded tail match). Full evidence + the two owner-accepted residuals (item 7
  failed-doesn't-stop, item 8 card) are in `docs/r2/tickets.md` T-311/T-316 — not restated here.

## ⟹ NEXT

1. **Start R2.5 (Migrate/clean the existing library)** — the one the owner actually wants (fills the
   library worth streaming in the car). It's `backlog`; move it → `specing` and write its spec to begin.
   R1.5's engine + R2's batch model are what its bulk run multiplies over; **T-208** (per-song speed)
   graduates here.
2. Or drain backlog speed follow-ons anytime: **T-217** scan debounce · **T-215** Shazam overlap.

## Recent sessions (rolling — last 2–3)

- **2026-08-21 (this session)** — **Closed T-311** (full live acceptance sweep). Found + fixed **T-316**
  (WSL/Windows resolve path bridge, the R2 blocker) → merged, 727 green. Drove the whole checklist against
  a temp `/mnt/c` library registered to Jellyfin (removed after; real library untouched). All verify
  artifacts cleaned up. Solo (Opus).
- **2026-08-20** — Shipped **T-315** (recover a deleted playlist id: 3-state pre-check + recreate/rebuild).
  Closed **T-309** (genre off disk); filed **T-050**. Earlier: **T-308** (ADR-028 credit fold).

## Where the rest of the context lives

`docs/roadmap.md` (R2 **all tickets done**, flip to `shipped` pending) · `docs/r2/tickets.md` (T-311 +
T-316 done; whole R2 closed) · `docs/r1/adr.md` (ADR-027 batch · ADR-028 credit · ADR-029 acquire dial) ·
`docs/learnings.md` (T-316 `==`-across-a-format-boundary; T-311 verify-staging gotchas) ·
`docs/backlog/` (T-050 · T-049 · T-216/217 · T-208/214/215). Business → `/graft`.
