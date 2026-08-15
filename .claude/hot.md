---
type: meta
title: "Hot — cleanmuzik"
updated: 2026-08-14
tags:
  - meta
  - hot-cache
status: evergreen
---
# Hot — cleanmuzik (personal YouTube → Jellyfin music tool)

> This repo's own working-memory board — session continuity, loaded at session start via `/hot`.
> A cache, not a journal: rewritten each save, never appended. Durable knowledge lives in this repo's
> stores (`docs/roadmap.md` · `docs/r1/adr.md` · `docs/learnings.md` · `docs/r2/` · git); business
> learnings go to the garden via `/graft`.

## What this repo is

CleanMuzik — personal YouTube → Jellyfin music tool. Purpose, stack, constraints, read-order in
`CLAUDE.md`; scope in `cleanmuzik-prd.md`. Not restated here.

## Current State (2026-08-14)

- **On `main`. R2 (Playlists) is now `in-build`** (flipped this session in `docs/roadmap.md`). R1 +
  R1.1 + R1.5 all SHIPPED.
- **R2 tickets are ready to build:** `docs/r2/tickets.md` = 13 build-order tickets **T-300–T-312**,
  council-reviewed last session (spec `docs/r2/spec.md` + `spec.html`).
- **Nothing in flight** — no ticket started yet. Next action is T-300.

## ⟹ NEXT

1. **Build T-300 + T-301 first** (Phase A) — they write **ADR-027** (batch/backfill data model + the
   six seams) and **ADR-028** (T-037 normalisation). Both gate the design gate (T-310).
2. **Two owner decisions parked in ADR-027**, to settle while building T-300: the Jellyfin resolve
   timeout/retry budget, and create-playlist-at-`batch.queued` vs backfill-create-if-missing (T-300
   recommends a default for each).

## Recent sessions (rolling — last 2–3)

- **2026-08-14 (this session)** — **Flipped R2 → `in-build`** (roadmap status line + header + two
  contradicting sentences reconciled). Fixed the stale **"Signal Path"** label in `docs/r2/spec.md`
  → canonical **console skin** (ADR-018; Signal Path is the superseded 23-Jul predecessor).
- **2026-08-14 (earlier)** — Generated **R2 tickets** (T-300–T-312) from the signed-off spec; built
  `spec.html`; ran a 4-agent review council; folded all findings (2 caught the T-300 migration blocker).
- **2026-08-14 (earlier)** — R1.5 retro: filed spike lesson + **ADR-026**; resequenced roadmap for
  the car north-star (R2 → R2.5 → R3 → R1.6).

## Where the rest of the context lives

`docs/roadmap.md` (R2 `in-build`) · `docs/r2/spec.md` + `spec.html` + **`tickets.md`** (T-300–T-312) ·
`docs/r1/adr.md` (ADR-026 last filed; ADR-027/028 are R2's, unwritten) · `docs/learnings.md` ·
`docs/workflow.md` · `docs/backlog/` (incl. T-037, T-208/214/215). Business/vault → `/graft`.
