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
> stores (`docs/r1/adr.md` · `docs/learnings.md` · `docs/engines/` · `docs/r1.1/` · `docs/backlog/` ·
> git); business/vault learnings go to the garden via `/graft`.

## What this repo is

CleanMuzik — personal YouTube → Jellyfin music tool. Purpose, stack, constraints and read-order are in
`CLAUDE.md`; scope in `cleanmuzik-prd.md`. Not restated here.

## Current State (2026-07-30)

- **On branch `t103-research`. T-038's work is UNCOMMITTED in the working tree** — modified
  `.env.example`, `CLAUDE.md`, `docs/backlog/T-038.md`, `docs/learnings.md`, plus an untracked
  `docs/engines/`. Nothing pushed. `main` untouched this session.
- **Both servers still up**: `:8137` backend, `:5173` client. **Restart Vite before browser-verifying**
  — the client changed heavily in the last session (learnings 2026-07-24).
- **Queue still holds the 2 fixtures**, both `pending` with audio on disk: Frank Ocean *Strawberry
  Swing* and Nines *Outro*. Deliberately not consumed. Library unchanged, 9 artists.

## ⟹ NEXT: land T-038, then finish T-103

**T-038 is BUILT, not done** — six engine pages written, no review, no merge. Two steps left:
`/code-review` the diff, then commit and merge to `main`. **No `/verify`** — it lands no code and has
no pipeline artifact; its acceptance check is that every claim carries a provenance tag and the
`[source]` line numbers resolve (spot-checked at write time, worth a re-run after any edit).

Then **T-103 slice A**: the **browser pass** at `:5173` (form, swap, empty state, `EventSource`
through the Vite proxy — needs the owner), then merge. Slice B (keep-untagged) follows, entry point
per the ADR-020 amendment. Status on T-103's entry in `docs/r1.1/tickets.md`.

## Also open (not the live thread)

- **T-106 is BUILT, not done** — its last gate closes with T-103's browser `/verify`.
- **T-102** then **T-105** (reskin, last). Do not fan out T-102 ∥ T-103 — overlapping client files.
- `docs/backlog/` — **T-037** (tag-quality; its genre half now has a home in
  `docs/engines/thin-surfaces.md`), **T-035** (Shazam tier — build ticket still unwritten).

## Verifying

- Isolate `DB_PATH` **and** patch `LIBRARY_DIRECTORY` in **both** `beets_engine` *and* `import_seam`
  (imported by name, so patching one is not enough), or a resolve lands in the real library.
- A yt-dlp `403` at download may be **transient** — retry once before diagnosing.

## Where the rest of the context lives

`docs/roadmap.md` · `docs/r1.1/` (active) · `docs/r1/adr.md` (**ADR-020 + amendment** newest) ·
`docs/engines/` (**new** — what the external tools do; its README holds the store-boundary rule) ·
`docs/learnings.md` · `docs/backlog/` · git. Business/vault → `/garden`.
