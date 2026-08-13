---
type: meta
title: "Hot — cleanmuzik"
updated: 2026-08-13
tags:
  - meta
  - hot-cache
status: evergreen
---
# Hot — cleanmuzik (personal YouTube → Jellyfin music tool)

> This repo's own working-memory board — session continuity, loaded at session start via `/hot`.
> A cache, not a journal: rewritten each save, never appended. Durable knowledge lives in this repo's
> stores (`docs/roadmap.md` · `docs/r1/adr.md` · `docs/learnings.md` · `docs/r1.5/` · git); business
> learnings go to the garden via `/graft`.

## What this repo is

CleanMuzik — personal YouTube → Jellyfin music tool. Purpose, stack, constraints, read-order in
`CLAUDE.md`; scope in `cleanmuzik-prd.md`. Not restated here.

## Current State (2026-08-13)

- **On `main`, pushed to origin.** Client **71** / server **529** green (R1.5 close was docs-only).
- **R1 + R1.1 + R1.5 all SHIPPED.** No release is `in-build` right now — **R1.6** (LLM genre, gated on
  exp 4) is next in sequence; R2 (playlists + migrate/clean) follows. Flip a status to start one.
- **R1.5 shipped 2026-08-13** — architecture B (multi-sense reconciliation). T-209 verified §7 end-to-end
  (11/12 on real audio, real library untouched); marquee **Pa Salieu override** lands the correct identity
  via a real ISRC MBID where R1 could only mistag/park.
- **The one non-pass was speed** — the spike's ~8.6× / <6s was **fixture-measured, not integrated**; §7
  amended to no-regression-vs-R1 (B is 22–26s vs R1's ~36s auto-land, so faster, just not the fantasy).

## The T-208 speed story (settled — deferred, not dropped)

- A design council corrected the lead's analysis: the ~8–9s fat is **fan-out** (5 independent MB
  `track_for_id` hydrations behind the 1/sec limit), **not** an unfixable dependency chain — and the repo
  already fixed the identical waste on re-search (`mb_search.py` finding #4, 27s→~1s). Full attribution +
  the 3-piece plan live in **T-208** (`docs/r1.5/tickets.md`).
- **Owner call:** 5s/song is a vanity metric on a one-at-a-time background add → **T-208 deferred to R2**
  (bulk-migrate multiplies per-song seconds to ~15–20 min). **T-214** (narrate the identify freeze —
  perceived speed, near-zero risk) filed to backlog.

## ⟹ NEXT

- Nothing is mid-flight. Start **R1.6** (or pull **R2** forward) by flipping its roadmap status when work
  begins. R1.6 opens with **exp 4** (the never-run confident-wrong-rate test for LLM genre).

## Recent sessions (rolling — last 2–3)

- **2026-08-13 (this session)** — Closed **T-209** (§7 11/12); **shipped R1.5**. Ran a design council on
  the speed finding → corrected the fan-out blind spot, **deferred T-208 to R2**, filed **T-214**
  (narration). Roadmap flipped R1.5 → shipped; learning transcribed.
- **2026-08-12 (prev)** — T-207 review-card + T-200 reconcile-key fix (reconcile went live) + T-213
  (403 retry). thru `a455386`.

## Where the rest of the context lives

`docs/roadmap.md` (R1.5 shipped) · `docs/r1.5/spec.md` (§7 amended) · `docs/r1.5/tickets.md` (T-208
deferred, T-214 backlog, T-209 done) · `docs/research/engine-rethink-spike.md` · `docs/r1/adr.md` ·
`docs/learnings.md` · `docs/backlog/` (T-210/211/212). Business/vault → `/graft`.
