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

- **On `main`, clean tree, pushed to origin** (`5e88c67`). Client suite **71 passed**; server **524**.
- **R1 + R1.1 shipped.** **R1.5** (engine rethink, architecture **B** — multi-sense reconciliation) in
  build. Phase A + T-204/205/206 landed. **Phase C: T-207 DONE. T-200 DONE.**
- **T-207 (review-card park story) landed.** Card renders the persisted `reason` + `contradictions`
  (sense badges) + candidates in adjudicator-ranked order. Per-candidate "via Shazam" badge **dropped by
  owner decision** — candidate row is `{id,title,artist,score}` (ADR-010), no source field; Shazam
  surfaces via its ISRC candidate + contradictions text (spec §5). No new payload field.
- **T-200 (reconcile key) landed.** Its code half was never built — reconcile was silently degraded. Added
  the `anthropic_apikey` field + boot log + `.env.example`; owner fixed the `.env` var name. Verified `set`
  in-process. **Reconcile is now live** once the owner restarts uvicorn to reload `.env`.

## ⟹ NEXT — T-209 end-to-end verify (unblocked)

Reconcile is wired and the key reads `set`. **First: owner restarts uvicorn** (`--reload` won't reload
`.env`) and confirms the boot log reads `anthropic_apikey=set`. Then run **T-209** — the §7 end-to-end
verify: isolated `DB_PATH` + temp beets lib, `pgrep -af uvicorn` first (`docs/workflow.md` + `/verify`).
Drive a real park and observe the whole §7 checklist — including T-207's `reason`/`contradictions`
rendering for real (their first live browser observation) and the Pa Salieu override landing.
**T-208 reserved.**

## Watch at T-209 (filed in `docs/backlog/`, not open work)

- **T-210** — isrc.py's 1/sec gate independent of beets' MB limiter; low real risk.
- **T-211** — `loose_match` containment false-matches short names (`Sia`⊂`Asia`); very low risk.
- **T-212** — deferred standalone Shazam hint; graduate only if contradictions text proves inadequate.

## Recent sessions (rolling — last 2–3)

- **2026-08-12 (this session)** — Landed **T-207** review-card park story (client-only; +6 tests, suite 71;
  code-review 5 findings all addressed). Discovered **T-200 was silently incomplete** (reconcile never ran
  live) and **landed it too** — config field + boot log + `.env.example`. `101f9fb`/`5252302`/`5e88c67`.
- **2026-08-12 (earlier)** — T-207 design gate passed; standalone Shazam hint deferred → T-212. `aeee532`.
- **2026-08-11** — Built + landed **T-206** (park-story persistence): `reason` + `contradictions_json`
  columns; one ranked list drives both row and SSE event. +9 tests.

## Where the rest of the context lives

`docs/r1.5/spec.md` (v3) · `docs/r1.5/tickets.md` · `docs/r1.5/design/t207-review-card.html` ·
`docs/research/engine-rethink-spike.md` · `docs/roadmap.md` · `docs/r1/adr.md` (thru ADR-025) ·
`docs/learnings.md` · `docs/backlog/`. Business/vault → `/graft`.
