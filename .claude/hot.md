---
type: meta
title: "Hot — cleanmuzik"
updated: 2026-07-19
tags:
  - meta
  - hot-cache
status: evergreen
---
# Hot — cleanmuzik (personal YouTube → Jellyfin music tool)

> This repo's own working-memory board — session continuity, loaded at session start via `/hot`.
> A cache, not a journal: rewritten each save, never appended to. Durable knowledge lives in this
> repo's stores (`docs/r1/adr.md` · `docs/learnings.md` · `docs/r1/tickets.md` · git); business/vault
> learnings go to the garden via `/graft`.

## What this repo is

CleanMuzik — personal YouTube → Jellyfin music tool. Purpose, stack, constraints and read-order
are in `CLAUDE.md`; scope in `cleanmuzik-prd.md`. Not restated here.

## Current State (2026-07-19)

- **On `main`.** This session's commit lands `docs/r1/tickets.md` (T-019 receipts + new T-030).
  Server suite **312 green**, client **20 green** — no code changed, docs only.
- **T-019 (§7 pass) — verification effectively COMPLETE.** All ten §7 items observed (full receipts
  in `tickets.md`, session-2 block): #6's three duplicate branches driven live through real beets,
  #4/#7/#9/#10 this session, #5 owner-confirmed on Jellyfin 10.11.11, #1/#2/#3/#8 prior.
  **Only gate left to STAMP it done = #4's tag-quality defects:** genre reads `Music` (→ T-021/22/23),
  year is current-not-original (→ T-025 / ADR-011). T-019 just re-checks a landed file once those land.
- **T-030 filed** (minor, deferred): landed lyrics need a *second* Jellyfin "Scan All Libraries" —
  a race between the app's scan trigger and the `.lrc` write. Not a §7 gate.

## NEXT (owner picks next session)

1. **T-021 / T-022 / T-023 + T-025** — genre + year tag fixes. These gate T-019's final close and
   are the last substantive tag-correctness work.
2. **T-029** — failed resume sets job=`error` while the row stays `pending`, orphaning the review.
   Clean HTTP-verifiable back-end fix, no browser.
3. **T-026** — needs an owner decision (a/b/c in `tickets.md`) *before* any code.

## Harness (still up — reuse, don't rebuild)

Isolated stack from the T-017/T-019 sessions is running: backend **:8100** (`verify_launcher.py`,
temp `DB_PATH` + sandboxed `LIBRARY_DIRECTORY` + blanked Jellyfin key → real library untouchable),
verify client **:5175** (`client/vite.verify.config.ts`). Real dev stack also up: **:8137** +
**:5173**. Isolated Rick Astley entry now carries test residue (192k + a `(Verify KB Take)` 320k) —
harmless throwaway lib. Untracked throwaways to clean when done verifying: `client/vite.verify.config.ts`,
`.playwright-mcp/`. Full T-019 receipts: scratchpad `t019-verify-log.md`.

## Recent sessions (rolling — last 2–3)

### 2026-07-19 — T-019 §7 verify pass (near-closed)
- Drove every §7 item not needing a browser over HTTP vs :8100; owner confirmed #5 in Jellyfin.
- Proved all three duplicate branches live through real beets (built + reset single-copy fixtures
  to satisfy the strict-higher-bitrate park rule). Filed T-030 (lyrics 2nd-scan race).

### 2026-07-20 — T-024 row 7 verified → DONE
- Real collab download over HTTP: `ftintitle` folded "Memphis Bleek" into the title, artist stayed
  single `JAŸ‐Z`. ADR-012's first real-download receipt.

### 2026-07-19 (d) — T-017 browser-verified → DONE
- Review panel driven live in Firefox (weak match, keep/replace/both, restart re-hydration). Filed:
  MusicBrainz IS reachable here.

## Where the rest of the context lives

- **Durable stores:** `docs/r1/adr.md` · `docs/learnings.md` · `docs/r1/tickets.md` · `docs/r1/spec.md`
  · `docs/r1/architecture.md` · `cleanmuzik-prd.md` · git. Read order in `CLAUDE.md`.
- **Business/vault context** — the garden, via `/garden`.
