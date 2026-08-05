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

- **On `main`, pushed to origin (`cb66c80`).** No branch in flight; tree clean.
- **T-105 is DONE** — console reskin merged and integrated. Client 65/65, server 432 green on `main`.
  The reskin's three UI-truth review fixes (`819f22c`) and the **ADR-018 amendment** (`01e1409`, console
  supersedes Signal Path; EQ bars reverse "no spectrum bars") are all landed. All fixes verified
  in-browser, including the duplicate panel with no fabricated cover swatch.
- Queue (real backend `:8137`): **1 parked review** — the `Coming Of Age` duplicate left over from the
  #1 verification (resolve or leave, owner's call). Library in `~/cleanmuzik-data`.

## ⟹ NEXT — R1.1 close-out

1. **T-106** — end-to-end `/verify` of durable parked-audio staging (was blocked on T-103, now unblocked).
   Already INTEGRATED on `main` (`eb5865e`); the last gate is the observable `/verify`, not more code.
2. **§8 acceptance close-out** — walk the R1.1 spec's checklist (`docs/r1.1/spec.md` §8) against the built
   app; this is what tips **R1.1 itself** toward done.

## Also open (not the live thread)

- `docs/backlog/` — **T-037** (JAŸ-Z artist-string normalisation — needs an ADR; owner's LLM-sweep idea
  now recorded as a candidate for the one-time half), **T-039** (inbox loading indicator), **T-040**
  (keep_untagged resolve fails), **T-041** (signal-glow pointermove reflow — from T-105 review),
  **T-035** (Shazam tier).

## Verifying

- **Run everything from `~/github/cleanmuzik` (ext4), never `/mnt/c`** — 9p times out test workers.
- Dev servers already run: `uvicorn :8137` (--reload) + Vite `:5173`. Server-module edits re-run the
  lifespan against the **live** DB (CLAUDE.md); client-only edits are safe.
- Playwright is the **MCP** server (persistent browser), not the CLI. Shots → gitignored `.playwright-mcp/`.

## Recent sessions (rolling — last 2–3)

- **2026-08-05** — T-105 close-out → DONE. High-effort `/code-review` (workflow, 4 findings): fixed the
  fabricated dup-swatch (ADR-010 trap), the channel-name-as-artist inbox line, and the dropped
  expanded-row highlight; deferred a pointermove reflow to T-041. Amended ADR-018 + swept spec/tickets/
  roadmap. Verified all three in-browser (incl. a real JAY-Z duplicate). Merged + pushed.
- **2026-08-04 (pm)** — T-105 full console redesign (`11b6302`): reskin ported the gate, owner found it
  templated, redesigned with taste-skill/Fable — console rail, centred crest, EQ beat bars.
- **2026-08-04 (am)** — Bug fix `8ba2c2f`: `FwKp-HkKUMA` showed Done but never landed. → ADR-009
  amendment, learnings entry.

## Where the rest of the context lives

`docs/roadmap.md` · `docs/r1.1/` (active) · `docs/r1/adr.md` · `docs/learnings.md` · `docs/backlog/` ·
git. Business/vault → `/garden`.
