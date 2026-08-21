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

- **On `main`, clean tree** (only `.vscode/` untracked). **727 server tests green on `main`.** Ahead of
  `origin/main` by **3 commits — not pushed** (push is the owner's call; the prior board's "8" was stale).
- **R2's last ticket (T-311) is DONE** — the full end-to-end acceptance sweep passed live against the real
  Jellyfin. **All R2 tickets are now closed.** R2 is functionally complete.
- **T-316 shipped** (found *by* T-311): the pipeline lands POSIX `/mnt/c/…` paths but Jellyfin reports
  `C:\…\`, so the exact resolve match never succeeded — no landed track ever joined its playlist. Fixed
  (library-relative, case-folded tail match). Full evidence + the two owner-accepted residuals (item 7
  failed-doesn't-stop, item 8 card) are in `docs/r2/tickets.md` T-311/T-316 — not restated here.

## ⟹ NEXT

1. **Flip R2 `in-build` → `shipped`** in `docs/roadmap.md` (all tickets done; owner-accepted residuals) —
   a release-close call, owner's to confirm (a `/maintenance` moment).
2. **Push `main`** to origin (3 unpushed) — owner's call.
3. Then pick the next release: **R2.5 (migrate/clean the existing library)** per the roadmap, or drain the
   backlog speed follow-ons (**T-217** scan debounce · **T-215** Shazam overlap · **T-208** MB de-hydration).

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
