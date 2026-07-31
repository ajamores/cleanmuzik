---
type: meta
title: "Hot — cleanmuzik"
updated: 2026-07-30
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

## Current State (2026-07-30)

- **On branch `main`, working tree clean, pushed to origin.** All branches integrated.
- **T-103 slice A is DONE** — re-search exit built, browser-verified (2026-07-30 via Playwright),
  and merged to `main`. Suites: 421 server, 53 client.
- **T-038 is closed** — engine notes consolidated into `learnings.md` (`65a8ea9`).
- **T-106 is DONE** — the browser pass for T-103 doubles as T-106's last gate (park → re-search →
  resolve → land was driven live; staging survived across sessions).
- **Queue holds 2 fixtures**, both `pending` with audio on disk: Frank Ocean *Strawberry Swing* and
  Nines *Outro*. Library now has **11 tracks, 10 artists** (Nines Outro + Frank Ocean Strawberry
  Swing auto-tagged during the browser pass — both are now in AcoustID well enough to auto-tag).

## ⟹ NEXT: T-103 slice B, then T-102, then T-105

1. **T-103 slice B** (keep-untagged) — land a file with owner-supplied tags, no MB match. Entry
   point must change per the **ADR-020 amendment**: MusicBrainz text search almost never returns
   zero, so the gate can't be an empty result list. The real dead-end is "many results, all wrong."
2. **T-102** — lift the review lifecycle out of TrackCard into the inbox. Enables resolving from
   cold load (the Review buttons in the inbox are currently disabled).
3. **T-105** — Signal Path reskin (last). Skins the finished structure.

## Also open (not the live thread)

- `docs/backlog/` — **T-037** (tag-quality), **T-035** (Shazam tier — build ticket still unwritten).

## Verifying

- Isolate `DB_PATH` **and** patch `LIBRARY_DIRECTORY` in **both** `beets_engine` *and* `import_seam`
  (imported by name, so patching one is not enough), or a resolve lands in the real library.
- A yt-dlp `403` at download may be **transient** — retry once before diagnosing.
- **Restart Vite before browser-verifying** — the `.vite` cache does not always pick up branch
  changes. Clear `node_modules/.vite` and restart (confirmed 2026-07-30).

## Recent sessions (rolling — last 2–3)

- **2026-07-30 (this session)** — T-103 slice A browser pass driven via Playwright: re-search form,
  swap, candidate replacement, empty state, SSE through Vite proxy — all PASS. Vite cache trap hit
  and resolved (stale bundle served code without the re-search form). Merged to `main`, pushed.
  Two tracks auto-tagged incidentally (Nines Outro, Frank Ocean Strawberry Swing). T-038 closed
  earlier same day.
- **2026-07-30 (earlier)** — T-038 engine notes evaluated and consolidated into `learnings.md`.
  T-103 slice A committed, branch pushed.

## Where the rest of the context lives

`docs/roadmap.md` · `docs/r1.1/` (active) · `docs/r1/adr.md` (**ADR-020 + amendment** newest) ·
`docs/learnings.md` · `docs/backlog/` · git. Business/vault → `/garden`.
