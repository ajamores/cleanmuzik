---
type: meta
title: "Hot — cleanmuzik"
updated: 2026-08-02
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

## Current State (2026-08-02)

- **📍 Repo relocated to `~/github/cleanmuzik` (ext4) — THIS copy is now canonical.** The old
  `/mnt/c/…/OneDrive/…/cleanmuzik` copy is a leftover: its WSL `9p` filesystem timed out vitest
  workers (→ `learnings.md` 2026-08-02). Delete it once confident here. Backend data was already
  Linux-side (`~/cleanmuzik-data`, per `.env`), so it's shared and unaffected by the move.
- **On `main`, working tree dirty — T-102 fixes uncommitted** (10 code/doc files + this board).
- **T-102 is BUILT + verified, not yet committed.** Four `/code-review` (high) findings, all fixed:
  1. `App.tsx` — **the blocker:** cold-load re-park net was a single 3s timer; now a bounded `getJob`
     poll (a re-park after 3s was invisible until a manual reload).
  2. `TrackCard.tsx` — duplicate mislabelled "Weak match" when `review` is null → neutral copy.
  3. `TrackCard.tsx` — dead `ReviewInfo` capture collapsed to `{ rec }`; `asCandidates`/`asGuess` gone.
  4. `TrackCard.test.tsx` — false-passing resume test rewritten to `rerender` one instance.
  **65/65 tests green, build + lint clean** (~9s on ext4).
- Queue: 1 fixture parked (Nines *Outro*, `bfff84283fb1`). Library: 14 tracks (same `~/cleanmuzik-data` DB).

## ⟹ NEXT

1. **Commit the T-102 fixes** from here (reviewed + tests green).
2. **Browser `/verify` finding 1** — cold-load resolve that re-parks → the row returns to the inbox on
   its own, no reload (needs owner + running stack; restart Vite / clear `.vite` first).
3. **Merge to `main`** → T-102 done.
4. **T-105** — Signal Path reskin (last UI ticket). Then **§8 close-out** vs the R1.1 spec.
5. Housekeeping: once happy here, delete the `/mnt/c` copy.

## Also open (not the live thread)

- `docs/backlog/` — **T-037** (tag-quality), **T-035** (Shazam tier — build ticket still unwritten).

## Verifying

- **Run everything from `~/github/cleanmuzik` (ext4), never `/mnt/c`** — 9p times out test workers.
- Isolate `DB_PATH` **and** patch `LIBRARY_DIRECTORY` in **both** `beets_engine` *and* `import_seam`,
  or a resolve lands in the real library.
- Restart Vite (clear `node_modules/.vite`) before browser-verifying — cache misses branch changes.
- A yt-dlp `403` at download may be transient — retry once before diagnosing.

## Recent sessions (rolling — last 2–3)

- **2026-08-02** — T-102 `/code-review` (high) → 4 findings, all fixed. Tests wouldn't run on `/mnt/c`
  (9p worker timeout); relocated repo to ext4 `~/github/cleanmuzik`, suite 65/65 green. Uncommitted.
- **2026-07-31 (b)** — T-102 implementation: ReviewInbox became the working review surface, TrackCard
  reduced to a hand-off note, App wires resolve via `resolveEpoch`. All tests rewritten, 65/65.
- **2026-07-31 (a)** — T-103B (keep-untagged) built, verified, merged to `main`.

## Where the rest of the context lives

`docs/roadmap.md` · `docs/r1.1/` (active) · `docs/r1/adr.md` (**ADR-020 + amendment** newest) ·
`docs/learnings.md` · `docs/backlog/` · git. Business/vault → `/garden`.
