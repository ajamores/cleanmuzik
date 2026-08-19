---
type: meta
title: "Hot — cleanmuzik"
updated: 2026-08-19
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

## Current State (2026-08-19)

- **On `main`, tree clean** (only `.vscode/` untracked). **679 server + 91 client tests green on main.**
  **Merged but NOT pushed** (main is 1 ahead of `origin/main` — the T-310 commit `cc44520`; push is yours).
  R2 (Playlists) `in-build`.
- **T-310 done + merged** — the batch view. **One aggregate card** per playlist paste (not fifty): durable
  tally+state from the T-312 snapshot, live rows off the T-305 stamped `track.*` stream, "needs you" from the
  durable review inbox hoisted on top, art on landed rows only, warmth-not-alarms. Plus the **acquire dial**
  (ADR-029: Single default / Playlist / Multi·soon inert). Reused the shipped console skin + review-inbox
  resolve seam; single-song R1 card unchanged.
- **Build decisions** (settled at build): (1) `never_started` batch state for the `total==0` phantom (screen
  07); (2) **Option 2 review-scoping** — review payload carries `playlist_id`+`position` (one bulk
  `membership_for_jobs` query) so the card owns its parked tracks; (3) per-track **row detail is live-only**
  (ADR-027 seam 5) — tally durable, row detail best-effort after a restart.
- **`/code-review` caught two subtle traps, both fixed + tested + filed to `learnings.md`:** a batch park was
  orphaned on reload (filtered from the inbox with no card to host it) → App now recovers a card from the
  review; and an async cold-load raced the SSE open → the stream now opens only once the snapshot says the
  batch is still live. Live-verified over a real socket (never_started, review membership, settled stream
  closes cleanly).

## ⟹ NEXT

1. **T-307** — idempotent re-paste (backend, buildable; rides T-303/T-304's idempotent append).
2. **T-308** — `git mv docs/backlog/T-037.md docs/r2/` (artist-credit normalisation; ADR-028 filed).
3. **T-311** — the FULL end-to-end `/verify` (whole acceptance checklist). **Now unblocked** — the batch
   card (T-310) it needed just landed. Carries the two live-Jellyfin seams already fixed under T-314.

## Recent sessions (rolling — last 2–3)

- **2026-08-19 (this session)** — Built + merged **T-310** solo (Opus): backend `never_started` + review
  membership, `AcquireDial` + `BatchCard` + App rewire, 178 new test lines. Owned the full DoD; `/code-review`
  found 2 real traps, both fixed. 679+91 green on main.
- **2026-08-18** — Built + merged **T-312** (durable batch snapshot) via a fable agent; 3-seat council ruled
  the payload aggregate-only (ADR-027 seam 5).
- **2026-08-18 (earlier)** — Built + merged **T-305** (batch-scoped SSE, one stream per batch).

## Where the rest of the context lives

`docs/roadmap.md` (R2 `in-build`) · `docs/r2/spec.md` + **`tickets.md`** (T-300–306, **T-305/T-312/T-310**
done; T-307/T-308/T-311/T-315 open) · `docs/r1/adr.md` (**ADR-027 seam 5** aggregate-only read; **ADR-029**
acquire dial) · `docs/learnings.md` (2026-08-19: reload-orphan + stream-race traps) · `docs/workflow.md` ·
`docs/backlog/` (T-037). Business → `/graft`.
