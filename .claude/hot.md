---
type: meta
title: "Hot — cleanmuzik"
updated: 2026-08-06
tags:
  - meta
  - hot-cache
status: evergreen
---
# Hot — cleanmuzik (personal YouTube → Jellyfin music tool)

> This repo's own working-memory board — session continuity, loaded at session start via `/hot`.
> A cache, not a journal: rewritten each save, never appended. Durable knowledge lives in this repo's
> stores (`docs/r1/adr.md` · `docs/learnings.md` · `docs/workflow.md` · `docs/r1.1/` · `docs/backlog/` ·
> git); business/vault learnings go to the garden via `/graft`.

## What this repo is

CleanMuzik — personal YouTube → Jellyfin music tool. Purpose, stack, constraints and read-order are in
`CLAUDE.md`; scope in `cleanmuzik-prd.md`. Not restated here.

## Current State (2026-08-06)

- **On `main`, HEAD `498e5d6`, pushed.** Tree clean. Suites green: **server 432, client 65** (unchanged —
  today was docs-only).
- **R1.1 SHIPPED (2026-08-05).** No release in build. **R2 is next and unblocked.**
- **CLAUDE.md was slimmed + de-staled today** (`498e5d6`): ~2340 → ~1250 always-loaded tokens via
  progressive disclosure. On-demand build-process detail moved to new **`docs/workflow.md`** (DoD
  rationale + fan-out mechanics + verify playbook); the "Current state" section had gone stale (called
  the shipped app "scaffold") and was corrected. **DoD gained step 6 (Ledger sync).**

## ⟹ NEXT — R2 (specing), when the owner starts it

- **R2 = playlists + migrate/clean the existing library.** Migrate is a firehose into the durable review
  queue R1.1 made real. First step: write `docs/r2/spec.md`, pulling relevant `docs/backlog/` items in
  as it specs (`git mv` from `docs/backlog/`). Not started — owner's call.

## Also open (backlog — triage into R2 as it specs)

- **T-037** (artist-string mojibake — `JAY‑Z` → `JAŸ-Z`): diagnosed as a `Y→Ÿ` encoding mangle on the
  matched-metadata path; recurred on a real Replace (split `Jay-Z/` 3 ways, orphaned a `.lrc`). Library
  manually standardized, but the **pipeline fix still needs an ADR** — next affected download re-splits.
- **T-035** (Shazam tier — GO, ADR-019, build ticket to write), **T-039** (inbox loading indicator),
  **T-041** (signal-glow pointermove reflow), **T-042** (loudness normalization via ReplayGain tags).

## Verifying

- Run from `~/github/cleanmuzik` (ext4), never `/mnt/c`. Full playbook + hazards: `docs/workflow.md` +
  the `/verify` skill. Dev servers: `uvicorn :8137` + Vite `:5173`; Playwright is the MCP server.

## Recent sessions (rolling — last 2–3)

- **2026-08-06** — Retro on R1→R1.1: the DoD additions (acceptance check, integration) held; found a new
  failure class (stale status-ledger) → wrote **DoD step 6**. Then noticed CLAUDE.md was bloated *and*
  stale; two audit agents confirmed; **slimmed it ~46% via progressive disclosure + fixed the stale
  "scaffold" claims**, moved detail to `docs/workflow.md`. Set the R3+ always-on host = owner's 2010
  MacBook on Mint (no purchase). All in `498e5d6`.
- **2026-08-05 (pm)** — **Shipped R1.1.** Verified T-106 end-to-end; owner browser-verified
  duplicate-from-inbox; standardized the Jay-Z split + diagnosed T-037; ticked §8, flipped roadmap →
  shipped. Filed T-042 + two stale-record learnings.
- **2026-08-05 (am)** — T-105 console reskin close-out → DONE (ADR-018 amended, merged `cb66c80`).

## Where the rest of the context lives

`docs/roadmap.md` · `docs/workflow.md` (build process) · `docs/r1.1/` (shipped) · `docs/r1/adr.md` ·
`docs/learnings.md` · `docs/backlog/` · git. Business/vault → `/garden`.
