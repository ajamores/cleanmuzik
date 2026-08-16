---
type: meta
title: "Hot — cleanmuzik"
updated: 2026-08-15
tags:
  - meta
  - hot-cache
status: evergreen
---
# Hot — cleanmuzik (personal YouTube → Jellyfin music tool)

> This repo's own working-memory board — session continuity, loaded at session start via `/hot`.
> A cache, not a journal: rewritten each save, never appended. Durable knowledge lives in this repo's
> stores (`docs/roadmap.md` · `docs/r1/adr.md` · `docs/learnings.md` · `docs/r2/` · git); business
> learnings go to the garden via `/graft`.

## What this repo is

CleanMuzik — personal YouTube → Jellyfin music tool. Purpose, stack, constraints, read-order in
`CLAUDE.md`; scope in `cleanmuzik-prd.md`. Not restated here.

## Current State (2026-08-15)

- **On `main`, working tree clean, pushed.** R2 (Playlists) `in-build`.
- **T-301 DONE + committed** — **ADR-028 filed**: surgical layered artist-credit fold (NFC floor +
  enumerated `Ÿ`→`Y` map + hyphen-class U+2010/U+2011→U+002D), placement via one shared
  `canonicalize_credit` helper in `import_seam.py` at BOTH `_accept` (:634) + `ResolveSession.choose_item`
  (:1520). Council-reviewed (4 lenses + chair); owner picked the layered+observable reach.
- **Both Phase A gates (ADR-027 + ADR-028) now settled** → the design gate **T-310** is unblocked, and
  Phase B can open.
- **Nothing in flight.**

## ⟹ NEXT

1. **T-310 — R2 design gate** (UI scenario screens, owner sign-off) — now unblocked (both ADRs settled).
   Design gate runs *ahead of* code (ADR-016).
2. **Phase B (backend)** — T-302 (accept+expand a playlist URL → N track-jobs; deps T-300 ✓), then the
   seam order **T-304 → T-303** (dedup's skip path appends via T-304 — not parallel).
3. **T-308** (Phase D, deps T-301 ✓) implements ADR-028 — **binding note: BOTH `_accept` AND
   `ResolveSession.choose_item` must route through the one helper**; `git mv docs/backlog/T-037.md
   docs/r2/` on starting it.

## Recent sessions (rolling — last 2–3)

- **2026-08-15 (this session)** — **T-301 done**: authored **ADR-028** via a 5-agent council (4 corporate
  lenses + chair). Council **corrected T-037's diagnosis**: the `Ÿ` is NOT an in-app decode fault (a plain
  `Y` 0x59 can't become U+0178 under any codec; MB serves it, beets writes it faithfully) — reframed as
  identity normalisation, not mojibake repair. Killed NFKC (doesn't even decompose `Ÿ`→`Y`). Owner chose
  layered+observable over the Pragmatist's minimal fold. Filed **T-044** (near-dup-folder tripwire) as the
  recorded follow-on, not binding on T-308.
- **2026-08-15 (earlier)** — Built + shipped **T-300** (data model + **ADR-027**), pushed to `main`.
  Owner settled ADR-027's parked decisions (resolve poll 2s/10s, create-playlist-at-queued); push logged
  as a live T-304 candidate. Declined a member↔job FK (a dedup-skip adds a member with no new job).
- **2026-08-14** — Flipped R2 → `in-build`; fixed the stale "Signal Path" label → console skin (ADR-018).

## Where the rest of the context lives

`docs/roadmap.md` (R2 `in-build`) · `docs/r2/spec.md` + `spec.html` + **`tickets.md`** (T-300 done) ·
`docs/r1/adr.md` (**ADR-027 last filed**; ADR-028 is T-301's, unwritten) · `docs/learnings.md` ·
`docs/workflow.md` · `docs/backlog/` (incl. T-037 → git-mv to `docs/r2/` when T-308 starts). Business →
`/graft`.
