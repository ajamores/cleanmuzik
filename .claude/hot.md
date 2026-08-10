---
type: meta
title: "Hot — cleanmuzik"
updated: 2026-08-10
tags:
  - meta
  - hot-cache
status: evergreen
---
# Hot — cleanmuzik (personal YouTube → Jellyfin music tool)

> This repo's own working-memory board — session continuity, loaded at session start via `/hot`.
> A cache, not a journal: rewritten each save, never appended. Durable knowledge lives in this repo's
> stores (`docs/r1/adr.md` · `docs/learnings.md` · `docs/research/` · `docs/backlog/` · git); business
> learnings go to the garden via `/graft`.

## What this repo is

CleanMuzik — personal YouTube → Jellyfin music tool. Purpose, stack, constraints, read-order in
`CLAUDE.md`; scope in `cleanmuzik-prd.md`. Not restated here.

## Current State (2026-08-10)

- **On `main`, pushed to `origin` at `8210074`.** Tree clean.
- **R1 + R1.1 shipped.** **R1.5 is the current release (`specing`)** — the engine rethink. R1.6 (LLM genre)
  and R2 (playlists + migrate) sequence behind it (`docs/roadmap.md`).

## ⟹ Engine decision — architecture **B** locked; R1.5 spec effectively signed off

**B = multi-sense reconciliation.** Identity from 3 senses (yt-dlp title · AcoustID fingerprint · Shazam)
reconciled by one LLM call. Spec: `docs/r1.5/spec.md` (v3). Evidence: `docs/research/engine-rethink-spike.md`
(exp 1/3/6/7 gate + exp 8/9 head-to-head). Binding: **ADR-021 (amended 2026-08-10)**, ADR-022. Two rules:

- **Rule 1 — 2-of-3 vote.** Auto-land needs ≥2 senses agreeing on **artist AND title** (code re-derives the
  vote over *present* senses); else park. LLM may override a wrong fingerprint iff 2 senses agree.
- **Rule 2 — facts from a real lookup** (fingerprint MBID or ISRC→MB), never LLM-invented. Carried forward.
- **Speed:** ~4.2s vs today's 11/37s (8.6×). **Parity:** must land everything R1 lands (art/synced-lyrics/
  genre/year/tags). Owner agreed to all of it; the beets question (below) was the last open thread — settled.

## ⟹ NEXT — decompose R1.5 tickets

Dep order: **SourceSignals** (`download.py:~299`) → **Shazam** (`app/shazam.py`, subprocess to 3.12
`.venv-shazam` + short ADR, hard 8s timeout) → **reconcile + 2-of-3 gate** (`choose_item`; augmented
candidates carry real MBIDs so `chosen_candidate` can name the ISRC override; persist `reason`/
`contradictions`) → **review-card fields**. **ADR-016 design gate** on the review card before its UI code.
Add R1.5 tickets file (`docs/r1.5/tickets.md` — none yet).

## Backlog added this session (not R1.5)

`T-043` scrub (clean tag writes) · `T-042` replaygain (loudness) · `mbsync`/`duplicates`/`fromfilename`
folded into the R2.5 migrate idea (`docs/backlog/README.md`). Artifact: `docs/r1.5/r1.5-overview.html`
(visual spec brief, published private).

## Live library mess (real cleanup, unticketed)

`Vanessa Bling…/Frontline.mp3` is really Pa Salieu (spike marquee fixture). `JAŸ-Z/Roc Boys` — T-037.

## Recent sessions (rolling — last 2–3)

- **2026-08-10** — Big session: ratified ADR-021–023 + merged spike→main. Drafted R1.5 spec for A →
  cold-reviewed → **ran exp 8/9, pivoted A→B**, amended ADR-021 → rewrote spec v2 → cold-reviewed (2
  blockers) → **v3** (closed) → **beets audit**: dropped Shazam art/lyrics (beets already does synced
  lyrics; art is hand-rolled `artwork.py`), filed T-043 + learnings (acousticbrainz service dead → local
  Essentia for R3). Spec effectively signed off. Suites green on main (432/65).
- **2026-08-09** — Accuracy/speed spike (locks 1b/3/7 met); council → identify is the bottleneck.

## Where the rest of the context lives

`docs/r1.5/spec.md` (v3) · `docs/research/engine-rethink-spike.md` · `docs/roadmap.md` · `docs/r1/adr.md`
· `docs/learnings.md` · `docs/backlog/` · `docs/r2/spec.md` · git. Business/vault → `/garden`.
