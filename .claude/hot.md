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

- **T-219 DONE — integrated to `main` 2026-08-25 (ADR-032), pushed, ledger synced.** Work `a457f25` + merge
  on `main`; **756 green on `main`**. `FingerprintTrustSession._corroboration_fast_path` runs in `choose_item`
  *before* `_reconcile`: a dominant fp whose recording is a beets candidate (`fp`) AND whose artist+title the
  YouTube source corroborates (`yt`) lands via the shared `_accept` tail with **no Shazam/ISRC/LLM call** —
  fp+yt = the 2-of-3 bar re-derived in code (muziktest Confidence-gate transplant). Additive but NOT purely
  gate-minus-latency: it also drops the LLM's veto + the Shazam→ISRC correction for the corroborated case (the
  accepted T-219 trade; ADR-032). Shared `_yt_supports` / `_dominant_match` helpers keep it bit-identical to
  the gate. Code-review's 5 findings all addressed.
  - **Acceptance compare PASSED** (16-track live corpus, ADR-030 bar): **~20% faster on fast-pathed tracks
    (5.4s/track saved)**, 9/16 fast-pathed, **outcome-neutral** — the 3 land/park flips are MB-503 noise, at the
    same floor a same-code `control` run produced (2/16, different tracks). Rebuilt harness lives at repo root
    (**uncommitted scratch**): `t219_compare.py` (`build`/`run`/`control`), `t219_corpus/` (YouTube rips — do
    NOT commit), `t219_results.json`, `t219_report.html` (published as an Artifact). Compare ran in-process
    against isolated temp libs — the real Jellyfin library was untouched.
  - **Left uncommitted on purpose:** the `t219_*` scratch + corpus, the pre-existing `README.md` "Run in WSL"
    edit, `.vscode/`. A `--reload` uvicorn is still live on **:8137** (real DB — DB-pollution trap per `/verify`).


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
- **The bottleneck now:** T-208 killed the call-count (11→2), T-210 capped the latency tail, **T-219 removed
  the LLM from the corroborated majority (measured ~5.4s/track saved, 9/16 tracks)**. The T-21x speed series
  is done; **T-035** (coverage) is what's left of the lever set. Remaining steady floor is transcode + the
  senses on the *non*-corroborated tracks that still reconcile.
- **muziktest head-to-head (2026-08-24, same 14-track playlist):** Lever B ~**8× faster** wall-clock
  (~69s vs ~551s), same 10/4 split, both embed art. **Complementary fingerprint coverage** — AcoustID got
  Tower of Power, Shazam got Franklin; neither dominates. Gap is **closable in cleanmuzik w/o a rewrite**:
  T-208 (done) + T-210 + T-219 + T-035. Full comparison recorded in **T-218**.
- **On `main`:** T-219 merged + about to push; **756 green on `main`**. **R2.5** (migrate/clean) is still the
  designated next *release*. **Roadmap R3 line still stale** (Navidrome pivot reshape pending — owner edit).

## ⟹ NEXT

1. **T-035 — Shazam fallback fingerprint tier** — the coverage sibling now that the T-21x *speed* series
   (T-208 + T-210 + T-219) is all in. Converts AcoustID-miss parks like Franklin into lands; still unstarted.
   Engine-touching → T-208's acceptance bar (the `t219_compare.py` harness generalizes to it).
2. Also unstarted, non-engine: **T-214** (narrate freeze), **T-217** (debounce scan). Also open: **T-210
   rate-limiter/ISRC half** (correctness — shared MB limiter, Pa Salieu ISRC) · a small **T-208 follow-up**
   (review nits: chroma thin-length rounding, unbounded `_chroma_recording_meta`, misleading resolve log).
   NB: the acceptance run surfaced a **live MB 503 storm** making land/park noisy for any engine — a T-210
   correctness-half signal, not a T-219 issue.
3. Bigger: reshape **roadmap R3** (Navidrome) · start **R2.5** (migrate/clean — fingerprint dedup is its spine).

## Recent sessions (rolling — last 2–3)

- **2026-08-25 (this session)** — **Built + integrated T-219** (corroboration fast-path, ADR-032, 756 green
  on `main`). Reviewed (5 findings closed, incl. two shared helpers `_yt_supports`/`_dominant_match`).
  **Rebuilt the acceptance harness** (`t219_compare.py` — build/run/control) and ran a 16-track live compare:
  ~20% faster on fast-pathed tracks, 9/16 fast-pathed, outcome-neutral (flips = MB-503 noise, proven by a
  same-code control). Published a compare-report Artifact. Merged to `main`, ledger synced. Solo (Opus).
- **2026-08-24** — **Built T-208** (winner-only MB fan-out collapse; `mb_thin.py`, ADR-030,
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
