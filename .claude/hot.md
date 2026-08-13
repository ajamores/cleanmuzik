---
type: meta
title: "Hot — cleanmuzik"
updated: 2026-08-12
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

## Current State (2026-08-12)

- **On `main`, clean tree, pushed to origin.** Suite **524 passed** (no code changed since T-206).
- **R1 + R1.1 shipped.** **R1.5** (engine rethink, architecture **B** — multi-sense reconciliation) in
  build. **Phase A + T-204/T-205/T-206 landed.** Now in **Phase C (UI)**.
- **T-207 design gate PASSED (owner sign-off).** Five flat scenario screens at
  `docs/r1.5/design/t207-review-card.html`. Component code is the remaining half — **not yet built**.
- **Scope decision at the gate:** standalone Shazam artist/title hint (spec §4) **DEFERRED →
  `docs/backlog/T-212`** (reaches no transport; narrow value; can pre-fill a confident-wrong guess).
  Shazam surfaces only via the ISRC→MB candidate + contradictions text. Spec §4 + T-207 amended.

## ⟹ NEXT — T-207 component code (design gate cleared)

Build `ReviewPanel`'s render of the persisted (T-206) `reason` + `contradictions` + candidates in
**LLM-ranked order**, matching the signed-off screens. **No new payload field / no Shazam control**
(T-212); badge the ISRC candidate's *source* only. **Don't** render LLM confidence or raw scores as a
verdict (T-017 — `ScoreBar` already keeps strength an honest bar). Acceptance self-contained: screens
signed off ✓, then each field observed in a browser. Then **T-209 verify** — needs **T-200** = owner
sets `ANTHROPIC_API_KEY` in `.env`. T-208 reserved.

## Watch at T-209 (filed, not open work)

- **`docs/backlog/T-210`** — isrc.py's 1/sec gate independent of beets' MB limiter; back-to-back calls
  can breach MB's floor. Low real risk.
- **`docs/backlog/T-211`** — `loose_match` containment false-matches short names (`Sia`⊂`Asia`);
  correlated yt+sz errors could auto-land wrong. Owner-ratified containment stands; very low risk.
- **`docs/backlog/T-212`** — deferred standalone Shazam hint; graduate if contradictions text proves an
  inadequate substitute after living with T-207.

## Recent sessions (rolling — last 2–3)

- **2026-08-12 (this session)** — **T-207 design gate passed.** 5 scenario screens, owner signed off.
  Fixed a mock bug (Shazam-ISRC screen was really an auto-land; retitled to a channel-name upload → true
  one-vote park). Deferred standalone Shazam hint (→ T-212); amended spec §4 + T-207. `aeee532`, pushed.
- **2026-08-11** — Built + landed **T-206** (park-story persistence): `reason` + `contradictions_json`
  columns; one ranked augmented list drives both row and SSE event. +9 tests, suite 524. Merged, pushed.
- **2026-08-11 (earlier)** — Built + landed **T-205** (2-of-3 accept gate + degrade). Filed T-211.

## Where the rest of the context lives

`docs/r1.5/spec.md` (v3) · `docs/r1.5/tickets.md` · `docs/r1.5/design/t207-review-card.html` ·
`docs/research/engine-rethink-spike.md` · `docs/roadmap.md` · `docs/r1/adr.md` (thru ADR-025) ·
`docs/learnings.md` · `docs/backlog/`. Business/vault → `/graft`.
