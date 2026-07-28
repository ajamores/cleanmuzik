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

- **`main` clean at `26b1e8d`. Eight commits unpushed** — T-106 and its docs. Push after the verify.
- **Servers are down.** Nothing on `:8137` or `:5173`; start both before verifying.
- **Data dir is `/home/armand/cleanmuzik-data/`** (Linux fs, set by `DB_PATH` in `.env`) — app DB,
  beets library DB and staging root. Jellyfin library unchanged at `/mnt/c/.../Music/CleanMuzik`.
- **Queue is 1 healthy review**: Frank Ocean — Strawberry Swing, audio present, 5 candidates. The
  9 dead rows are deleted; the only DB backup was scratchpad-only and is gone.

## ⟹ LIVE THREAD — T-106's last gate

**Owner runs `/verify` next session.** Everything else in T-106 landed and was observed (see
`docs/r1.1/tickets.md`). What's left is the Done-when end-to-end: park a track → restart the server →
resolve → confirm the tagged MP3 320 lands in Jellyfin.

**Use a fresh track, not the Frank Ocean row.** All 5 of its candidates are wrong and it is now
T-103's regression fixture. Then push.

## Also open (not the live thread)

- **T-103 escape-hatch design** — awaiting owner sign-off (ADR-016 gate). Frank Ocean is the live
  example of the case it exists for; the reasoning is filed in ADR-019 and `docs/backlog/T-035.md`.
- **Shazam build ticket** — still unwritten (`T-035.md` item 4). It now has a prerequisite: the
  pipeline must be able to tell a Shazam-derived match from an AcoustID one, or ADR-019's new
  condition 3 can't be enforced.
- **T-102** (lift the review lifecycle out of `TrackCard`) renders T-106's `staging_missing` flag.
  **T-105** reskin, **R2** migrate — later.
- **Worth an ADR?** "The data dir is placed by `DB_PATH` and must not sit in a cloud-synced tree"
  constrains future code but lives only in `learnings.md`. Owner's call to promote.

## Verifying

- Isolate `DB_PATH` to a temp dir **and** monkeypatch `beets_engine.LIBRARY_DIRECTORY` (a hardcoded
  constant, not a setting), or a resolve lands in the real library. The suite already does this.
- Sandbox: `yt-dlp --js-runtimes node`; `uv venv`, not `python3 -m venv`.
- **`--reload` did not fire** on a `touch` of a module under `/mnt/c`. Restart deliberately.

## Where the rest of the context lives

`docs/roadmap.md` · `docs/r1.1/` (active) · `docs/r1/adr.md` (**ADR-019** newest) · `docs/learnings.md`
· `docs/backlog/` · `docs/r1/design/*.html` · git (tag `r1-single-song`). Business/vault → `/garden`.
