---
type: meta
title: "Hot — cleanmuzik"
updated: 2026-08-24
tags:
  - meta
  - hot-cache
status: evergreen
---
# Hot — cleanmuzik (personal YouTube → Jellyfin music tool)

> This repo's own working-memory board — session continuity, loaded at session start via `/hot`.
> A cache, not a journal: rewritten each save, never appended. Durable knowledge lives in this repo's
> stores (`docs/roadmap.md` · `docs/r1/adr.md` · `docs/backlog/` · `docs/learnings.md` · git);
> business learnings go to the garden via `/graft`.

## What this repo is

CleanMuzik — personal YouTube → Jellyfin music tool. Purpose, stack, constraints, read-order in
`CLAUDE.md`; scope in `cleanmuzik-prd.md`. Not restated here.

## Current State (2026-08-25)

- **T-208 DONE — integrated to `main`, pushed, ledger synced.** Commits `717a73c` (perf) + `ced56c4`
  (merge) on `origin/main`; **743 tests green on `main`** (re-confirmed 2026-08-25, 32.6s). New code:
  `app/mb_thin.py` (thin MB + chroma patches + chroma-fork drift guard), `_ensure_full_match` + per-track
  hydration cache + `_cap_park_rows` in `import_seam.py`, install wired in `beets_engine.py`, **ADR-030**.
  Step 5 (fpcalc fold-in) **deferred** → T-210 orbit; `cache_control` fold-in dropped.
  - **Was the integration action** — done this session: the code had already merged/pushed mid-build; only
    the backlog README index line + this board were stale. Both now flipped. T-208's own status line was
    already DONE. Nothing further open on T-208.
  - **Result (compare, 5 corpus tracks):** 0 outcome changes, 0 tag changes, **MB `get_recording` 33→6**.
- **The bottleneck flipped (owner-clarified 2026-08-24):** T-208 killed the MB *call-count* (11→2). What's
  left, in order: (1) **MB *latency* tail** — a single call can still hang 18–34s, the #1 remaining time cost,
  → **T-210** (per-call timeout); (2) a steady ~15s non-MB floor (transcode + LLM + senses). No single new
  villain — it's still mostly MB, just the tail not the count.
- **muziktest head-to-head (2026-08-24, same 14-track playlist):** Lever B ~**8× faster** wall-clock
  (~69s vs ~551s), same 10/4 split, both embed art. **Complementary fingerprint coverage** — AcoustID got
  Tower of Power, Shazam got Franklin; neither dominates. Gap is **closable in cleanmuzik w/o a rewrite**:
  T-208 (done) + T-210 + T-219 + T-035. Full comparison recorded in **T-218**.
- **On `main`:** in sync with `origin/main`, suite last green at R2 close (727). **R2.5** (migrate/clean) is
  still the designated next *release*. **Roadmap R3 line still stale** (Navidrome pivot reshape pending —
  owner edit).

## ⟹ NEXT

1. **T-210 — the per-call MB timeout.** The #1 remaining time lever (caps the 18–34s tail so wall-clock
   becomes predictable). Cheap, non-engine-identity. **Do this next.** (T-208 is integrated — done.)
2. **T-219 — corroboration fast-path** (skip the LLM when the fingerprint agrees with the source title;
   the muziktest transplant, ~3–6s/track steady win) · **T-035 — Shazam fallback fingerprint tier**
   (coverage: converts AcoustID-miss parks like Franklin into lands). Both engine-touching → T-208's
   acceptance bar.
3. Also unstarted, non-engine: **T-214** (narrate freeze), **T-217** (debounce scan).
4. Bigger: reshape **roadmap R3** (Navidrome) · start **R2.5** (migrate/clean — fingerprint dedup is its spine).

## Recent sessions (rolling — last 2–3)

- **2026-08-24 (this session)** — **Built T-208** (winner-only MB fan-out collapse; `mb_thin.py`, ADR-030,
  743 green) and **passed its acceptance compare** (33→6 MB calls, 0 decision/tag drift). Ran a live
  14-track playlist + a **muziktest head-to-head** (Lever B ~8× faster; complementary AcoustID/Shazam
  coverage). Filed **T-219** (LLM fast-path), promoted **T-210** (MB timeout) to primary lever. Killed a
  runaway 27h uvicorn (32% CPU). NOT committed. Solo (Opus).
- **2026-08-23** — **Profiled identify (T-218).** Isolated harness named the MB recording fan-out the target;
  owner chose T-208's within-beets fix, refuted T-215. Also the **Navidrome pivot** (T-40x set filed).
- **2026-08-21** — Closed **T-311** (live acceptance sweep) + fixed **T-316**. **R2 shipped + pushed.**

## Where the rest of the context lives

`docs/roadmap.md` (R2 shipped; **R3 line stale — reshape pending**) · `docs/backlog/` (**T-208** built +
compare-passed; **T-210** now the primary speed lever (MB timeout); **T-219** new (LLM fast-path); **T-035**
Shazam fallback; **T-218** holds the Lever-A-vs-B comparison; **T-40x** listening layer; T-214 · T-217 · …) ·
`docs/r1/adr.md` (**ADR-030** = T-208) · `docs/learnings.md`. Scratchpad harnesses (uncommitted, per /verify):
`t208_compare.py` (baseline/branch/diff), `t208_playlist.py` (live playlist). Sibling repos:
**`~/github/muziktest`** (Lever B — album-only, Shazam-primary; its `tools/observe.py` is its measurement
harness) · **`~/github/music-stack`** (Navidrome trial). Business → `/graft`.
