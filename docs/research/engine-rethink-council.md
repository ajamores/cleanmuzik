# Engine Rethink — Architecture Council Recommendation

> **Companion to `llm-reconciler-vs-beets.md`.** That file was the first spike research (conservative
> verdict: cross-check gate is the load-bearing fix). This file is the follow-on **council** run
> 2026-08-09 after the owner pushed past that verdict — brief: *"what is the best possible engine if
> the LLM is the brain, ShazamIO + yt-dlp are the senses, and neither rebuild-time nor third-party
> libraries are constraints?"*
>
> **Status: recommendation, not ratified.** The spike (§5) is the go/no-go. The three ADRs this
> calls for are **proposed, pending the spike** — do not treat them as binding yet.
>
> **Provenance:** 11-agent council (5 lenses, each skeptic-tested, + synthesis). One lens
> (identification-accuracy) failed its structured-output contract and dropped; its substance
> (hallucination/grounding) was covered by the other four. Synthesis ran on four lenses.

---

## The one-line finding

Four lenses, four entry points, **one answer**: don't rewrite the engine. Keep beets as the
writer/organizer and MusicBrainz as the source of facts; give the LLM the two jobs it's actually
good at — **adjudicating identity among candidates the fingerprint already produced**, and
**authoring the opinion layer (genre/mood/style)** — and add Shazam as a fail-soft ID input, never
a verdict. This is a **matcher swap, not an engine rewrite.**

Why not full removal: beets' load-bearing job was never matching — it's the invisible plumbing
(NTFS-via-WSL path sanitization on `/mnt/c`, `%aunique` collisions, the dedup catalogue, and the
`ImportSession` scaffold that ADR-009/010/015 + T-029 already hardened over four review rounds).
Removing it spends the two highest-risk rebuilds in the repo to gain nothing the existing
`_forced_match` seam already gives for free.

---

## 1. Recommended architecture

| Stage | Owner | Change from today |
|---|---|---|
| **Download** (`download.py`) | yt-dlp | Stop discarding the `info` dict at ~line 299. Surface a small `SourceSignals` blob (`title`, `uploader`, `channel_is_topic` from the `- Topic` suffix, description head, tags, duration, `video_id`) up through `run_pipeline` into the session. Today only `--embed-metadata` tags survive. |
| **Transcode / fingerprint** | ffmpeg / Chromaprint | Logic unchanged. Becomes parallel-eligible (§2a). `fingerprint_dominance` **stays** — the AcoustID score is the one audio signal the LLM has no substitute for. |
| **Shazam** (new `app/shazam.py`) | ShazamIO | Best-effort `{artist,title,isrc,genre}` under ADR-019's three conditions. One more LLM input; **never auto-lands.** |
| **Identify / adjudicate** (`import_seam.py :: choose_item`) | **LLM** | Replace the bare `_matching_candidate` + `SCORE_MIN` boolean with `llm_adjudicate(signals) -> Verdict`, injected like `dominance_fn` (so tests stay offline). Two modes below. `_matching_candidate` **survives as a hard veto.** |
| **Apply / organize / dedup / write** (beets) | **beets — unchanged** | The load-bearing invisible competence. Do **not** rebuild. |
| **Facts** (recording MBID, credit, ISRC, year via ADR-014) | **MusicBrainz — unchanged** | The LLM never authors these; it will hallucinate every one, and R1 dedup + T-037 rest on a *real* MBID. |
| **Enrich — opinion layer** (new `app/enrich.py`) | **LLM** | Drop `lastgenre` from `PLUGINS` (`beets_engine.py:52`). Author `genre` + `mood`/`style` as a post-run tag write in `finalize_outcomes`, mirroring `_stamp_original_year`. Constrained to an owner-curated enum **with an explicit `uncertain` member** (§4). |
| **Art / lyrics** (`artwork.py`, LRCLIB) | **unchanged** | Already hand-rolled art; LRCLIB synced lyrics have no LLM substitute. |

### The two adjudicator modes — this split *is* the safety story

- **VETO/CONFIRM on the auto-land path.** The LLM may only **CONFIRM** the fingerprint's own top
  recording or **VETO-to-park**. Structured output with `chosen_mbid` **enum-constrained to the
  supplied candidate MBIDs**. Accept iff `dominance.top_score >= score_min` **AND**
  `verdict == "accept"` **AND** `chosen_mbid == dominance.top_recording_ids[0]`. Any divergence →
  park, carrying `contradictions[]` onto the review row. The LLM **may never override to a
  recording the fingerprint didn't return** — veto-to-park is worst-case-equals-today;
  override-to-different is how it corrupts a match the fingerprint got right. Catches both live
  fixtures (Pa Salieu; Strawberry Swing).
- **CHOOSE-AMONG on the park/rescue path.** The LLM ranks the candidate list for the review card
  and writes a real reason/contradiction string — replacing `guess_terms()` dash-splitting and
  turning today's "25 results, all wrong" dead-end into a ranked, annotated, one-click card.

### The clean seam that makes this cheap

An LLM-accept hands `chosen_mbid` to the **same** `ResolveSession._forced_match` / `resolve_import`
machinery the owner's manual resolve already uses (`import_seam.py:1102`). An LLM-accept and a
human-resolve become mechanically identical code. That reuse is why this is a matcher swap.

**Position on full-removal vs hybrid: hybrid, decisively.** Narrow ADR-005; do not reverse it.

---

## 2. The three decisions (proposed — pending spike)

**(a) Reopen ADR-001 (sequential)? — YES, narrow; do not repeal.** Rewrite as a per-stage
constraint: **download** pool 1–3 with delays/jitter preserved, **transcode/fingerprint** parallel
to cores, **identify** fans out for LLM/Shazam while AcoustID/MusicBrainz queue on their own
limiters, **land strictly pool = 1**. Record a *new* ADR for the land-serialization seam — the
moment there's a second worker, `choose_item`'s live dedup (ADR-009) double-lands.

> **MEASURED CORRECTION (2026-08-09, two real songs via the isolated server).** The council (and an
> earlier line in this doc) framed download as the owner's speed pain. **That is wrong — measured.**
> Per-stage wall clock: Nines "Franklin" (parks) — download 2.71s / transcode 3.98s / **identify
> 10.96s (62%)**. Rick Astley (auto-lands) — download 2.02s / transcode 4.44s / **identify 36.20s
> (85%)**. Download is the *smallest* stage. The bottleneck is **identify ("inspect")**, and it is
> worse on auto-land because that path also does the enrichment fan-out (MusicBrainz year lookup per
> ADR-014, Last.fm genre, Cover Art Archive, LRCLIB lyrics) on top of fingerprint + AcoustID + MB
> match. **Implication:** parallelizing downloads buys almost nothing; the real lever is overlapping
> **identify/land across tracks** and/or parallelizing the *independent* enrichment calls *within*
> identify — but MusicBrainz's own 1.0/sec limiter is a serial floor on the MB portion (R4 already
> flagged this floor; the correction is that identify, not download, is where the time actually goes).
> Not yet measured: the sub-breakdown *inside* identify (fingerprint vs AcoustID vs MB-match vs each
> enrichment call) — the next instrumentation step before designing the concurrency model.

**(b) Reopen ADR-005 (beets-is-engine)? — NO; narrow it.** Split its two halves. "beets is the
*identification* engine" reopens (LLM takes it). "beets is the *writer/organizer*" must **not**
reopen — the hard-to-rebuild half. Superseding ADR: *"the LLM adjudicates identity (veto/confirm)
and authors genre/mood; beets + MusicBrainz remain the engine of record."*

**(c) Pause or reshape R2? — Neither; sequence around it.** R2's batch/backfill data model
(`playlists` table, `job.playlist_id` FK, `position`, exact-`video_id` dedup, one batch SSE stream)
is orthogonal to the engine — proceed with its two prerequisite ADRs now. Land the LLM adjudicator
as a flagged **R1.5** between R1.1 and R2, measured on the parked queue + the two live fixtures,
before the batch multiplies a systematic mis-verdict.

---

## 3. Where agents earn their place

A single structured Haiku call is correct for the mainline. An **agent** (tool-using, multi-step
loop) earns its place in exactly **one** spot: **the human-triggered re-search rescue path**
(ADR-020 exit 1 / deferred T-034/T-035). Give an LLM a `musicbrainz_search()` tool bound to beets'
existing rate-limited MB client and let it loop: hypothesize from the messy title, search, read
hits, reformulate, converge — then hand its candidate set to the choose-among call. **Bound it
hard:** cap iterations, reuse the 1.0/sec limiter, keep it human-triggered on the review card,
never auto-fired per track. Everywhere else, an agent is over-engineering.

---

## 4. The load-bearing risks

**R1 — Override-to-wrong-recording (the go/no-go).** An unconstrained LLM "reconciles" a *correct*
AcoustID match toward a wrong textual identity — strictly worse than today. *Containment is
structural:* veto/confirm mode forbids returning any recording the fingerprint didn't produce;
`chosen_mbid` enum-constrained; `_matching_candidate` stays a hard veto. Spike metric (b) is the
kill switch.

**R2 — Auto-landing on invented LLM confidence re-arms the ADR-006/010/011 wound.** *Containment:*
the LLM may only **raise** the bar to park (veto), never **lower** it to land what the fingerprint
gate would have parked. No LLM confidence number is ever written to the review row or the accept gate.

**R3 — Genre confident-wrong on contested micro-genres.** drill / road-rap / grime / afroswing /
dancehall all post to the same channels ("GRM Daily", "Link Up TV") — the channel identifies the
*scene*, not the *sub-genre*. A forced enum with no "don't know" state converts Last.fm's honest
blank into a confident wrong fill. *Containment:* the enum **must include an explicit
`uncertain`/`unsorted` member**; keep Last.fm demoted to a *witness* (one input), not deleted; the
genre write is fail-soft (blank on error) and deterministic (temp 0 + cache keyed by recording MBID).

**R4 — The concurrency "free lunch" is not free.** Today's serial processing *incidentally* spaces
downloads; pipelining removes that spacing and may trip throttling the current architecture never
provoked. *Containment:* the download pool keeps **explicit** delays/jitter as a first-class
rate-limiter; the spike instruments real throttling before any fan-out ships. Honest ceiling:
parallelism speeds download/transcode/fingerprint/LLM but **not** the MusicBrainz apply — the
1.0/sec limiter is a serial floor.

**Residual (owned, not solved) — covers/edits over an original master.** Strawberry Swing, the
Nines music-video edit, most of *nostalgia, ULTRA*: the audio genuinely *is* the original, so the
fingerprint is "correctly wrong" and the LLM can't hear the difference. Belongs to ADR-020's manual
exit — a **prerequisite** of this rewrite, not an alternative.

**Honest headline:** a well-built adjudicator will likely *raise* park count (its only safe
auto-land move is veto-to-park). But **count is not labor.** Choose-among + Shazam rescue turns
empty/wrong parked cards (a minute-plus of manual MB re-searching each) into ranked one-click
confirmations — ADR-019 measured Shazam rescuing 4/5 of the real parked queue. Total review
*minutes* fall even as *cards* tick up. **Measure minutes, not cards.**

---

## 5. The spike plan (before committing the rewrite)

**This is now an accuracy AND speed test** — the 2026-08-09 measurement (§2a) proved *identify
("inspect")* is the bottleneck (62% of a park's wall clock, 85% of an auto-land's), not download.
That reframes the LLM-forward path: it is not only an accuracy/richness play, it is potentially a
large **latency** win, because it deletes the slow serial lookup chain (AcoustID + MusicBrainz
match at 1/sec + MB year at 1/sec + Last.fm) and collapses it into one ShazamIO call (which returns
artist/title/**ISRC**/genre/**art URL** at once) + one Haiku call (genre/mood = *zero* extra
network). What still needs the network — cover-art *bytes* and synced *lyrics* — goes to different
servers and parallelizes; neither sits behind MusicBrainz's 1/sec floor. The open question is
whether ShazamIO's *own* (unknown, undocumented) rate limit becomes the new floor, and whether one
audio ear (Shazam alone, no AcoustID cross-check) stays accurate enough. Both are measured below.

Runs **offline against `TestClient`** per `/verify` isolation (isolated `DB_PATH` + temp beets
library; `pgrep -af uvicorn` first). Total LLM cost ~$0.05–0.20. Corpus: **~30–50 of the owner's
real rips** — current parked queue + landed files, spanning drill/grime/afroswing/road-rap/dancehall,
Topic and non-Topic, plus the two live fixtures (Pa Salieu "Frontline", Frank Ocean "Strawberry Swing").

**Measured baseline (2026-08-09, two real songs via the isolated server), to beat:** identify stage
= **10.96s** (Nines "Franklin", parks) / **36.20s** (Rick Astley, auto-lands). Download 2–3s,
transcode ~4s in both. Sub-breakdown *inside* identify (fingerprint vs AcoustID vs MB-match vs each
enrichment call) is **not yet instrumented** — experiment 7 does that and gives the head-to-head.

| # | Experiment | Method | Pass / fail signal |
|---|---|---|---|
| **1** | **Adjudicator go/no-go** | Inject `llm_adjudicate` as `dominance_fn` is injected. One structured Haiku call/item, `chosen_mbid` enum-constrained, fed real `SourceSignals` + AcoustID candidates + best-effort Shazam. | **(a)** Does it VETO Pa Salieu? *(the win)* **(b) Does it EVER override a correct dominant fingerprint? Must be `0`. Non-zero = STOP.** |
| **2** | **Candidate-ceiling check** | On non-Topic rips, count how many have the correct recording in beets' candidate set at all. | Large fraction with **no** correct candidate → the swap is "safer veto," not "autonomous ID." Scope calibration, not a fail. |
| **3** | **Review-labor, not count** | On ~10 real parks: how many cards flip to "correct answer ranked #1"; and **wall-clock owner-seconds-per-card before vs after.** | Park *count* may rise; **seconds-per-card must drop materially.** The only number that settles "do I review less." |
| **4** | **Genre confident-wrong rate** | ~30 tracks across the five micro-genres. Real context (MB tags, Last.fm tags, uploader + description). Haiku with enum **including `uncertain`**. Owner labels {right / defensibly-right / wrong}. | Low confident-wrong on the niche tail → net-positive. Frequent adjacent-misclassification → fix is the `uncertain` member, **not** abandoning the swap. |
| **5** | **Concurrency throttle probe** | Instrument per-stage wall-time on ~20 rips. Separately, fire ~50 back-to-back downloads from the residential IP; watch for 429/bot-checks. | If back-to-back throttles, download pool ships with mandatory delays/jitter. Confirms where real wall-time is. |
| **6** | **Shazam reliability** | Log every ShazamIO call across spikes 1/3/4; confirm pipeline stays correct when it returns nothing/wrong. | Fail-soft holds on every error path; no Shazam-derived match ever auto-lands. |
| **7** | **Inspect head-to-head (the speed arm)** | On the same ~30 songs, stopwatch two inspect paths per song: **(A)** today's beets chain (AcoustID → MB match → MB year → Last.fm → CAA → LRCLIB), instrumented per sub-call so we see which round-trip dominates; **(B)** the LLM+Shazam path (one ShazamIO call for identity/ISRC/genre/art-URL, one Haiku call, then art-bytes + LRCLIB lyrics fetched **in parallel**, and — if a real MBID/year is kept — one ISRC→MB lookup). Report wall-clock A vs B, and B's breakdown. | **B materially faster than A** (target: beat the 36s auto-land baseline by a wide margin), *and* B's own slowest call named. If B isn't faster, the latency case for the rewrite fails — say so. |
| **8** | **Shazam batch-throttle probe** | Fire ShazamIO at all ~30–50 songs **back-to-back** from the residential IP; log latency per call, any throttle/ban/empty responses, and where it degrades. | Shazam sustains a batch without opaque throttling/blocking. If it throttles, it becomes the new 1/sec-class floor — record the real safe rate, and the speed win shrinks accordingly. This is the risk that can't be reasoned, only measured. |

**Commit-to-rewrite gate:** experiment **1(b) = 0** (never overrides a correct fingerprint) AND
experiment **3 seconds-per-card drops materially** (review labor falls) AND experiment **7 shows B
faster than A** (the latency win is real, not assumed). The first two are the *accuracy/labor*
go/no-go; the third is the *speed* go/no-go the owner is betting on. Everything else calibrates scope.

---

## 6. Sequencing vs R2

1. **Now, in parallel with the spike (engine-agnostic):** author R2's two prerequisite ADRs — the
   batch/backfill data model and the T-037 canonical artist-credit normalization. Stamp `position`
   before any future fan-out; write R2's land path as the single serialization point; durably record
   `video_id` at landing (same blob `SourceSignals` now carries).
2. **R1.5 (flagged, between R1.1 and R2):** land the LLM adjudicator (veto/confirm + choose-among) +
   the Shazam input, gated on the spike. Ship the genre-enrichment swap here too *if* spike 4 passes.
   **Prerequisite:** ADR-020's manual re-search / keep-untagged exits must exist first.
3. **R2 (playlists):** proceed on the sequential model as specced. One flag for the ADR-016 design
   gate: if the concurrency narrowing lands, story 17's "one live track" card becomes "K processing"
   — a user-visible flow change that reopens the mockup gate. Treat parallelism as an R2.x/R3
   optimization layered on the single-serialization-point land, **not** an R2 blocker.

**Do not** fold the engine rethink into R2 as a hidden dependency; **do not** stall R2's data-model
work waiting on the spike. R1.5 is the seam between them.

---

### Build map (from synthesis)

Files/seams named: `download.py:~299` (surface `SourceSignals`) · `import_seam.py :: choose_item`
(inject `llm_adjudicate` like `dominance_fn`; keep `fingerprint_dominance` + `_matching_candidate`
veto) · `import_seam.py:1102 _forced_match` (reuse seam for LLM-accept) · `finalize_outcomes`
(post-run enrich write, mirror `_stamp_original_year`) · `beets_engine.py:52` (drop `lastgenre`) ·
new `app/shazam.py` · new `app/enrich.py`. **New ADRs required (pending spike):**
LLM-adjudicator-narrows-ADR-005 · land-serialization-seam-narrows-ADR-001 · genre-enum-swap ·
plus R2's two.
