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

- **On `main`, tree clean. 676 tests green. Merged but NOT pushed** (main is ahead of `origin/main` —
  the T-312 feat + merge + docs at least; push is yours to call). R2 (Playlists) `in-build`.
- **T-312 done + merged** — the batch spine's reconnect stone: **`GET /api/playlists/{id}`**, a read-only
  projection that rebuilds a batch's aggregate tally + terminal state purely from SQLite
  (`count_jobs_by_status` → `batch_progress_payload`, the exact read `batch.progress` rides) plus the
  playlist's durable identity — so "walk away, come back after a restart" survives an empty bus. **No live
  overlay** (unlike `get_job`); that's the point.
- **Aggregate-only by decision** — a 3-seat design council (2026-08-18) ruled per-track detail out: ADR-027
  seam 5 reserves the per-track ordered read for T-306/T-310. The ticket's old "and per-track outcomes"
  *What* prose contradicted the ADR — **amended** in the close-out commit.
- Live-verified over a real socket across a **genuine `kill`+relaunch**: tally + `waiting_on_you` came back
  byte-identical from SQLite. `/code-review`: 2 low findings, both **triaged not fixed** — the zero-job
  `total=0 → state=done` edge is filed onto **T-310's design gate** (fix belongs with `batch_progress_payload`,
  not the route); the non-atomic 2-read is nil under ADR-004.

## ⟹ NEXT

1. **T-310** — batch view (one aggregate card). **Now unblocked** (needed T-305 + T-312). **DESIGN GATE
   FIRST** (ADR-016: flat HTML scenario screens incl. ugly states → owner sign-off *before* component code).
   Gate now must cover the **zero-track/partial-enqueue reconnect** state (filed there this session). Also
   carries the ADR-029 acquire-dial screens. Front-end. Gate artifact: `docs/r2/design/t310-batch-view.html`.
2. **T-307** — idempotent re-paste (backend, buildable; rides T-303/T-304's idempotent append).
3. **T-308** — `git mv docs/backlog/T-037.md docs/r2/` (artist-credit normalisation; ADR-028 filed).
4. **T-311** — the FULL end-to-end `/verify` (whole acceptance checklist). Needs the card (T-310).

## Recent sessions (rolling — last 2–3)

- **2026-08-18 (this session)** — Built **T-312** via a fable agent in a worktree; a 3-seat council decided
  the payload (aggregate-only); owned the DoD (review, acceptance, live restart `/verify`, merge, ledger).
  676 green.
- **2026-08-18 (earlier)** — Built + merged **T-305** (batch-scoped SSE, one stream per batch); 670 green.
- **2026-08-18** — Built + pushed **T-306** (parked→resolved appends to its playlist); filed **T-315**.

## Where the rest of the context lives

`docs/roadmap.md` (R2 `in-build`) · `docs/r2/spec.md` + **`tickets.md`** (T-300–306, T-313–314, **T-305**,
**T-312** done; T-310/T-307/T-308/T-311/T-315 open) · `docs/r1/adr.md` (**ADR-027 seam 5** = the batch-tally
aggregate read; per-track ordered read → T-306/T-310) · `docs/learnings.md` · `docs/workflow.md` ·
`docs/backlog/` (T-037). Business → `/graft`.
