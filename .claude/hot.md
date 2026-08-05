---
type: meta
title: "Hot — cleanmuzik"
updated: 2026-08-05
tags:
  - meta
  - hot-cache
status: evergreen
---
# Hot — cleanmuzik (personal YouTube → Jellyfin music tool)

> This repo's own working-memory board — session continuity, loaded at session start via `/hot`.
> A cache, not a journal: rewritten each save, never appended. Durable knowledge lives in this repo's
> stores (`docs/r1/adr.md` · `docs/learnings.md` · `docs/r1.1/` · `docs/backlog/` · git);
> business/vault learnings go to the garden via `/graft`.

## What this repo is

CleanMuzik — personal YouTube → Jellyfin music tool. Purpose, stack, constraints and read-order are in
`CLAUDE.md`; scope in `cleanmuzik-prd.md`. Not restated here.

## Current State (2026-08-05)

- **On `main`, HEAD `1dd3069`** (about to push). Tree clean.
- **T-106 is DONE + VERIFIED** — durable parked-audio staging. Last gate (park → real process
  restart → route-resolve → landed MP3) driven end-to-end; full receipt in `docs/r1.1/tickets.md`
  T-106, verify recipe at `.claude/skills/verify/SKILL.md`. **T-103 also DONE** (both exits) — the
  unblock that let T-106's route-resolve be shown.
- Real backend `:8137` + real library **untouched** by the verify (isolated temp throughout). The
  **owner cleared the review area**, so the real queue is now **empty**. Library in `~/cleanmuzik-data`.

## ⟹ NEXT — R1.1 close-out (one gate left)

- **§8 acceptance close-out** — walk the R1.1 spec's checklist (`docs/r1.1/spec.md` §8) against the
  built app and tick each item. With T-101/102/103/104/105/106 done, this is what tips **R1.1 itself**
  toward done. (§8 items 1 + 8, the durable-review + reboot promises, are now backed by the T-106
  verify above.)

## Also open (not the live thread)

- `docs/backlog/` — **T-037** (JAŸ-Z artist-string normalisation — needs an ADR; owner's LLM-sweep idea
  recorded as a candidate for the one-time half), **T-039** (inbox loading indicator), **T-040**
  (keep_untagged resolve fails), **T-041** (signal-glow pointermove reflow — from T-105 review),
  **T-035** (Shazam tier).

## Verifying

- **Run everything from `~/github/cleanmuzik` (ext4), never `/mnt/c`** — 9p times out test workers.
- Pipeline `/verify` without polluting the real library: see `.claude/skills/verify/SKILL.md`
  (isolated `uvicorn` on `:8138`, temp `DB_PATH`, `LIBRARY_DIRECTORY` patched in both modules).
- Dev servers run: `uvicorn :8137` (--reload) + Vite `:5173`. Server-module edits re-run the lifespan
  against the **live** DB (CLAUDE.md); client-only edits are safe.
- Playwright is the **MCP** server (persistent browser), not the CLI. Shots → gitignored `.playwright-mcp/`.

## Recent sessions (rolling — last 2–3)

- **2026-08-05 (pm)** — T-106 end-to-end `/verify` → DONE. Isolated `uvicorn`, real park → kill+
  relaunch (orphan swept, file survived) → route re-search + resolve → landed 320 kbps + art. Filed
  the receipt + a `verify` repo skill. Owner cleared the real review queue.
- **2026-08-05 (am)** — T-105 close-out → DONE. High-effort `/code-review` (4 findings): fixed the
  fabricated dup-swatch (ADR-010 trap), channel-name-as-artist inbox line, dropped expanded-row
  highlight; deferred a pointermove reflow to T-041. Amended ADR-018. Merged + pushed.
- **2026-08-04 (pm)** — T-105 full console redesign (`11b6302`): reskin ported the gate, owner found it
  templated, redesigned with taste-skill/Fable — console rail, centred crest, EQ beat bars.

## Where the rest of the context lives

`docs/roadmap.md` · `docs/r1.1/` (active) · `docs/r1/adr.md` · `docs/learnings.md` · `docs/backlog/` ·
git. Business/vault → `/garden`.
