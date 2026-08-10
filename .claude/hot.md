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
> stores (`docs/r1/adr.md` · `docs/learnings.md` · `docs/research/` · `docs/r2/spec.md` · git);
> business/vault learnings go to the garden via `/graft`.

## What this repo is

CleanMuzik — personal YouTube → Jellyfin music tool. Purpose, stack, constraints, read-order in
`CLAUDE.md`; scope in `cleanmuzik-prd.md`. Not restated here.

## Current State (2026-08-10)

- **On `main`**, pushed to `origin` at `e569052`. **Uncommitted:** today's spike exp 8/9 (`throttle_probe.py`,
  `b_flow.py` + result JSONs), the ADR-021 amendment, the spike-ledger update, this board.
- **R1 + R1.1 shipped.** R2 (playlists + T-037) scope-locked, `docs/r2/spec.md` `ready-for-agent`, parked
  behind the engine decision. Migrate/clean → R2.5.

## ⟹ Engine decision — architecture **B locked in** (2026-08-10)

Evidence: `docs/research/engine-rethink-spike.md` (exp 1/3/6/7 gate + exp 8/9 head-to-head). **B = multi-sense
reconciliation**, chosen over A (veto-only adjudicator):

- **Rule 1 — senses vote (2-of-3).** Auto-land needs ≥2 of {yt-dlp title, AcoustID fingerprint, Shazam} to
  agree; disagreement → park. The LLM *may* now override a wrong fingerprint iff 2 senses corroborate — this
  **reversed ADR-021's veto-only clause** (amended 2026-08-10). Validated on Pa Salieu, n=1 for the override.
- **Rule 2 — facts only from a real lookup** (already true, carried forward): ID from fingerprint MBID or
  ISRC→MB; LLM never invents one. No-ID freestyles land untagged, undeduped — unchanged; acoustic dedup = R2.
- **Why:** B ~4s vs today's 11/37s (8.6×), Shazam sustains back-to-back (exp 8, no throttle), and B *resolves*
  the Pa Salieu mistag A could only park.

## ⟹ NEXT

1. **Rewrite `docs/r1.5/spec.md` for B.** The drafted spec is for **A** and is holey (3-reviewer panel: cold-build
   + adversarial + consistency — findings still valid). New §5 safety = the 2-of-3 rule, not veto-only.
2. **Open build items to fold into the B spec:** Shazam **packaging seam** (lean: subprocess to the 3.12
   `.venv-shazam`); **hard Shazam timeout** (exp 8 tail); ISRC→MB covers only ~46% (fingerprint MBID covers the
   confident rest); the review-card `reason`/`contradictions` **persist to SQLite** (don't repeat ADR-010);
   **ADR-016 design gate** on the review card. Then decompose tickets + add R1.5/R1.6 rows to `docs/roadmap.md`.
3. R1.6+: genre/mood enrichment (ADR-023, gated on the unrun exp 4), re-search rescue agent (T-034/035).

## Live library mess (real cleanup, unticketed)

`Vanessa Bling…/Frontline.mp3` is really Pa Salieu (spike marquee fixture — re-tag). `JAŸ-Z/Roc Boys` — T-037.

## Recent sessions (rolling — last 2–3)

- **2026-08-10** — Ratified ADR-021–023 + filed librarian direction (`prd §2.1`), merged spike→main (suites
  green), pushed. Drafted `r1.5/spec.md` (for A) → ran a 3-agent cold review (real holes). Then ran exp 8
  (Shazam no-throttle) + exp 9 (full B head-to-head, 8.6× + resolved Pa Salieu) → **pivoted A→B, locked in**,
  amended ADR-021. Next: rewrite the spec for B.
- **2026-08-09** — Ran the accuracy/speed spike (locks 1b/3/7 met). R2 specced; council → identify (not
  download) is the bottleneck.

## Where the rest of the context lives

`docs/research/engine-rethink-spike.md` (spike + B decision) · `engine-rethink-council.md` · `docs/roadmap.md`
· `docs/r1.5/spec.md` (A-draft, to rewrite) · `docs/r2/spec.md` · `docs/r1/adr.md` · `docs/learnings.md` · git.
Business/vault → `/garden`.
