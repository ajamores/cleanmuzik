---
type: meta
title: "Hot — cleanmuzik"
updated: 2026-08-11
tags:
  - meta
  - hot-cache
status: evergreen
---
# Hot — cleanmuzik (personal YouTube → Jellyfin music tool)

> This repo's own working-memory board — session continuity, loaded at session start via `/hot`.
> A cache, not a journal: rewritten each save, never appended. Durable knowledge lives in this repo's
> stores (`docs/r1/adr.md` · `docs/learnings.md` · `docs/research/` · `docs/backlog/` · git); business
> learnings go to the garden via `/graft`.

## What this repo is

CleanMuzik — personal YouTube → Jellyfin music tool. Purpose, stack, constraints, read-order in
`CLAUDE.md`; scope in `cleanmuzik-prd.md`. Not restated here.

## Current State (2026-08-11)

- **On `main`, at `1c6cee1`, clean tree, pushed to origin.** Suite **524 passed**.
- **R1 + R1.1 shipped.** **R1.5** (engine rethink, architecture **B** — multi-sense reconciliation) in
  build. **Phase A + T-204/T-205 done. T-206 landed.**
- **T-206** — parked-review park story now persists: `reviews.reason` + `contradictions_json` columns
  (additive migration via `_ADDED_COLUMNS`), `candidate_ids` written in the Verdict's ranked order
  through the augmented list, so the **synthetic ISRC candidate reaches the row** (F6). Live
  `track.review_required` event + `GET /api/reviews` both carry reason/contradictions and the same
  ranked list — event↔row can't drift. `/code-review` high fixed 2: live-event still shipped
  beets-only candidates (ISRC missing until reload); stale per-track `verdict`/`reconcile_candidates`
  (now reset atop `choose_item`).

## ⟹ NEXT — Phase C, sequential

**T-207 review-card UI** — **ADR-016 design gate FIRST** (changes a user-visible state): flat HTML
scenario screens, one per scenario *incl failure/edge* (2-of-3 park w/ contradictions; Pa-Salieu
override auto-landed = no card; Shazam-absent park; reconcile-unavailable park; degrade-mode land),
owner sign-off *before* component code. Then render the persisted `reason`/`contradictions`, ranked
candidates, Shazam hint (labelled, ADR-020 exits only — no new landing path). **Don't** render LLM
confidence (never reaches the row) or raw scores as a verdict (T-017). Acceptance is self-contained
(§7 has no render item). Then **T-209 verify** — needs **T-200** = owner sets `ANTHROPIC_APIKEY` in
`.env`. T-208 reserved.

## Watch at T-209 (filed, not open work)

- **`docs/backlog/T-210`** — isrc.py's 1/sec gate independent of beets' MB limiter; back-to-back calls
  can breach MB's floor. Low real risk; watched in the T-209 sweep.
- **`docs/backlog/T-211`** — `loose_match` containment false-matches short names (`Sia`⊂`Asia`);
  correlated yt+sz errors could auto-land wrong. Owner-ratified containment stands; very low risk.

## Recent sessions (rolling — last 2–3)

- **2026-08-11 (this session)** — Built + landed **T-206** (park-story persistence). `reason` +
  `contradictions_json` columns; `_park` renders one ranked augmented list driving both the row and
  the SSE event (ISRC candidate reaches both). High review fixed 2 (live-event drift, stale session
  state). +9 tests, suite 524. Merged to main, pushed.
- **2026-08-11 (earlier)** — Built + landed **T-205** (2-of-3 accept gate + degrade); `_agreeing_senses`
  re-derives the vote in code. Filed T-211. Merged, pushed.
- **2026-08-11 (earlier)** — Built + landed **T-204** (reconcile seam, `app/reconcile.py`). ADR-025.

## Where the rest of the context lives

`docs/r1.5/spec.md` (v3) · `docs/r1.5/tickets.md` · `docs/research/engine-rethink-spike.md` ·
`docs/roadmap.md` · `docs/r1/adr.md` (thru ADR-025) · `docs/learnings.md` · `docs/backlog/`. Business/vault → `/garden`.
