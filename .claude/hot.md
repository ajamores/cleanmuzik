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

- **On branch `t103-research`, working tree clean, 6 commits ahead of `main`.** Pushed and tracking
  `origin/t103-research`. `main` itself is untouched.
- **T-038 is closed** — engine notes were built (`36f1138`), then evaluated and consolidated into
  `learnings.md` (`65a8ea9`). `docs/engines/` removed; 3 genuinely new facts kept as entries.
- **T-103 slice A is BUILT, not done** — needs the browser pass at `:5173`.
- **Both servers up**: `:8137` backend, `:5173` client. **Restart Vite before browser-verifying** —
  the client changed heavily two sessions ago (learnings 2026-07-24).
- **Queue still holds the 2 fixtures**, both `pending` with audio on disk: Frank Ocean *Strawberry
  Swing* and Nines *Outro*. Deliberately not consumed. Library unchanged, 9 artists.

## ⟹ NEXT: T-103 browser pass, then merge, then slice B

1. **T-103 slice A** — the **browser pass** at `:5173` (form, swap, empty state, `EventSource`
   through the Vite proxy). **Needs the owner**; this is the one thing no tool here can do. It closes
   **T-106**'s last gate at the same time.
2. **Merge to `main`**. Nothing is *done* until it's there.
3. Then **slice B** (keep-untagged), entry point per the ADR-020 amendment. Status on T-103's entry
   in `docs/r1.1/tickets.md`.

## Also open (not the live thread)

- **T-102** then **T-105** (reskin, last). Do not fan out T-102 ∥ T-103 — overlapping client files.
- `docs/backlog/` — **T-037** (tag-quality), **T-035** (Shazam tier — build ticket still unwritten).

## Verifying

- Isolate `DB_PATH` **and** patch `LIBRARY_DIRECTORY` in **both** `beets_engine` *and* `import_seam`
  (imported by name, so patching one is not enough), or a resolve lands in the real library.
- A yt-dlp `403` at download may be **transient** — retry once before diagnosing.

## Recent sessions (rolling — last 2–3)

- **2026-07-30 (this session)** — evaluated T-038 engine notes via 3 parallel agents (accuracy,
  rework prevention, maintenance burden); owner decided to consolidate into `learnings.md` and drop
  the separate store. 3 new facts kept, 7 files removed. T-038 closed.
- **2026-07-30 (earlier)** — T-038 built (6 engine note pages), T-103 slice A committed, branch
  pushed to origin.

## Where the rest of the context lives

`docs/roadmap.md` · `docs/r1.1/` (active) · `docs/r1/adr.md` (**ADR-020 + amendment** newest) ·
`docs/learnings.md` · `docs/backlog/` · git. Business/vault → `/garden`.
