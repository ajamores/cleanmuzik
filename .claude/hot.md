---
type: meta
title: "Hot — cleanmuzik"
updated: 2026-08-09
tags:
  - meta
  - hot-cache
status: evergreen
---
# Hot — cleanmuzik (personal YouTube → Jellyfin music tool)

> This repo's own working-memory board — session continuity, loaded at session start via `/hot`.
> A cache, not a journal: rewritten each save, never appended. Durable knowledge lives in this repo's
> stores (`docs/r1/adr.md` · `docs/learnings.md` · `docs/workflow.md` · `docs/r2/spec.md` ·
> `docs/research/` · `docs/backlog/` · git); business/vault learnings go to the garden via `/graft`.

## What this repo is

CleanMuzik — personal YouTube → Jellyfin music tool. Purpose, stack, constraints and read-order are in
`CLAUDE.md`; scope in `cleanmuzik-prd.md`. Not restated here.

## Current State (2026-08-09)

- **On `main`, tree clean except untracked `docs/r2/` + `docs/research/`.** Suites green: **server 432,
  client 65** (no code this session — specing + research).
- **R1 + R1.1 SHIPPED.** **R2 = playlists + T-037**, scope locked; `docs/r2/spec.md` written
  (`ready-for-agent`). Migrate/clean split OUT → R2.5.
- **NEW strategic thread: rethink the identify/tag engine.** Triggered by a live **confidently-wrong
  auto-tag** (Pa Salieu "Frontline" landed as Vanessa Bling — AcoustID fingerprint collision, nothing
  cross-checked the YouTube title). Research filed: **`docs/research/llm-reconciler-vs-beets.md`**.

## ⟹ NEXT — two live tracks of work

**A. Match-quality / engine rethink (decide with a spike, not vibes).** Research verdict: the real fix
is a **cross-check gate** (divert to review when the DB match diverges from the YouTube title) — needs
**no** new dependency; an LLM is the *nice* implementation, not the core. Owner wants bigger: Shazam-first
identity + LLM reconciler + self-fetch art/lyrics, possibly dropping AcoustID/MB/beets-matching + a
bulk-download-then-tag phase w/ parallel workers. **Open decisions:** does this reopen **ADR-001**
(sequential) and **ADR-005** (beets-is-engine)? Does it change R2's foundation → pause playlists? →
**run the research's 5-item spike for real accuracy numbers on the owner's corpus first.** File a
reconciler-gate backlog ticket (holds the Frontline evidence).

**B. R2 build — blocked on two ADRs before the design gate** (full detail in `docs/r2/spec.md`):
batch/backfill data model (`playlists` + `job.playlist_id` + backfill chain + one-SSE-stream); T-037
write-path normalisation. Then `git mv` T-037 → R2 tickets · record migrate=R2.5 in roadmap ·
generate `docs/r2/tickets.md` · commit.

## Live library messes (uncleaned)

- `Vanessa Bling & The Heatwave/Frontline.mp3` — mis-tagged (really Pa Salieu). Re-tag/re-acquire.
- Fresh **`JAŸ-Z/Roc Boys`** folder — T-037 recurred on a real download today. Re-consolidate.

## Also open (backlog — parked, NOT R2)

Per roadmap scope gate: **T-035** (Shazam tier — now central to thread A), **T-034** (query norm),
**T-042** (ReplayGain), **T-023/030/031/039/041**. T-037 is the only backlog item pulled into R2.

## Verifying

Run from `~/github/cleanmuzik` (ext4), never `/mnt/c`. Playbook + hazards: `docs/workflow.md` + `/verify`
skill. Dev servers: `uvicorn :8137` + Vite `:5173`; Playwright is the MCP server.

## Recent sessions (rolling — last 2–3)

- **2026-08-09** — Specced R2 (grilling → `docs/r2/spec.md`; batch view = "Hybrid" aggregate card, one
  SSE stream). Then a live confidently-wrong auto-tag opened the engine-rethink thread; ran research
  (`docs/research/llm-reconciler-vs-beets.md`) — verdict: cross-check gate is the load-bearing fix,
  Shazam/LLM are enhancements, spike before committing.
- **2026-08-06** — Retro R1→R1.1: DoD step 6; slimmed CLAUDE.md ~46%; fixed stale claims (`498e5d6`).
- **2026-08-05 (pm)** — Shipped R1.1; diagnosed T-037's encoding mangle.

## Where the rest of the context lives

`docs/roadmap.md` · `docs/r2/spec.md` · `docs/research/` · `docs/workflow.md` · `docs/r1.1/` ·
`docs/r1/adr.md` · `docs/learnings.md` · `docs/backlog/` · git. Business/vault → `/garden`.
