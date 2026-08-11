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

- **On `main`, at `e07147d`, clean tree, pushed to origin.** Suite **488 passed**.
- **R1 + R1.1 shipped.** **R1.5** (engine rethink, architecture **B** — multi-sense reconciliation) in
  build. **Phase A done** (T-201/202/203 senses). **T-204 done** — the reconcile seam: `choose_item`
  now gathers the senses, builds augmented `candidates[]`, and stashes a validated **`Verdict`**
  (`app/reconcile.py`); it does **not** yet land/park on it. `/code-review`'d high (2 findings fixed,
  1 skipped as intended-design). **ADR-025** filed (reconcile model = `claude-haiku-4-5` @ temp 0).

## ⟹ NEXT — Phase B continues, sequential (all `import_seam.py`/`db.py`)

**T-205 the 2-of-3 gate + degrade** (deps T-204 ✓) → **T-206 review-row persistence**. Then **T-207
review-card UI** (ADR-016 design gate FIRST) → **T-209 verify** (needs **T-200** = owner sets
`ANTHROPIC_APIKEY` in `.env`). T-208 reserved.

**Build note for T-205 (don't re-derive):**
- Consume `session.verdict` (a `reconcile.Verdict`) + the augmented `candidates[]`. The gate
  **RE-DERIVES `agreeing_senses` in code** from *present* senses — never trusts the LLM's count.
  Auto-land iff ALL: `verdict=="accept"` **and** code-validated agreeing ≥ 2 **and**
  `candidates[chosen].mbid` non-null; else park. `chosen_candidate` already coerced to a real index or
  None (an accept-with-no-identity is downgraded to park in `_coerce_verdict`).
- Normalizer = loose/containment (owner-ratified): port `spike/b_flow.py:43` alnum-fold + substring on
  artist AND title into a shared `app/` helper. This is what parks Strawberry Swing.
- Degrade: `ANTHROPIC_APIKEY` absent/rejected → R1 fingerprint-only gate (already the interim state,
  since `reconcile_fn` is None without a key); a transient mid-run failure still parks that one track.

## Watch at T-209 (filed, not open work)

- **`docs/backlog/T-210`** — isrc.py's 1/sec gate is independent of beets' MB limiter; back-to-back
  calls can breach MB's floor. Low real risk; deferred, watched in the T-209 sweep.

## Recent sessions (rolling — last 2–3)

- **2026-08-11 (this session)** — Built + landed **T-204** (reconcile seam). New `app/reconcile.py`
  (index-only forced-tool schema, no free-text identity; confidence structurally absent). Wired 4
  stubbable seams into `FingerprintTrustSession`; `import_song` builds defaults, degrades w/o key.
  ADR-025 + `anthropic` dep declared. High review: fixed unguarded import + accept-with-no-identity;
  skipped reconcile-per-track (intended B). Merged to main, pushed.
- **2026-08-10** — Built + landed R1.5 Phase A (T-201∥202∥203) via 3-worktree fan-out; ADR-024 +
  backlog T-210 filed.

## Where the rest of the context lives

`docs/r1.5/spec.md` (v3) · `docs/r1.5/tickets.md` · `docs/research/engine-rethink-spike.md` ·
`docs/roadmap.md` · `docs/r1/adr.md` (thru ADR-025) · `docs/learnings.md` · `docs/backlog/`. Business/vault → `/garden`.
