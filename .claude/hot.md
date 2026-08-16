---
type: meta
title: "Hot — cleanmuzik"
updated: 2026-08-16
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

## Current State (2026-08-16)

- **On `main`, pushed.** R2 (Playlists) `in-build`.
- **T-310 design gate BUILT + owner-APPROVED** (2026-08-16). Ten flat scenario screens —
  the aggregate batch card (01–06) + the acquire dial (D1–D4) — in the shipped console skin.
  Artifact: **`docs/r2/design/t310-batch-view.html`** (also published privately to claude.ai).
  This is the *gate* (ADR-016, ahead of code); **T-310 component code is not built** (Phase E).
- **ADR-029 filed** — acquire intent is **explicit** (an optional `intent` field on `POST /api/jobs`),
  never inferred from URL shape. Control = a round **detented dial**: Single (default) / Playlist /
  Multi·soon. **Owner removed the council's inline confirm** — the dial *is* the intent: a
  `watch?v=X&list=PL…` on Single lands just the song + a quiet note, no prompt. Authored via a
  5-agent council.
- **Nothing in flight.**

## ⟹ NEXT

1. **Phase B backend opens — T-302** (accept + expand a playlist URL → N track-jobs), now also carrying
   ADR-029's **optional `intent` field** (absent = R1 shape inference byte-for-byte). Then the seam order
   **T-304 → T-303** (dedup's skip path appends via T-304 — not parallel).
2. **Phase D T-308** (implements ADR-028; BOTH `_accept` AND `ResolveSession.choose_item` route through the
   one `canonicalize_credit` helper) — `git mv docs/backlog/T-037.md docs/r2/` when starting.
3. **T-310 component code** (the batch card + dial Single/Playlist, Multi inert) is **Phase E** — after the
   B/C/D behaviours exist to render.

## Recent sessions (rolling — last 2–3)

- **2026-08-16 (this session)** — Built the **T-310 design gate** (10 screens), owner approved. Owner
  raised the paste-intent ambiguity (song+list silently grabs one song) → spawned a **5-agent council** →
  **ADR-029** (the acquire dial + explicit intent). Owner steered two things: a round detented dial (not a
  spin-pot), and **no inline confirm** (the dial is the intent). Filed backlog **T-045** (theme switcher —
  Dark/Light/System, default Dark; owner endorsed the ADR-018 dark skin) + **T-046** (the Multi build, the
  deferred half of ADR-029).
- **2026-08-15** — **T-301 done**: **ADR-028** (surgical artist-credit normalisation) via a 5-agent
  council. Built + shipped **T-300** (batch/backfill data model + **ADR-027**). Both Phase A gates settled.

## Where the rest of the context lives

`docs/roadmap.md` (R2 `in-build`) · `docs/r2/spec.md` + `spec.html` + **`tickets.md`** (T-300/301 done) ·
`docs/r2/design/t310-batch-view.html` (the gate) · `docs/r1/adr.md` (**ADR-029 last filed**) ·
`docs/learnings.md` · `docs/workflow.md` · `docs/backlog/` (T-037 → git-mv to `docs/r2/` when T-308 starts;
T-045 theme switcher, T-046 Multi build). Business → `/graft`.
