---
type: meta
title: "Hot — cleanmuzik"
updated: 2026-07-27
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

## Current State (2026-07-27)

- **`main` is clean at `06c24ed`, T-106 integrated.** Not yet pushed.
- **The data dir moved off the Windows/OneDrive tree.** `DB_PATH` in `.env` now points at
  `/home/armand/cleanmuzik-data/` (Linux fs), which places the app DB, the beets library DB **and**
  the staging root. The Jellyfin library is unaffected — still `/mnt/c/Users/aj_am/Music/CleanMuzik`.
- **The queue is 1 healthy review**: Frank Ocean — Strawberry Swing, audio present, 5 candidates. The
  9 dead rows are deleted. A pre-surgery DB backup is in this session's scratchpad only — **not
  durable**; take another if you want one that survives.
- **Server is running** on `:8137` (started this session, merged code) plus Vite on `:5173`.

## ⟹ LIVE THREAD — T-106 needs its last gate

Everything else landed and was observed (details in `docs/r1.1/tickets.md`). What's left is the
**end-to-end `/verify`** from the ticket's Done-when: park a track → restart → resolve → confirm the
tagged MP3 lands in Jellyfin. Owner-triggered; needs a real download and writes to the real library.

**Don't use the Frank Ocean row as the subject** — all 5 of its candidates are wrong (top match is
Coldplay's original, 0.52). Resolving it would mistag. Park a fresh track instead.

## Also open (not the live thread)

- **T-103 escape-hatch design** — awaiting owner sign-off (ADR-016 gate). Frank Ocean is now the live
  example of exactly the case it exists for: audio fine, no correct candidate offered.
- **Shazam build ticket** — ADR-019 ratified; the tier ticket itself is still unwritten
  (`docs/backlog/T-035.md`, item 4).
- **T-102** (lift the review lifecycle out of `TrackCard`) renders T-106's `staging_missing` flag.
  **T-105** reskin, **R2** migrate — later.
- **Worth an ADR?** "The data dir is placed by `DB_PATH` and must not sit in a cloud-synced tree" now
  constrains future code but lives only in `learnings.md` + the ticket. Owner's call to promote.

## Verifying

- Isolate `DB_PATH` to a temp dir **and** monkeypatch `beets_engine.LIBRARY_DIRECTORY` (a hardcoded
  constant, not a setting), or a resolve lands in the real library. The suite already does this — a
  full run with the real `.env` loaded left the live DB untouched.
- Sandbox: `yt-dlp --js-runtimes node`; `uv venv`, not `python3 -m venv`.
- **`--reload` did not fire** on a `touch` of a module under `/mnt/c` this session (inotify on DrvFs).
  A real content edit was not tested — don't rely on either behaviour; restart deliberately.
- `pkill -f uvicorn` matches its own shell and kills it. Kill by PID.

## Where the rest of the context lives

`docs/roadmap.md` · `docs/r1.1/` (active) · `docs/r1/adr.md` (**ADR-019** newest) · `docs/learnings.md`
· `docs/backlog/` · `docs/r1/design/*.html` · git (tag `r1-single-song`). Business/vault → `/garden`.
