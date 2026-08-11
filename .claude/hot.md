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

- **On `main`, at `1b6c070`, clean tree.** Suite **515 passed**. (Not yet pushed to origin.)
- **R1 + R1.1 shipped.** **R1.5** (engine rethink, architecture **B** — multi-sense reconciliation) in
  build. **Phase A + T-204/T-205 done.** **T-205 landed** — the 2-of-3 accept gate is live:
  `choose_item` dispatches (no adjudicator → R1 fingerprint gate; wired → `_reconcile_gate`), the gate
  **re-derives agreement in code** and lands iff accept + ≥2 present senses + real MBID, else parks.
  Rejected key degrades; transient failure parks. New `normalize.loose_key/loose_match` (shared with
  `artwork`). `/code-review`'d high: 3 correctness bugs fixed (uncaught MB lookup, wrong-cover-art
  dominance, diacritic fold), 2 cleanups, 1 deferred to T-206. **ADR-025** = reconcile model.

## ⟹ NEXT — Phase B continues, sequential

**T-206 review-row persistence** (`db.py` + `create_review`) → **T-207 review-card UI** (ADR-016
design gate FIRST) → **T-209 verify** (needs **T-200** = owner sets `ANTHROPIC_APIKEY` in `.env`).
T-208 reserved.

**Build note for T-206 (don't re-derive):**
- Add columns via `db.py:_ADDED_COLUMNS` (additive migration, **not** a `CREATE TABLE` edit):
  `("reviews","reason","TEXT")`, `("reviews","contradictions_json","TEXT")`.
- Persist `session.verdict.reason` + `.contradictions`, and reorder `candidate_ids` by
  `verdict.ranking` before `create_review` (`import_seam.py`). **T-205 already stashes
  `session.reconcile_candidates`** (the augmented list) so ranking indices resolve to real MBIDs —
  this is also how the synthetic **ISRC candidate** reaches the review row (the F6 gap T-205 left).
- `candidate_scores_json` is MBID-keyed (not a parallel array), so reordering `candidate_ids` is safe.

## Watch at T-209 (filed, not open work)

- **`docs/backlog/T-210`** — isrc.py's 1/sec gate independent of beets' MB limiter; back-to-back calls
  can breach MB's floor. Low real risk; watched in the T-209 sweep.
- **`docs/backlog/T-211`** — `loose_match` containment false-matches short names (`Sia`⊂`Asia`);
  correlated yt+sz errors could auto-land wrong. Owner-ratified containment stands; very low risk.

## Recent sessions (rolling — last 2–3)

- **2026-08-11 (this session)** — Built + landed **T-205** (2-of-3 accept gate + degrade). Rewired
  `choose_item` into `_fingerprint_gate`/`_reconcile_gate`; `_agreeing_senses` re-derives the vote in
  code; shared `_accept` + `match_for_recording` (extracted from `ResolveSession`). Added
  `normalize.loose_key/loose_match`; `artwork` delegates to it. High review fixed 3 correctness bugs;
  filed T-211. +27 tests. Committed to main (not pushed).
- **2026-08-11 (earlier)** — Built + landed **T-204** (reconcile seam, `app/reconcile.py`, index-only
  forced-tool schema). ADR-025 + `anthropic` dep. Merged, pushed.
- **2026-08-10** — Built + landed R1.5 Phase A (T-201∥202∥203) via 3-worktree fan-out; ADR-024 + T-210.

## Where the rest of the context lives

`docs/r1.5/spec.md` (v3) · `docs/r1.5/tickets.md` · `docs/research/engine-rethink-spike.md` ·
`docs/roadmap.md` · `docs/r1/adr.md` (thru ADR-025) · `docs/learnings.md` · `docs/backlog/`. Business/vault → `/garden`.
