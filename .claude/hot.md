---
type: meta
title: "Hot — cleanmuzik"
updated: 2026-07-29
tags:
  - meta
  - hot-cache
status: evergreen
---
# Hot — cleanmuzik (personal YouTube → Jellyfin music tool)

> This repo's own working-memory board — session continuity, loaded at session start via `/hot`.
> A cache, not a journal: rewritten each save, never appended. Durable knowledge lives in this repo's
> stores (`docs/r1/adr.md` · `docs/learnings.md` · `docs/r1.1/` · `docs/backlog/` · git); business/vault
> learnings go to the garden via `/graft`.

## What this repo is

CleanMuzik — personal YouTube → Jellyfin music tool. Purpose, stack, constraints and read-order are in
`CLAUDE.md`; scope in `cleanmuzik-prd.md`. Not restated here.

## Current State (2026-07-29)

- **`main` clean and in sync with origin** at `a8c1e39` — everything from 2026-07-29 is pushed. No
  code changed today; the session produced ADR-020, five learnings, T-037, and a charset fix.
- **Both servers up**: `:8137` backend, `:5173` client. **Serve `docs/**/design/*.html` over HTTP for any
  owner review** — an open from the OneDrive tree truncated the T-103 screens silently (learnings
  2026-07-29). `cd docs/r1.1/design && python3 -m http.server 8901`.
- **Queue is 2 reviews**: Frank Ocean *Strawberry Swing* and Nines *Outro (Official Audio)* (added
  today, 5 wrong candidates). Both audio present. Both are now T-103 fixtures with known-correct MBIDs.
- **Library is 9 tracks** — Jay-Z *Wishing on a Star* landed today via auto-tag (323 kbps, art
  embedded).

## ⟹ LIVE THREAD — build T-103

**Design signed off 2026-07-29, ratified as ADR-020. T-103 is ready to build and is the critical path.**
Start with ADR-020's binding consequence 1: relax `_validate_weak_match` (`reviews.py:168`), which today
refuses any recording that isn't already a candidate — the single thing making re-search impossible. The
landing machinery it calls (`resolve_import` / `_forced_match`) already lands an arbitrary recording.

**Verify T-103 and T-106 together** — one park→re-search→resolve→land run closes both gates. Fixtures are
already in the queue with known-correct MBIDs (Frank Ocean `908e389b…`, Nines *Outro* `f5d1bcfb…`).

## Also open (not the live thread)

- **T-106 is BUILT, not done** — reboot half proven on the real machine today; resolve half folded into
  T-103's `/verify` by owner decision. Full reasoning on its status line in `docs/r1.1/tickets.md`.
- **T-102** then **T-105** (reskin, last). Do not fan out T-102 ∥ T-103 — overlapping client files.
- **`docs/backlog/T-037.md` — filed today, untriaged.** Split artist folders + missing genre tag.
- **LLM-as-disambiguator tier** — raised and deliberately deferred today; reasoning filed in
  `docs/backlog/T-035.md`. Sequenced after T-103 and after the Shazam tier.

## Verifying

- Isolate `DB_PATH` **and** monkeypatch `beets_engine.LIBRARY_DIRECTORY` (a hardcoded constant), or a
  resolve lands in the real library. The suite already does this.
- A yt-dlp `403` at the download stage may be **transient** — retry once before diagnosing.
- `--reload` did not fire on a `touch` under `/mnt/c`. Restart deliberately.

## Where the rest of the context lives

`docs/roadmap.md` · `docs/r1.1/` (active) · `docs/r1/adr.md` (**ADR-019** newest) · `docs/learnings.md`
· `docs/backlog/` · `docs/r1.1/design/*.html` · git (tag `r1-single-song`). Business/vault → `/garden`.
