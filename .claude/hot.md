---
type: meta
title: "Hot — cleanmuzik"
updated: 2026-07-21
tags:
  - meta
  - hot-cache
status: evergreen
---
# Hot — cleanmuzik (personal YouTube → Jellyfin music tool)

> This repo's own working-memory board — session continuity, loaded at session start via `/hot`.
> A cache, not a journal: rewritten each save, never appended to. Durable knowledge lives in this
> repo's stores (`docs/r1/adr.md` · `docs/learnings.md` · `docs/r1/tickets.md` · `docs/backlog/` ·
> git); business/vault learnings go to the garden via `/graft`.

## What this repo is

CleanMuzik — personal YouTube → Jellyfin music tool. Purpose, stack, constraints and read-order
are in `CLAUDE.md`; scope in `cleanmuzik-prd.md`. Not restated here.

## Current State (2026-07-21)

- **On `main`, clean tree** (bar this board + the T-022 close in `tickets.md`, both about to commit).
- **T-022 closed won't-change.** Measured (`scratchpad/t022_measure.py`, 3 live tracks): the
  yt-dlp "no JS runtime → some formats may be missing" warning is a false alarm for audio — the
  dropped `web_safari` client adds only *video* formats; the bestaudio pick is identical with/without
  node. One-line re-enable recorded in the ticket for the day YouTube drops JSless audio.
- **R1 at its shipping line.** Remaining: **T-020 / T-027** — neither blocked.

## Next session — the last two (neither blocked)

- **T-027** (back-end): prove whether `noplaylist=True` makes a playlist-shaped `extract_info`
  result unreachable → close with the demonstration; else guard it. Reproduce-first.
- **T-020** (front-end): amend spec §6 to add `path`+`tags` to the `GET /api/jobs/{id}` snapshot,
  build the stream-reattach story, verify stream-offline (Playwright MCP can emulate offline).

## Notes for later (not blocking)

- **Reload loses all cards.** `App.tsx` holds the job list in component state and doesn't restore
  it across a browser reload, so any "survives reload" work is latent until a *job-restore-on-reload*
  capability exists (bites T-026's finding-#0; server fix + unit test already cover the mechanism).

## Verifying

- Owner's real servers: `:8137` (uvicorn, real library — **do NOT POST jobs to it**) + `:5173`.
- Browser `/verify` works here (Playwright MCP over an isolated backend). Rebuild the throwaway
  harness from the T-026/T-029 notes if needed. Hazard: WSL `/mnt/c` Vite serves a **stale bundle** —
  start with `--force` (`learnings.md` 2026-07-21).

## Recent sessions (rolling — last 2–3)

### 2026-07-21 — T-022 closed won't-change (measurement)
- Read yt-dlp's client-set logic, measured audio inventory JSless vs node across 3 tracks: identical.
  No code change; ticket records the finding + the one-line re-enable path.

### 2026-07-21 (pm) — T-026 built + verified + landed; post-review re-run closed clean
- Album/playlist card note (decision c), allowlist, browser-verified on isolated `:8100`. Deferred
  high-effort re-review ran → two findings, both adjudicated non-defects, no code change.

## Where the rest of the context lives

- **Durable stores:** `docs/r1/adr.md` · `docs/learnings.md` · `docs/r1/tickets.md` ·
  `docs/backlog/` · `docs/r1/spec.md` · `docs/r1/architecture.md` · `cleanmuzik-prd.md` · git.
  Read order in `CLAUDE.md`.
- **Business/vault context** — the garden, via `/garden`.
