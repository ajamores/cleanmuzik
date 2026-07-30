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

- **On branch `t103-research`, ahead of `main`, working tree clean, nothing pushed.** `main` itself is
  untouched by this session. The tip is this board's own commit; the T-103 slice-A work is the commit
  beneath it. (Don't pin a SHA here — the last board named one and was wrong the moment it was saved.)
- **Both servers up**: `:8137` backend, `:5173` client. The client changed heavily — **restart Vite
  before browser-verifying**, or it may serve a stale transform (learnings 2026-07-24).
- **Queue still holds the 2 fixtures**, both `pending` with audio on disk: Frank Ocean *Strawberry
  Swing* (9.4 MB) and Nines *Outro* (7.6 MB). Deliberately not consumed — they have known-correct
  MBIDs, and slice A was verified against a *copy* into a temp library. Library unchanged, 9 artists.

## ⟹ NEXT: T-038 first, then finish T-103

**T-038** (`docs/backlog/T-038.md`) — capability/limitation notes for beets, MusicBrainz and ShazamIO.
Owner asked for this **before more build work**: it is the foundation ticket filed because T-103's
review round cost a session to rework.

Then T-103 slice A needs two things to be **done**: the **browser pass** at `:5173` (form, swap, empty
state, `EventSource` through the Vite proxy — needs the owner), then **merge to `main`**. Slice B
(keep-untagged) follows, and its entry point must change per the ADR-020 amendment. Full status on
T-103's entry in `docs/r1.1/tickets.md`.

## Also open (not the live thread)

- **T-106 is BUILT, not done** — its last gate closes with T-103's browser `/verify`.
- **T-102** then **T-105** (reskin, last). Do not fan out T-102 ∥ T-103 — overlapping client files.
- `docs/backlog/` — **T-037** (tag-quality; half-answered by T-103's verify run), **T-035**
  (LLM-disambiguator, deferred), **T-038** (above).

## Verifying

- Isolate `DB_PATH` **and** patch `LIBRARY_DIRECTORY` in **both** `beets_engine` *and* `import_seam`
  (imported by name, so patching one is not enough), or a resolve lands in the real library.
- A yt-dlp `403` at download may be **transient** — retry once before diagnosing.

## Where the rest of the context lives

`docs/roadmap.md` · `docs/r1.1/` (active) · `docs/r1/adr.md` (**ADR-020 + its amendment** newest) ·
`docs/learnings.md` · `docs/backlog/` · `docs/r1.1/design/*.html` · git. Business/vault → `/garden`.
