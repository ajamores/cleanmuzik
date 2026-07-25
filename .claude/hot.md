---
type: meta
title: "Hot — cleanmuzik"
updated: 2026-07-25
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

## Current State (2026-07-25)

- **On `main`.** Nothing committed this session — a **pile of uncommitted docs** is staged in the tree:
  `docs/backlog/T-035.md` (new) · `T-034.md` + backlog `README.md` (reframed) · `docs/r1.1/tickets.md`
  (T-103 design note) · `docs/r1.1/design/*.html` (new, 2 files) · `docs/learnings.md` · plus the prior
  session's `docs/r1.1/tickets.md` T-101/T-104 marks. **Commit when ready** (small, then tree is clean).
- **T-101 + T-104 remain DONE + VERIFIED LIVE** (merged `700df62`, `90d5854`). No verify debt.
- This session was **design/experiment, no code shipped.** Chased "an easy track parked with junk
  candidates" → found the fingerprint pipeline is healthy (5 tracks auto-landed happy-path); the Nipsey
  rip was a *reversed-title* text-search fallback. A 4-lens agent panel → consensus: **don't build the
  T-034 auto-match tower — build a manual-resolution escape hatch** (re-search + keep-untagged), fold
  into **T-103**. Flow drawn as 6 flat screens (`docs/r1.1/design/review-rescue-flow.html`).

## ⟹ LIVE THREAD — continue next session

**Shazam backup-fingerprint spike (`docs/backlog/T-035.md`).** n=1 decisive win: the track AcoustID
couldn't fingerprint, **Shazam identified cold** (Nipsey Hussle — All Get Right). Identification-only,
feeds beets/MB (ADR-005 intact). **Next: measure the lift** —

1. Run Shazam over **every track in the parked review queue** (real DB ~8 reviews) → count auto-rescues.
   *That rescue-rate number is the go/no-go.* Harness ready: `scratchpad/shazam-test/` (uv venv +
   shazamio; audio via `yt-dlp --js-runtimes node`).
2. Test the truly-obscure parked tracks (the Nines-outro TV-mix) → shows where Shazam *also* fails =
   the residual the manual escape hatch still must cover.
3. If go → draft an ADR (add Shazam backup tier) for owner ratification. Cautions: unofficial API; was
   the *abandoned* engine (different now as a backup ID tier); network dep.

## Also open (not the live thread)

- **T-103 escape-hatch design** — awaiting owner sign-off (ADR-016 gate) + an ADR. Shazam outcome
  affects *how often* the manual exit is hit, not whether it's needed. Screens filed.
- **T-102** — original next build ticket (lift review lifecycle out of `TrackCard`). Still valid.
- **T-034** — Layers 0/2 likely retired by T-035; Layer 1 kept for R2/migrate only.
- **T-105** Signal Path reskin; **R2** migrate — later.

## Verifying

- Owner's real servers: `:8137` (uvicorn `--reload`, real library — **do NOT POST jobs to it**) + `:5173`
  (Vite — restart after any merge/checkout touching `client/`). Isolate `DB_PATH` to a temp dir for
  backend checks. Sandbox download gotcha: `yt-dlp --js-runtimes node` (plain pull 403s); `uv venv` not
  `python3 -m venv`. Both in `docs/learnings.md` (2026-07-24, 2026-07-25).

## Where the rest of the context lives

`docs/roadmap.md` · `docs/r1.1/` (active) · `docs/r1/adr.md` (ADR-018 newest) · `docs/learnings.md` ·
`docs/backlog/` (T-035 live) · `docs/r1/design/*.html` · git (tag `r1-single-song`). Business/vault → `/garden`.
