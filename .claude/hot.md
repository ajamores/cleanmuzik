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
> stores (`docs/r1/adr.md` · `docs/learnings.md` · `docs/r1.1/` · `docs/backlog/` · git); business/vault
> learnings go to the garden via `/graft`.

## What this repo is

CleanMuzik — personal YouTube → Jellyfin music tool. Purpose, stack, constraints and read-order are in
`CLAUDE.md`; scope in `cleanmuzik-prd.md`. Not restated here.

## Current State (2026-07-30)

- **On branch `t103-research` at `aeaba57`, one commit ahead of `main`, working tree clean.**
  `main` is unchanged at `1976bbd`. Nothing is pushed.
- **Both servers up**: `:8137` backend, `:5173` client. The client has changed a lot — **restart Vite
  before browser-verifying**, or it may serve a stale transform (learnings 2026-07-24).
- **Queue still holds the 2 fixtures**, both `pending` with audio on disk: Frank Ocean *Strawberry
  Swing* (9.4 MB) and Nines *Outro* (7.6 MB). Deliberately not consumed — they have known-correct
  MBIDs. Library unchanged at 9 artist folders.

## ⟹ NEXT: T-038 first, then finish T-103

The owner asked for **T-038** (`docs/backlog/T-038.md`) to be written **first in the next session** —
capability/limitation notes for beets, MusicBrainz and ShazamIO. It is a foundation ticket filed
because T-103's review round cost a session to rework.

Then T-103 slice A needs two things to be **done**: the **browser pass** at `:5173` (the form, swap,
empty state, `EventSource` through the Vite proxy — needs the owner), then **merge to `main`**.
Slice B (keep-untagged) follows. Full status on T-103's entry in `docs/r1.1/tickets.md`.

## Also open (not the live thread)

- **T-106 is BUILT, not done** — its last gate closes with T-103's browser `/verify`.
- **T-102** then **T-105** (reskin, last). Do not fan out T-102 ∥ T-103 — overlapping client files.
- `docs/backlog/` — **T-037** (tag-quality; half-answered by T-103's verify run), **T-035**
  (LLM-disambiguator, deferred), **T-038** (the notes above).

## Verifying

- Isolate `DB_PATH` **and** patch `LIBRARY_DIRECTORY` in **both** `beets_engine` *and* `import_seam`
  (it is imported by name, so patching one is not enough), or a resolve lands in the real library.
- A yt-dlp `403` at download may be **transient** — retry once before diagnosing.

## Where the rest of the context lives

`docs/roadmap.md` · `docs/r1.1/` (active) · `docs/r1/adr.md` (**ADR-020 + its amendment** newest) ·
`docs/learnings.md` · `docs/backlog/` · `docs/r1.1/design/*.html` · git. Business/vault → `/garden`.
