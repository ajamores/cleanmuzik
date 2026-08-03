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

- **📍 Repo at `~/github/cleanmuzik` (ext4).** The `/mnt/c` copy is stale — delete when ready.
- **On `main`, working tree dirty** — two new backlog tickets (T-039, T-040) + verification screenshots uncommitted.
- **T-102 is DONE** — committed (`58c0fea`), browser-verified by owner. Cold-load resolve, inbox
  expand/collapse, `watchColdResolve` re-park recovery all confirmed working live.
- Queue: 1 fixture parked (Dave East mixtape, weak match). Library: 14+ tracks (`~/cleanmuzik-data` DB).
- **Jellyfin permissions error** surfaced during verify — "error deleting the item from the server."
  Needs investigation next session (infrastructure, not app code).

## ⟹ NEXT

1. **Investigate the Jellyfin permissions error** — owner saw it during T-102 verify.
2. **Commit the backlog tickets** (T-039, T-040) and clean up verification screenshots.
3. **T-105** — Signal Path reskin (last UI ticket). Then **§8 close-out** vs the R1.1 spec.
4. Housekeeping: delete the `/mnt/c` copy.

## Also open (not the live thread)

- `docs/backlog/` — **T-039** (inbox loading indicator), **T-040** (keep_untagged resolve fails),
  **T-037** (tag-quality), **T-035** (Shazam tier).

## Verifying

- **Run everything from `~/github/cleanmuzik` (ext4), never `/mnt/c`** — 9p times out test workers.
- Isolate `DB_PATH` **and** patch `LIBRARY_DIRECTORY` in **both** `beets_engine` *and* `import_seam`,
  or a resolve lands in the real library.
- Restart Vite (clear `node_modules/.vite`) before browser-verifying — cache misses branch changes.
- A yt-dlp `403` at download may be transient — retry once before diagnosing.

## Recent sessions (rolling — last 2–3)

- **2026-08-02 (b)** — T-102 committed (`58c0fea`), browser-verified: cold-load inbox, expand/collapse,
  resolve, and `watchColdResolve` re-park all confirmed by owner. Filed T-039 (loading indicator) and
  T-040 (keep_untagged failure) to backlog. Jellyfin permissions error noted for next session.
- **2026-08-02 (a)** — T-102 `/code-review` (high) → 4 findings, all fixed. Repo relocated to ext4
  `~/github/cleanmuzik` (9p worker timeout). Suite 65/65 green in ~5s.
- **2026-07-31 (b)** — T-102 implementation: ReviewInbox became the working review surface, TrackCard
  reduced to a hand-off note, App wires resolve via `resolveEpoch`. All tests rewritten, 65/65.

## Where the rest of the context lives

`docs/roadmap.md` · `docs/r1.1/` (active) · `docs/r1/adr.md` (**ADR-020 + amendment** newest) ·
`docs/learnings.md` · `docs/backlog/` · git. Business/vault → `/garden`.
