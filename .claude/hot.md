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

- **On `main`, HEAD `d73d1ba`, pushed.** Tree clean. Suites green: **server 432, client 65**.
- **R1.1 is SHIPPED (2026-08-05).** All nine §8 acceptance items met with receipts
  (`docs/r1.1/spec.md` §8); roadmap flipped `in-build` → `shipped`. Closes R1's §7 spec-vs-build gap.
  T-101/102/103/104/105/106 all done + verified. The last item (duplicate-from-inbox) was
  owner-verified in-browser today via a real Jay-Z "My 1st Song" Replace.
- **No release in build.** R2 is next and now **unblocked**.

## ⟹ NEXT — R2 (specing), when the owner starts it

- **R2 = playlists + migrate/clean the existing library.** Migrate is a firehose into the durable
  review queue R1.1 just made real. First step: write `docs/r2/spec.md`, pulling relevant
  `docs/backlog/` items in as it specs (`git mv` from `docs/backlog/`). Not started — owner's call.

## Also open (backlog — triage into R2 as it specs)

- **T-037** (artist-string mojibake — `JAY‑Z` → `JAŸ-Z`): **diagnosed today** as a `Y→Ÿ` encoding
  mangle on the matched-metadata path; recurred on a real Replace (split `Jay-Z/` 3 ways, orphaned a
  `.lrc`). Library **manually standardized** (tag+file+beets-DB), but the **pipeline fix still needs an
  ADR** — next affected download re-splits. Higher priority than "cosmetic".
- **T-035** (Shazam tier — GO, ADR-019, build ticket to write), **T-039** (inbox loading indicator),
  **T-041** (signal-glow pointermove reflow), **T-042** (loudness normalization via ReplayGain tags —
  delegated to Jellyfin for now). **T-040 CLOSED** (was already fixed by `8ba2c2f`).

## Verifying

- Run from `~/github/cleanmuzik` (ext4), never `/mnt/c`. Isolated pipeline `/verify` recipe:
  `.claude/skills/verify/SKILL.md` (kill the isolated backend by PID — `pkill -f run_isolated`
  self-matches the shell). Dev servers run: `uvicorn :8137` (--reload, live DB) + Vite `:5173`.
  Playwright is the **MCP** server; shots → gitignored `.playwright-mcp/`.

## Recent sessions (rolling — last 2–3)

- **2026-08-05 (pm)** — **Shipped R1.1.** Verified T-106 end-to-end; a Fable plan caught a stale
  T-102 `todo` (nearly rebuilt shipped code); re-verified & closed T-040; owner browser-verified the
  duplicate-from-inbox item (real Jay-Z Replace); standardized the Jay-Z library split + diagnosed
  T-037; ticked §8, flipped roadmap → shipped. Filed T-042 + two stale-record learnings.
- **2026-08-05 (am)** — T-105 console reskin close-out → DONE (high-effort review, ADR-018 amended,
  merged `cb66c80`).
- **2026-08-04 (pm)** — T-105 full console redesign (`11b6302`): reskin found templated, redesigned
  with taste-skill/Fable.

## Where the rest of the context lives

`docs/roadmap.md` · `docs/r1.1/` (shipped) · `docs/r1/adr.md` · `docs/learnings.md` · `docs/backlog/` ·
git. Business/vault → `/garden`.
