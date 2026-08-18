---
type: meta
title: "Hot — cleanmuzik"
updated: 2026-08-17
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

## Current State (2026-08-17)

- **On `main`. Nothing in flight.** R2 (Playlists) `in-build`, 613 tests green. Uncommitted: this board
  + the T-313 ticket work (about to commit + push).
- **T-303 done + shipped** — exact-video dedup (skip an owned video, add its file, `track.skipped`).
  Added `jobs.landed_path` (ADR-027 seam-2 amendment; narrows ADR-015).
- **T-304 has 3 live bugs** (found via `/code-review high` on T-303, then two councils vs. the shipped
  code): (1) fast batch burns the 20-try give-up counter → drops tracks; (2) append-before-stamp →
  double-add on crash; (3) resolve can't tell "not-indexed" from "Jellyfin down" → outage strands healthy
  tracks. **Root: a retry tally used as a clock.**
- **Design settled — councils decided the fix (T-313):** keep polling + **incremental fill**; retire the
  tally (all 3 sites), 3-state resolve, idempotent append, no-penalty append path, durable visible
  "stuck" state. **Rejected:** push/WebSocket (kills only 2 of 3; half-open socket = the plugin's ghost)
  and **batch-at-end** (adversarially reviewed → no-go: kills 0 extra bugs, adds real liabilities).
- **Live gap found:** `run_resolve` writes no playlist membership → a **parked batch member approved
  later never joins its playlist**. That fix is **T-306** (already todo, buildable now).

## ⟹ NEXT — fix T-304's live bugs BEFORE layering T-305 on the seam

1. **T-313 — reconcile reframe** (fixes the 3 bugs; supersedes T-047; carries an ADR-027 seam-1
   amendment). Backend correctness + a durable "stuck" flag land now; the on-screen surface follows
   with the batch UI (T-310) — no silent loss in the gap.
2. **T-306** — resolve-path membership write; rides T-313's idempotent append, closes the live
   review-approve silent loss.
3. **T-305 — batch-scoped SSE** (one stream/batch + `batch.queued`/`batch.progress`/`track.skipped`).
   *After* T-313, so its tally reports truthful counts, not a broken seam's.
4. **T-312** durable batch state; **T-310** batch card (renders T-313's stuck state); **T-308**
   (Phase D, ADR-028) alongside — `git mv docs/backlog/T-037.md docs/r2/` on start.

## Recent sessions (rolling — last 2–3)

- **2026-08-17 (this session)** — Shipped **T-303**. Review + 2 councils on T-304's reconcile: settled the
  fix as **T-313** (ledger reframe on incremental fill), rejected push + batch-at-end, found the
  review-approve membership gap (→ T-306). Promoted T-047 → T-313.
- **2026-08-17 (earlier)** — Shipped **T-304** defer-first Jellyfin playlist seam (the one now being
  hardened). Fixed a cold-review migration blocker. ADR-027 seam-1 amendment.
- **2026-08-16** — Settled T-304 push-vs-poll → poll. Shipped **T-302** (accept + expand + create_playlist).

## Where the rest of the context lives

`docs/roadmap.md` (R2 `in-build`) · `docs/r2/spec.md` + **`tickets.md`** (T-300/301/302/303/304 done;
**T-313** reconcile reframe; T-306 council note) · `docs/r1/adr.md` (**ADR-027 seam-2 last filed**;
seam-1 amendment pending in T-313) · `docs/learnings.md` · `docs/workflow.md` · `docs/backlog/` (T-047
superseded by T-313; T-037 → git-mv on T-308; T-045/T-046). Business → `/graft`.
