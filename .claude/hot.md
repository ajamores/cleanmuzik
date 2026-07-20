---
type: meta
title: "Hot — cleanmuzik"
updated: 2026-07-20
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

## Current State (2026-07-20)

- **On `main`, clean** through `0684eb9`. Server suite **312 green**, client **20 green** (no code
  changed this session — docs only).
- **T-024 is DONE** — row 7 discharged: ADR-012's first *real download* receipt. Jay-Z "Coming of
  Age (feat. Memphis Bleek)" landed as `JAŸ‐Z/…` with `TPE1='JAŸ‐Z'` (single primary artist),
  featured credit in the title, MP3 320 + art + lyrics. Full receipt in `tickets.md`.
- Ledger: **T-016, T-017, T-018, T-024, T-028 done** (T-001–T-018 all done + T-024 + T-028 = 20).
  Open = **T-019, T-020, T-021, T-022, T-023, T-025, T-026, T-027, T-029**.

## NEXT

1. **T-019** — the §7 end-to-end acceptance pass. Now fully unblocked (its deps T-016/T-017 done).
   Reuse the isolated harness below; it owns the whole §7 checklist.
2. **T-029** — back-end: a failed resume sets job=`error` while the row stays `pending`, orphaning
   the review. Verifiable over HTTP, no browser.
3. **T-026** — **needs an owner decision first** (option a/b/c in `tickets.md`), then code. Don't
   start building it without the call.

## Harness (still up — reuse, don't rebuild)

Isolated verify stack from the T-017/T-024 sessions is **still running and sound**: backend `:8100`
(prior-session launcher `verify_launcher.py`, temp `DB_PATH` + sandboxed `LIBRARY_DIRECTORY` +
blanked Jellyfin key → real library untouchable) and client `:5175` (`client/vite.verify.config.ts`,
proxies `/api`→`:8100`). Real dev stack also up: `:8137` + `:5173`. Untracked throwaways to clean
when done with browser tickets: `client/vite.verify.config.ts`, `.playwright-mcp/`, scratchpad.

## Recent sessions (rolling — last 2–3)

### 2026-07-20 — T-024 row 7 verified → DONE
- Drove a real collab download over HTTP against the isolated `:8100` harness (already running from
  the prior session; read `verify_launcher.py` to confirm isolation before trusting it). `ftintitle`
  pulled "Memphis Bleek" into the title, left artist as single `JAŸ‐Z`. Flipped T-024 → done.
- Two non-T-024 observations on the file, both filed: genre `Music` (T-018 `lastgenre` follow-up)
  and year `2026` — current year, not a reissue's — logged to T-025 as a second data point.

### 2026-07-19 (d) — T-017 browser-verified → DONE
- Built the isolated harness (above) and drove the review panel live in Playwright's Firefox: weak
  match, duplicate keep/replace/both, no reconnect-loop, restart re-hydration. Real library untouched.
- Filed to `learnings.md`: **MusicBrainz is reachable here** (T-013's "can't reach MB" was inherited).

## Where the rest of the context lives

- **Durable stores:** `docs/r1/adr.md` · `docs/learnings.md` · `docs/r1/tickets.md` · `docs/r1/spec.md`
  · `docs/r1/architecture.md` · `cleanmuzik-prd.md` · git. Read order in `CLAUDE.md`.
- **Business/vault context** — the garden, via `/garden`.
