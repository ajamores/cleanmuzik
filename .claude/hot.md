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

- **On `main`, HEAD `31ab7bf`, pushed.** Tree clean. Suites green here: **server 432, client 65**.
- **R1.1 has no unbuilt tickets.** T-101/102/103/104/105/106 all done. A Fable planning pass caught
  that **T-102's `todo` line was stale** (built `58c0fea`, owner-verified `027a5db` on 08-02) — nearly
  rebuilt shipped code; corrected, learning filed.
- **T-040 CLOSED** — keep_untagged re-park was already fixed by the 08-03 dup-stage defusal (`8ba2c2f`),
  never re-tested. Re-verified end-to-end (isolated): two keep-untagged lands in a row now succeed.
  All three no-candidate exits work → **§8 item 4 fully satisfied**.
- Real backend `:8137` + real library **untouched** (all verifies isolated to temp). Real queue empty.

## ⟹ NEXT — close R1.1 (§8: 8 of 9 items backed by receipts)

1. **The one open verify — duplicate-from-inbox (§8 item 3), in a browser.** Also closes T-105's last
   thread: the dup-panel art fix (#1, `819f22c`) is un-browser-verified. Plan: run the isolated backend
   on **`:8137`** (temp DB + library, Jellyfin off) so the untouched Vite proxy hits it → paste a track,
   land it, paste again → duplicate park → resolve from the inbox; confirm cover art shows **only on the
   owned side**. Needs a browser (Playwright MCP) + owner eyes. (Commandeers `:8137` briefly — restart
   the real dev server after.)
2. **Close-out** — tick all nine §8 boxes in `docs/r1.1/spec.md` with receipt pointers, flip R1.1 →
   **shipped** in `docs/roadmap.md`, update this board. Items 1/2/4/5/6/7(skin)/8/9 already backed.

## Also open (not the live thread)

- `docs/backlog/` — **T-037** (JAŸ-Z artist-string normalisation — needs an ADR), **T-039** (inbox
  loading indicator), **T-041** (signal-glow pointermove reflow), **T-042** (loudness normalization via
  ReplayGain tags — delegated to Jellyfin for now), **T-035** (Shazam tier).

## Verifying

- Run from `~/github/cleanmuzik` (ext4), never `/mnt/c`. Isolated pipeline `/verify` recipe:
  `.claude/skills/verify/SKILL.md` (kill the isolated backend by PID — `pkill -f run_isolated`
  self-matches the shell). Dev servers run: `uvicorn :8137` (--reload, live DB) + Vite `:5173`.
  Playwright is the **MCP** server; shots → gitignored `.playwright-mcp/`.

## Recent sessions (rolling — last 2–3)

- **2026-08-05 (pm)** — Closed R1.1 loose ends. T-106 verified end-to-end; corrected stale T-102/T-105
  status lines (Fable plan caught the T-102 near-rebuild); **re-verified T-040 → already fixed, closed**;
  filed T-042 (loudness). Two stale-record learnings filed. One verify left: duplicate-from-inbox.
- **2026-08-05 (am)** — T-105 close-out → DONE. High-effort `/code-review` (4 findings), ADR-018 amended,
  merged + pushed.
- **2026-08-04 (pm)** — T-105 full console redesign (`11b6302`): reskin found templated, redesigned with
  taste-skill/Fable — console rail, centred crest, EQ beat bars.

## Where the rest of the context lives

`docs/roadmap.md` · `docs/r1.1/` (active) · `docs/r1/adr.md` · `docs/learnings.md` · `docs/backlog/` ·
git. Business/vault → `/garden`.
