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

- **On `main`, clean** through `8e075cd` (docs commit for T-017 pending). Server suite **312 green**,
  client **20 green**.
- **T-017 is DONE** — browser receipt discharged this session (all "Done when" clauses observed
  live: weak-match render/accept/reject, duplicate keep/replace/keep_both, no reconnect-loop,
  restart re-hydration). Full receipt in `tickets.md`.
- Ledger: **T-016, T-017, T-028 done**; **T-024 built** (owes only its **row 7** browser receipt —
  a collaboration `feat.` landing, *not* yet run). **T-029 drafted**. Open = T-019, T-020,
  T-021→T-027, T-029, + T-024 row 7.

## NEXT

1. **T-024 row 7** — the last outstanding browser receipt: a collaboration lands with the featured
   artist baked into the artist field (`Nines feat. …`). Reuse this session's harness (below);
   needs a real collab-song download (mind the YouTube 403 rate-limit from repeated pulls).
2. **T-019** — the §7 acceptance pass; unblocked now that T-017 is verified.
3. **T-029** — back-end: a failed resume sets job=`error` while the row stays `pending`, orphaning
   the review. Verifiable over HTTP, no browser.

## Recent sessions (rolling — last 2–3)

### 2026-07-19 (d) — T-017 browser-verified → DONE
- Built an **isolated verification harness** and drove the panel live in Playwright's own Firefox
  (no clash with the owner's Chrome): temp `DB_PATH` + patched `LIBRARY_DIRECTORY` + blanked
  Jellyfin key on `:8100`, throwaway vite on `:5175`. Real library untouched (8 files throughout).
- Fixtures were **real parks, not seeded rows** — there is no queue view to surface a seeded row.
  Weak match: a sped-up upload parks with 5 clustered candidates. Duplicate: downgrade a landed
  320 copy to 192k in the sandbox, re-download → parks as duplicate.
- Two corrections filed to `learnings.md`: **MusicBrainz is reachable here** (T-013's "can't reach
  MB" was an inherited wall — so the harness ran fully real, no stubs).
- Left running for poking: `:8100` API, `:5175` client. Untracked throwaways to clean:
  `client/vite.verify.config.ts`, `client/.playwright-mcp/`, root `t017-*.jpeg`, scratchpad.

### 2026-07-19 (c) — T-017 built, reviewed, landed
- Review panel shipped (weak-match pick/reject + duplicate keep/replace/both), `rec` on the SSE
  event, narrow `GET /api/reviews/{id}` for panel re-hydration. High-effort `/code-review`: 5
  findings fixed, finding 2 → **T-029**. Committed `0e41956` + `0a4816c`, pushed.

## Where the rest of the context lives

- **Durable stores:** `docs/r1/adr.md` · `docs/learnings.md` · `docs/r1/tickets.md` · `docs/r1/spec.md`
  · `docs/r1/architecture.md` · `cleanmuzik-prd.md` · git. Read order in `CLAUDE.md`.
- **Business/vault context** — the garden, via `/garden`.
