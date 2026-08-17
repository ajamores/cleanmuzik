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
- **T-302 done + shipped** (`daa65af`). `POST /api/jobs` now expands a curated playlist URL → N
  track-jobs (shared `playlist_id` + 1-based `position` + `youtube_video_id`); single-song URL
  unchanged (R1 byte-for-byte). Explicit `intent` (ADR-029) added; **`create_playlist` built in
  `jellyfin.py`** (degrades to NULL on absent/failed Jellyfin). Verified against a real 183-track
  playlist; 580 tests green.
- **ADR-027 gained a seam-3 addendum** (council-settled 2026-08-16, 4 lenses unanimous + owner):
  the Jellyfin **create** lives in T-302, not T-304; T-304 keeps only resolve/append/reconcile.
  Paired T-302/T-304 ticket edits filed.
- **Phase A done** (T-300 data model, T-301/ADR-028). **Nothing in flight.**

## ⟹ NEXT

1. **T-304 — the hard half of the Jellyfin seam** (ADR-027 seam 1): resolve a landed file → its
   Jellyfin item id (**poll Items-by-path 2s up to a 10s hard cap, then defer**, never block the
   sequential worker), append to the playlist, and reconcile a **pending append**
   (`playlist_members.jellyfin_item_id IS NULL`). `create_playlist` already exists (T-302); T-304
   consumes the stored `jellyfin_playlist_id`. **Push-vs-poll settled: poll** (ADR-027 seam 1
   resolved 2026-08-16 — Webhook plugin's `ItemAdded` is scheduled-task-batched + buggy, not push).
2. **Then T-303** (exact-video dedup: `EXISTS(job WHERE youtube_video_id=? AND status='done')`) —
   its skip path **appends via T-304**, so T-304 lands first (not parallel).
3. **Then T-305** (batch-scoped SSE) · **T-312** (durable batch state + reconnect).
4. **Phase D T-308** (ADR-028) can run alongside; `git mv docs/backlog/T-037.md docs/r2/` on start.

## Recent sessions (rolling — last 2–3)

- **2026-08-16 (this session)** — **Shipped T-302** (accept + expand + explicit intent + minimal
  `create_playlist`). Owner convened a **4-lens council** on the create/resolve ticket split →
  unanimous "create in T-302" → **ADR-027 seam-3 addendum**; owner settled the degrade-on-failure
  contract. `/code-review` surfaced 5 findings (4 fixed, 1 single-user race accepted-in-code).
- **2026-08-16 (earlier)** — Built the **T-310 design gate** (10 screens), owner-approved. Raised the
  paste-intent ambiguity → 5-agent council → **ADR-029** (acquire dial + explicit intent). Filed
  backlog **T-045** (theme switcher) + **T-046** (the Multi build).
- **2026-08-15** — **T-301 done** (**ADR-028** artist-credit normalisation, council). **T-300** shipped
  (batch data model + **ADR-027**).

## Where the rest of the context lives

`docs/roadmap.md` (R2 `in-build`) · `docs/r2/spec.md` + **`tickets.md`** (T-300/301/302 done) ·
`docs/r2/design/t310-batch-view.html` (the gate) · `docs/r1/adr.md` (**ADR-027 seam-3 addendum last
filed**; ADR-028/029) · `docs/learnings.md` · `docs/workflow.md` · `docs/backlog/` (T-037 → git-mv to
`docs/r2/` when T-308 starts; T-045 theme, T-046 Multi). Business → `/graft`.
