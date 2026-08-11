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

- **On `main`, at `b0d6f35`.** One **uncommitted new file: `docs/r1.5/tickets.md`** (this session's work).
- **R1 + R1.1 shipped.** **R1.5 is the current release** — engine rethink, architecture **B**
  (multi-sense reconciliation). Spec signed off (`docs/r1.5/spec.md` v3). Just moved from *specing* →
  **tickets drafted, pending review-fixes + owner sign-off**.

## ⟹ NEXT — build R1.5, starting the T-201∥T-202∥T-203 fan-out

R1.5 tickets **SIGNED OFF + committed** (`docs/r1.5/tickets.md`). Dep order: **T-201 SourceSignals ∥
T-202 Shazam ∥ T-203 ISRC→MB** (disjoint fan-out, build first) → **T-204 reconcile seam → T-205 2-of-3
gate → T-206 review-row persistence** (all `import_seam.py`/`db.py`, sequential) → **T-207 review-card UI
(ADR-016 design gate first)** → **T-209 verify**. T-200 = owner sets `ANTHROPIC_APIKEY`; T-208 = reserved.

**Ratified into the tickets (don't re-litigate):**
- **Normalizer = loose/containment** (T-205, `spike/b_flow.py:43` alnum-fold + substring on artist AND
  title). 2-of-3 rule covers the short-name false-match risk.
- **SourceSignals prefers YouTube's structured `artist`/`track`/`album`/`release_year`** over title-parse;
  `yt_album`/`yt_release_year` are **judgment-only** (fed to the AI, never written, never in the code vote —
  facts stay MusicBrainz/ISRC). In both `spec.md §2` and T-201.

**Build note for whoever starts T-204/T-205:** structured output = Anthropic tool-use + per-track enum on
`chosen_candidate` (see `claude-api` skill); **do NOT copy `spike/b_flow.py`'s free-text schema** (it lets
the LLM author the MBID — forbidden). T-202 files a new ADR (subprocess-against-3.12 + the per-track
widening of ADR-019).

## Recent sessions (rolling — last 2–3)

- **2026-08-10 (this session)** — Drafted `docs/r1.5/tickets.md` (T-200–T-209) from spec v3 + real code
  seams. Ran spec-fidelity review (3 fixes above; coverage/scope/deps otherwise clean). Buildability
  review interrupted. Uncommitted.
- **2026-08-10 (earlier)** — Ratified ADR-021–023, merged spike→main, spec A→B pivot (exp 8/9), spec v3,
  beets audit (dropped Shazam art/lyrics; filed T-043 + learnings). Suites green (432/65).

## Where the rest of the context lives

`docs/r1.5/spec.md` (v3) · `docs/r1.5/tickets.md` (new) · `docs/research/engine-rethink-spike.md` ·
`docs/roadmap.md` · `docs/r1/adr.md` · `docs/learnings.md` · `docs/backlog/`. Business/vault → `/garden`.
