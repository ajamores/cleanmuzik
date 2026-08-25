---
type: meta
title: "Hot — cleanmuzik"
updated: 2026-08-25
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

- **T-219 BUILT on branch `perf/t-219-corroboration-fast-path` (ADR-032) — NOT integrated.** Commit
  `a457f25`; **756 green on the branch**. `FingerprintTrustSession._corroboration_fast_path` runs in
  `choose_item` *before* `_reconcile`: a dominant fp whose recording is a beets candidate (`fp`) AND whose
  artist+title the YouTube source corroborates (`yt`) lands via the shared `_accept` tail with **no
  Shazam/ISRC/LLM call** — fp+yt = the 2-of-3 bar re-derived in code (muziktest Confidence-gate transplant).
  Additive on the common path but NOT purely gate-minus-latency: it also drops the LLM's veto + the Shazam→ISRC
  correction for the corroborated case (the accepted T-219 trade; ADR-032). Shared `_yt_supports` /
  `_dominant_match` helpers keep the fast-path bit-identical to the gate. Code-review (5 findings) all
  addressed: 2 were the intended trade (comments made honest), 2 dedup (the helpers), 1 test gap (added
  gate-accept-land test).
  - **Remaining before DONE:** the **ADR-030 measured corpus compare** (engine-touching, owner-adjudicated —
    expect land/park + tags unchanged except corroborated tracks now landing LLM-free, plus any
    remaster-vs-ISRC-original recording-MBID shift), then **integrate to `main`** + flip T-219's status line in
    the closing commit. The `t208_compare.py` scratchpad harness was reaped — needs rebuild for the compare.
  - **Hazard for the compare run:** a `--reload` uvicorn is live on **:8137** (the DB-pollution trap — isolate
    `DB_PATH` + beets lib per `/verify`). Left the pre-existing unrelated `README.md` "Run in WSL" edit unstaged.


- **T-208 DONE — integrated to `main`, pushed, ledger synced.** Commits `717a73c` (perf) + `ced56c4`
  (merge) on `origin/main`; **743 tests green on `main`** (re-confirmed 2026-08-25, 32.6s). New code:
  `app/mb_thin.py` (thin MB + chroma patches + chroma-fork drift guard), `_ensure_full_match` + per-track
  hydration cache + `_cap_park_rows` in `import_seam.py`, install wired in `beets_engine.py`, **ADR-030**.
  Step 5 (fpcalc fold-in) **deferred** → T-210 orbit; `cache_control` fold-in dropped.
  - **Was the integration action** — done this session: the code had already merged/pushed mid-build; only
    the backlog README index line + this board were stale. Both now flipped. T-208's own status line was
    already DONE. Nothing further open on T-208.
  - **Result (compare, 5 corpus tracks):** 0 outcome changes, 0 tag changes, **MB `get_recording` 33→6**.
- **T-210 SPEED HALF DONE — integrated 2026-08-25 (ADR-031).** The premise was wrong and the fix changed:
  beets already sets `timeout=10` per request; the 18–34s tail was beets' **retry ladder** (`Retry(total=6)`
  backoff, ~30s of sleep), not an uncapped socket. `app/mb_retry.py` bounds it to one retry (6→1) via
  `Retry.new()`, preserving backoff/status-list/spacing/limiter. 751 green (8 new). Caps the tail (~503-storm
  spike gone; hung-endpoint worst case ~20s, was ~30s+), **does not lower the median**. One accepted trade:
  a transient error the 6-deep ladder would've ridden out can now miss → blank year / re-searchable park,
  never a wrong tag. **Rate-limiter/ISRC half of T-210 stays OPEN** (correctness, orthogonal).
- **The bottleneck now:** T-208 killed the call-count (11→2); T-210 capped the latency tail. What's left is
  the **steady per-track floor** — the ~15s non-MB baseline (transcode + LLM + senses). The big *steady* win
  is **T-219** (LLM fast-path, ~3–6s/track every track); **T-035** adds coverage. T-210 made the baseline
  predictable; T-219 is the one that visibly lowers it.
- **muziktest head-to-head (2026-08-24, same 14-track playlist):** Lever B ~**8× faster** wall-clock
  (~69s vs ~551s), same 10/4 split, both embed art. **Complementary fingerprint coverage** — AcoustID got
  Tower of Power, Shazam got Franklin; neither dominates. Gap is **closable in cleanmuzik w/o a rewrite**:
  T-208 (done) + T-210 + T-219 + T-035. Full comparison recorded in **T-218**.
- **On `main`:** in sync with `origin/main`, suite last green at R2 close (727). **R2.5** (migrate/clean) is
  still the designated next *release*. **Roadmap R3 line still stale** (Navidrome pivot reshape pending —
  owner edit).

## ⟹ NEXT

1. **T-219 — corroboration fast-path — BUILT on branch (ADR-032), NOT integrated.** Finish it: run the
   ADR-030 corpus compare (owner-adjudicated), then merge `perf/t-219-corroboration-fast-path` to `main` and
   flip the ticket status in the closing commit. The steady speed win (skip the LLM on the corroborated
   majority) is coded + tested + reviewed; only the live compare + integration remain. · **T-035 — Shazam
   fallback fingerprint tier** (coverage: converts AcoustID-miss parks like Franklin into lands; still
   unstarted). Both engine-touching → T-208's acceptance bar.
2. Also unstarted, non-engine: **T-214** (narrate freeze), **T-217** (debounce scan). Also open: **T-210
   rate-limiter/ISRC half** (correctness — shared MB limiter, Pa Salieu ISRC) · a small **T-208 follow-up**
   (review nits: chroma thin-length rounding, unbounded `_chroma_recording_meta`, misleading resolve log).
3. Bigger: reshape **roadmap R3** (Navidrome) · start **R2.5** (migrate/clean — fingerprint dedup is its spine).

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
