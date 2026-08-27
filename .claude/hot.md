---
type: meta
title: "Hot — cleanmuzik"
updated: 2026-08-26
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

## Current State (2026-08-26)

- **T-223 DONE — built + committed to `main` 2026-08-26 (this session). 792 green on `main`.** Wave 3 of the
  T-220 epic: **beets is retired from tag-writing.** `_configure_import_options` sets import **`write` off** —
  beets still copies + organizes (by the item's applied fields), but writes no tags. New **`app/tagwriter.py`**
  (`write_tags`) writes the authoritative ID3 frames (TIT2/TPE1/TPE2/TALB/TDRC/TCON/TSRC/USLT) + an APIC cover
  with mutagen, `clear()`-ing the yt-dlp junk first (ADR-013 clean slate; `clear()` not `delete()` — a
  headerless MP3 would raise). The land tail (`finalize_outcomes`) resolves the cover (`_resolve_cover`: Shazam
  `art_url` → YouTube thumbnail **centre-cropped square** via `artwork.crop_to_square`, or CAA/iTunes for
  AcoustID-only) and writes once (`_write_landed_tags`, injected `tag_writer_fn`). Year/genre now set in-memory
  only; the writer persists them, and a write failure rolls the **year** back (F2) without un-landing (genre is
  read off disk, needs none). **KeepUntagged/ASIS re-persists post-run via `_write_landed_tags`** so ftintitle's
  feat.-split still lands (write=False coupling). beets/plugins still LOADED — teardown is T-224. Code-review's
  5 findings all addressed (headerless `delete()` = the load-bearing one). Isolated real-beets smoke confirmed
  write-off still organizes; on-disk seam tests assert ID3+APIC for Shazam / AcoustID-only / thumbnail lands.
  **Next action: build T-224** (retire beets + plugins; the epic live compare rides there).

- **T-222 DONE — built + committed to `main` 2026-08-26 (this session). 779 green on `main`.** Wave 2 (the
  HEART) of the T-220 epic: the tag/art SOURCE on a land is now the accepted identity, not a MusicBrainz
  re-derivation. **Owner-approved Option 1** (this session): Shazam is gathered ONCE per track in
  `choose_item` — **restoring it on the T-219 fast-path** (ADR-032 had it skip Shazam entirely; the cheap
  recognition returns, the expensive ISRC+LLM stay skipped; ADR-032 **amended**, ADR-033 premise corrected).
  `_resolve_tag_source` → **Shazam** when its record corroborates the landed recording (loose artist+title),
  else **AcoustID** (one `get_recording` via `_ensure_full_match`, fail-soft, no fan-out). Shazam-backed land:
  artist/album/title/isrc overridden on the applied match (so beets organizes folder-coherent with the tags),
  year/genre set in finalize, cover from `art_url`→YouTube-thumbnail (`artwork.fetch_url_image`, image-magic
  validated), **no `_ensure_full_match` MB hydration**. **Land decision, 2-of-3 gate, Frank Ocean/Coldplay
  park all UNTOUCHED.** beets still WRITES (writer swap = T-223; genre still via lastgenre until T-224).
  Code-review's 6 findings addressed. (T-223 now DONE — see above.)

- **T-221 DONE — built + committed to `main` 2026-08-26 (this session). 770 green on `main`.** Wave 1 of the
  T-220 epic: widened the Shazam §6 record with **album / year / genre** (runner `shazam_runner.py` +
  `shazam.py` normalise/`_RECORD_KEYS`/`_non_vote`), all keys always present, non-vote → Nones (fail-soft
  unchanged). album+year from the SONG section's metadata rows, genre from `genres.primary` — all already in
  the `recognize` `track` dict, so pure capture, no network. `year` extracted to a **4-digit int** (Shazam's
  'Released' can be a full date). Spec §6 amended (`docs/r1.5/spec.md`). 14 new tests (`test_shazam_runner.py`
  new + 2 in `test_shazam.py`). **Identity/voting/T-219 fast-path UNTOUCHED.** Code-review's 3 findings
  (locale label caveat, year-as-int extraction, spec drift) all addressed. **Next action: build T-222.**

- **T-220 EPIC SPEC'D + ADR-033 RATIFIED 2026-08-26. IN BUILD (T-221 done; T-222–224 remain). Base
  COMMITTED to `main` `755ab9c`.** Shazam becomes the tag+art source of record; retire beets → mutagen
  writes; one thin `get_recording` for the AcoustID-only case; genre from Shazam (LLM enum deferred to
  polish); MP3-320 held (codec = T-225, NOT yet filed — just referenced). Reverses ADR-005, supersedes R1.5
  art-via-beets. Base = `docs/backlog/T-220.md` (epic) + `T-221`–`T-224` (wave) + **ADR-033** in
  `docs/r1/adr.md` + this board + backlog README index (all in `755ab9c`; not pushed). Still uncommitted
  (intentional scratch, per /verify): `t219_*`, `mt_ab_report.html`, root `README.md`, `.vscode/`. See ⟹ NEXT.

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

## ⟹ NEXT — build the rest of the T-220 wave in order (T-221 done)

**T-220 EPIC is the active work: Shazam becomes the tag+art source of record; retire beets (mutagen writes).
ADR-033 RATIFIED 2026-08-26.** Read `docs/backlog/T-220.md` (epic, corrected frame) + **ADR-033** in
`docs/r1/adr.md` (line ~1187) FIRST — they hold the full rationale. Key correction this session: cleanmuzik
already identifies with 3 senses + Shazam-every-track + 2-of-3 vote (ADR-021/024) and already *fetches*
Shazam's tags + `art_url` every track, then **throws them away** and re-derives via MusicBrainz hydration +
fetchart. The epic is a **subtraction** — use what we already fetch — NOT a port of muziktest.

1. **T-221 — widen the Shazam record** (album/year/genre into `shazam_runner.py` + `shazam.py` §6 record).
   **DONE 2026-08-26** — pure capture, 770 green, on `main`.
2. **T-222 — tag+art from the accepted identity in `_accept`** (Shazam record + `art_url`; AcoustID-only =
   ONE thin `get_recording`, owner option 1, no fan-out). The heart. **DONE 2026-08-26** — 779 green, on
   `main`; Option 1 (Shazam every track) approved + ADR-032/033 amended. → now
3. **T-223 — mutagen ID3/MP3-320 writer + art embed** (replaces beets tag-write + fetchart). ⚠ Note: T-222
   leaves the WRITER as beets (item override + `embed_cover`); T-223 swaps to mutagen ID3 (APIC), owns the
   ISRC/lyrics write, and does the YouTube-thumbnail centre-crop-to-square that T-222 deferred. → then
4. **T-224 — retire beets + drop slow fetchers.** ⚠ **TRAP:** dedup (ADR-009) + NTFS/`%aunique` path
   sanitization lived in beets `choose_item` — carry them forward or acquire regresses. Do this LAST.
   Epic acceptance = generalised `t219_compare.py` before/after (faster, covers correct, outcomes unchanged,
   Frank Ocean/Coldplay still parks).

- **Identification is UNTOUCHED** by this epic (senses, 2-of-3, LLM adjudicator, T-219 fast-path all stand).
- **T-035 is SUPERSEDED by T-220** (its evidence — 4/5 rescue, Frank Ocean fixture — carried into ADR-033).
- **Deferred, not in this epic:** the LLM+mutagen polish pass (owner, by hand, R2.5 clean-work — genre's
  LLM curated enum re-homes there) · **T-225** codec reconsideration (MP3-320 held for now; transcoding a
  lossy YT source up to 320 buys no quality — remux-don't-reencode is the real win, separate ticket).
- Also still open, non-epic: **T-210** rate-limiter/ISRC half · **T-214** (narrate freeze) · **T-217**
  (debounce scan) · small **T-208 follow-up** nits. Bigger: reshape **roadmap R3** (Navidrome) · **R2.5**.

## Recent sessions (rolling — last 2–3)

- **2026-08-26 (this session)** — **Ran a fresh muziktest head-to-head** (A/B, per-track timed, artwork-forward
  Artifact report) → **designed + spec'd the T-220 engine-reshape epic** and **ratified ADR-033**. Key finding:
  cleanmuzik already has the Shazam senses + 2-of-3 gate + fetches Shazam art every track, then discards it;
  the epic is a subtraction (use what we fetch; retire beets/MB tag path → mutagen), not a muziktest port.
  Corrected two of my own misframes mid-session (the "port" premise; a genre-LLM that was never built). Wrote
  T-220 + T-221–224 + ADR-033 + board + README index. **Uncommitted.** Solo (Opus).
- **2026-08-25** — **Built + integrated T-219** (corroboration fast-path, ADR-032, 756 green
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
