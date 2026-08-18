---
type: meta
title: "Hot — cleanmuzik"
updated: 2026-08-18
tags:
  - meta
  - hot-cache
status: evergreen
---
# Hot — cleanmuzik (personal YouTube → Jellyfin music tool)

> This repo's own working-memory board — session continuity, loaded at session start via `/hot`.
> A cache, not a journal: rewritten each save, never appended. Durable knowledge lives in this repo's
> stores (`docs/roadmap.md` · `docs/r1/adr.md` · `docs/r2/` · `docs/backlog/` · git); business
> learnings go to the garden via `/graft`.

## What this repo is

CleanMuzik — personal YouTube → Jellyfin music tool. Purpose, stack, constraints, read-order in
`CLAUDE.md`; scope in `cleanmuzik-prd.md`. Not restated here.

## Current State (2026-08-18)

- **On `main`, tree clean. 670 tests green. Merged but NOT pushed** (origin is behind by the T-305
  feat + merge — push is yours to call). R2 (Playlists) `in-build`.
- **T-305 done + merged** — the batch spine's first stone: a batch drives **one** playlist-scoped SSE
  stream, not one-per-track (dual-publish via `_BatchScopedBus`; `batch.queued`/`batch.progress`; tally
  recomputed from SQLite; "waiting on you" while parked > 0; channel pinned against eviction). Full
  mechanism + the 2 fixed `/code-review` findings (batch channel orphaned open+pinned when the final
  member bypassed the wrapper) + the 3 triaged ones are in `tickets.md` T-305 and commit `a908c4c`.
- Live-verified over a real socket (isolated DB): 404 on unknown, clean close for a settled batch, stays
  open while parked. The full live batch grind with real downloads is **T-311**'s e2e.

## ⟹ NEXT

1. **T-312** — durable batch state + reconnect (`GET /api/playlists/{id}`). **Now unblocked** (depended
   on T-305). Reuses `count_jobs_by_status` + `batch_progress_payload` as its **exact** projection source.
2. **T-310** — batch card (aggregate view). **Design gate first** (ADR-016: flat HTML scenario screens,
   incl. ugly states, signed off before component code). Renders `stuck_since`; client closes its
   EventSource on `state != running` (the batch edition of the EventSource-close rule).
3. **T-308** — `git mv docs/backlog/T-037.md docs/r2/` (artist-credit normalisation; ADR-028 already filed).
4. **T-307** — idempotent re-paste (buildable; rides T-303/T-304's idempotent append).
5. **T-311** — the FULL end-to-end `/verify` (whole acceptance checklist). Needs the spine above.

## Recent sessions (rolling — last 2–3)

- **2026-08-18 (this session)** — Built **T-305** via a fable agent in a worktree; owned the DoD (review,
  acceptance, live `/verify`, integration). Fixed 2 review findings, merged to `main`, 670 green.
- **2026-08-18 (earlier)** — Built + pushed **T-306** (parked→resolved appends to its playlist); filed
  **T-315** from a review finding.
- **2026-08-17** — Merged **T-313** then **T-314**; playlist append works live for the first time.

## Where the rest of the context lives

`docs/roadmap.md` (R2 `in-build`) · `docs/r2/spec.md` + **`tickets.md`** (T-300–304, T-313, T-314, T-306,
**T-305** done; T-312/T-310/T-308/T-307/T-311/T-315 open) · `docs/r1/adr.md` (**ADR-027 seam-1**;
create-if-missing = settled null-case guard) · `docs/learnings.md` · `docs/workflow.md` ·
`docs/backlog/` (T-037). Business → `/graft`.
