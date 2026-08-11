---
type: meta
title: "Hot — cleanmuzik"
updated: 2026-08-10
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

## Current State (2026-08-10)

- **On `main`, at `43a2bdd`, clean tree.** Suite **465 passed**.
- **R1 + R1.1 shipped.** **R1.5** (engine rethink, architecture **B** — multi-sense reconciliation) in
  build. **Phase A done:** the three sense-gatherers landed — **T-201** SourceSignals ∥ **T-202** Shazam
  subprocess ∥ **T-203** ISRC→MusicBrainz — each `/code-review`'d (high, workflow-backed), findings folded,
  ledger flipped. **ADR-024** filed (Shazam subprocess + per-track widening of ADR-019).

## ⟹ NEXT — Phase B, the reconcile spine (sequential, all `import_seam.py`/`db.py`)

**T-204 reconcile seam** (deps T-201/202/203 now all satisfied) → **T-205 2-of-3 gate + degrade** →
**T-206 review-row persistence**. Then **T-207 review-card UI** (ADR-016 design gate FIRST) → **T-209
verify** (needs **T-200** = owner sets `ANTHROPIC_APIKEY` in `.env`). T-208 reserved.

**Build note for T-204/205 (don't re-derive):**
- Structured output = Anthropic **tool-use + forced `tool_choice`** on one `record_verdict` tool; per-track
  `chosen_candidate` = **enum over present `n` values + null** (no free-text identity). Consult the
  `claude-api` skill. **Do NOT copy `spike/b_flow.py`** — its free-text schema lets the LLM author the MBID.
- Injection shapes from Phase A: `SourceSignals` (`from app.source_signals import SourceSignals`);
  `shazam.recognize(path, *, timeout_s=...)`; `isrc.isrc_to_mb(isrc) -> ISRCRecording|None` (read
  `.mbid/.artist/.title`). All three stubbable offline like `dominance_fn`.
- Normalizer for T-205 = loose/containment (`spike/b_flow.py:43` alnum-fold + substring on artist AND
  title); 2-of-3 covers the short-name false-match risk. Gate RE-DERIVES `agreeing_senses` in code.

## Watch at T-209 (filed, not open work)

- **`docs/backlog/T-210`** — isrc.py's 1/sec gate is independent of beets' MB limiter; back-to-back calls
  can breach MB's floor. Low real risk (26-track spike ran both paths unthrottled, never tripped it);
  deferred, watched in the T-209 sweep.

## Recent sessions (rolling — last 2–3)

- **2026-08-10 (this session)** — Built + landed R1.5 Phase A (T-201∥202∥203) via 3-worktree fan-out;
  each high-effort reviewed, findings folded (promoted `normalize.split_leading_artist`; Shazam timeout →
  `Settings`, last-line stdout parse; isrc fail-soft guard + centralized MB User-Agent w/ real repo URL).
  ADR-024 + backlog T-210 filed. Worktrees cleaned.
- **2026-08-10 (earlier)** — Drafted + signed off `docs/r1.5/tickets.md` (T-200–T-209) from spec v3.

## Where the rest of the context lives

`docs/r1.5/spec.md` (v3) · `docs/r1.5/tickets.md` · `docs/research/engine-rethink-spike.md` ·
`docs/roadmap.md` · `docs/r1/adr.md` (thru ADR-024) · `docs/learnings.md` · `docs/backlog/`. Business/vault → `/garden`.
