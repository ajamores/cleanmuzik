---
type: meta
title: "Hot — cleanmuzik"
updated: 2026-08-03
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

## Current State (2026-08-03)

- **On `main`, working tree clean.**
- **T-105 design gate PASSED** — owner approved the OutKast-style crest logo (Rev C) and Signal Path
  palette with ambient signal line, hover glow, segmented meter rail. Design references committed to
  `docs/r1/design/` (`crest-logo.html`, `t105-design-gate.html`). Ready for implementation.
- Queue: 1 fixture parked (Dave East mixtape, weak match). Library: 14+ tracks (`~/cleanmuzik-data` DB).
- Jellyfin permissions error (T-102 verify) — not app code; owner resolved by deleting tracks via
  file explorer. No action needed.

## ⟹ NEXT

1. **T-105 implementation** — go straight into building. Apply Signal Path reskin to components:
   crest logo SVG, CSS token swap, ambient line, segmented meter rail, hover glow, cover art on
   landed tracks. All design references in `docs/r1/design/`.
2. After T-105: **§8 close-out** vs the R1.1 spec.
3. Housekeeping: delete the `/mnt/c` copy.

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

- **2026-08-03** — T-105 design gate: iterated on OutKast-style crest logo (5 revisions via Fable
  agent — medieval→street→tighter text→shorter wings→softer bottom→parallel outlines). Owner approved
  Rev C. Explored equalizer bars background, reverted to ambient signal line. Cleaned up T-102
  verification screenshots, gitignored `.playwright-mcp/`. Jellyfin permissions error closed (infra).
- **2026-08-02 (b)** — T-102 committed (`58c0fea`), browser-verified. Filed T-039, T-040 to backlog.
- **2026-08-02 (a)** — T-102 `/code-review` (high) → 4 findings fixed. Repo relocated to ext4. 65/65.

## Where the rest of the context lives

`docs/roadmap.md` · `docs/r1.1/` (active) · `docs/r1/adr.md` (**ADR-020 + amendment** newest) ·
`docs/learnings.md` · `docs/backlog/` · git. Business/vault → `/garden`.
