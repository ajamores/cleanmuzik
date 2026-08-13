# Engine Rethink — Spike Results (ledger)

> **Companion to `engine-rethink-council.md`.** That file is the *recommendation* (LLM-as-adjudicator
> over an unchanged beets/MusicBrainz spine). This file is the *results ledger* for the spike (§5 of
> the council doc) that gates the go/no-go. Started 2026-08-09.
>
> **The three-lock commit gate:** 1(b) never overrides a correct fingerprint **AND** 3 review
> seconds-per-card drops **AND** 7 the Shazam+LLM inspect path is faster than today's beets chain.

## Test environment (established 2026-08-09)

- **Corpus: 26 distinct YouTube video IDs**, re-derived from the 48 `jobs.url` rows (the original
  parked staging files were gone — 0/15 on disk — so the corpus is *re-downloaded*, not lying around).
  Labels from best historical outcome: 23 `done`, 2 `review`, 1 `error`. 20 auto-land-eligible
  (AcoustID ≥ 0.90), 6 blank (freestyles / deep cuts). US-hip-hop-heavy; both council fixtures present
  (Pa Salieu "Frontline" id 7, Frank Ocean "Strawberry Swing" id 11).
- **Isolation:** in-process `run_pipeline`, temp `DB_PATH` + temp beets `LIBRARY_DIRECTORY` (patched in
  both modules), `JELLYFIN_API_KEY` blanked. Never touches `/mnt/c` or the real DB. Harness +
  artifacts on branch `spike/engine-rethink`, under `server/spike/`.
- **Capture run** (`server/spike/capture.py`): each song through the REAL identify path; snapshots
  `source_signals` (the yt-dlp info dict `download.py:299` discards), the MusicBrainz `candidates`, and
  the AcoustID `dominance` → `capture.jsonl`. This is the offline fixture every experiment replays
  against — capture the network once, iterate for free. Reproduced the measured baseline (first
  auto-land = 37.75s, matching the council's 36s).

## Experiment 1 — adjudicator go/no-go (lock 1b) — **PASS**

**Method.** Blinded replay: each song's evidence (`source_signals` + AcoustID score + MusicBrainz
candidates; Shazam not yet wired) handed to a **Haiku** adjudicator that sees *only* that — never the
ground-truth label or the landed identity. VETO/CONFIRM on the auto-land path; choose-among on the park
path. Three parallel Haiku sub-agents via the Claude Code harness (production-fidelity model, **no API
key** — the pipeline's own Python call is what needs a key; the harness spawning the model does not).
Verdicts scored against the fingerprint's own matched recording (`recording_mbid ∈
dominance.top_recording_ids`), **not** text.

**Result (26 songs):**

| | Count | |
|---|---|---|
| Confirmed a correct auto-land | 15 | left every genuinely-correct match alone |
| **Overrode a correct fingerprint** | **0** | the kill-switch number — **PASS** |
| Vetoed → park | 2 | both caught a fingerprint that had matched the *wrong* recording |
| Correctly parked a blank freestyle | 6 | never fabricated confidence on a 0.00 score |
| Accepted a dedup twin | 3 | harmless — the dedup layer catches these at land time |

**The marquee catch (id 7, Pa Salieu "Frontline").** AcoustID matched, at 0.994, a MusicBrainz recording
labelled *"Vanessa Bling & The Heatwave – Frontline"* — so **today's rule auto-lands it as Vanessa
Bling, the exact mistag in the live library.** The referee saw YouTube-says-Pa-Salieu vs
match-says-Vanessa-Bling, and parked it. The failure that motivated the whole rethink, reproduced on
real audio and caught by the cheap model.

**Honest wrinkles.**
- The second veto (id 17, "Mos Def – Life Is Good") is *over*-cautious: the fingerprint matched
  "DJ Deckstream feat. Yasiin Bey – Life Is Good", and **Yasiin Bey *is* Mos Def**, so that landing was
  defensible. The referee didn't know the alias and parked it — *safe* (no wrong tag, no override) but
  costs a review card. A prompt/enrich-tuning target, and grist for lock 3, not a 1b failure.
- **Scorer bug, caught and fixed (learning).** v1 of the scorer compared the referee's pick against the
  capture's `item_tags` — which are the *raw YouTube tags read before beets tags the file*, not the
  landed identity — and falsely flagged 5 correct confirmations as overrides ("GATE FAIL"). Fixed by
  scoring on recording MBID. **Lesson: `item_tags` in the capture hook is pre-tag input, never truth.**

**Caveats.** 26-song corpus (17 confident lands + 6 blanks); Shazam absent from the evidence; "today's
landing = correct" is a proxy that id 7 proves is *sometimes wrong in today's favour* (so the 2 vetoes
are correctness wins, not merely safe). Haiku, temp default, single pass.

**Verdict: lock 1b PASS.** 0/17 overrides, plus positive evidence of the win (2 real mislabels caught,
0 false-accepts on blanks).

## Experiment 3 — review labor (lock 3) — **provisionally positive** (final number needs owner)

**Method.** Choose-among mode: the 8 cards that land in the review queue under the new design (6 blank
fingerprints + the 2 referee vetoes) handed to a Haiku ranker that orders each card's candidates best-first,
writes a one-line reason, and honestly flags when *nothing* fits. Scored against the known identity from
the YouTube title. (The final seconds-per-card wall-clock is an owner-in-the-loop measurement — this
measures the *mechanism* that makes it drop: correct-answer-at-#1 rate + reason quality.)

**Result (8 cards):**

| Card outcome | Count | ids | What the owner sees now |
|---|---|---|---|
| Correct answer ranked **#1** | 2 | 6, 21 | one-click confirm (Lute – Ballad of Westside Scoop; Odeal – After the Club) |
| Right thing #1, ranker hedged | 1 | 17 | #1 is the match + reason spells out "Yasiin Bey = Mos Def" → one-click |
| **Honest-empty** ("none fit, here's why") | 3 | 2, 13, 7 | accurate "all candidates are 1960s soul covers" / "no Pa Salieu, likely false positive" — not a silent wall of 5 wrong results |
| No candidates at all | 2 | 3, 19 | unavoidable manual — freestyles absent from MusicBrainz |

**Read.** Every card got **better or honest; none got worse.** Where a correct candidate exists, it's
surfaced #1 (one-click). Where it doesn't (freestyles, the Frontline false-positive), the card now carries
an accurate *why-nothing-fits* line instead of a misleading list — the owner skips straight to Shazam /
manual re-search rather than pawing through wrong options.

**The bound (ties to exp 2, candidate ceiling).** Choose-among can't manufacture a match MusicBrainz never
returned. 5 of 8 parks are freestyles/false-positives with no correct candidate — that's the ceiling, and
**Shazam is the intended lever for exactly those** (measured later). So lock 3's labor win is real but
concentrated on cards that *have* a right answer; the freestyle tail needs the Shazam arm.

**Verdict: provisionally positive** — correct-#1 where possible, honest-empty where not, 0 cards made worse.
The hard seconds-per-card number remains an owner-timed step before the lock is fully closed.

## Experiment 6 — Shazam reliability + freestyle rescue — **PASS**

**Method.** `shazamio` (keyless) installed in an isolated Python 3.12 venv (`server/.venv-shazam`;
the app's 3.14 venv has no prebuilt `shazamio-core` wheel and no Rust toolchain). All 26 rips
re-downloaded via the app's hardened `download_song`, then recognized one-at-a-time (2s spacing).
Artifacts: `download_corpus.py`, `shazam_arm.py`, `shazam.jsonl`; audio in gitignored `spike/audio/`.

**Result.** Shazam matched **25/26**, median **1.58s** (min 1.19 / max 8.65), **0 errors** — the one
miss returned empty, never a crash. On the 20 confident auto-lands it matched all 20.

**The freestyle tail (the 6 blank-fingerprint dead-ends AcoustID couldn't touch):**

| id | YouTube | Shazam | |
|---|---|---|---|
| 6 | Lute – Ballad of Westside Scoop | Lute – Ballad of Westside Scoop | ✅ rescued |
| 19 | Jay-Z – Coming Of Age ft. Memphis Bleek | Jay-Z – Coming Of Age (feat. Memphis Bleek) | ✅ rescued (had **0** MB candidates — total dead-end) |
| 21 | After The Club | Odeal – After The Club | ✅ rescued |
| 3 | Nines – "Franklin" outro | *(empty)* | honest miss |
| 2 | Dave East – Spanish Harlem Diary #3 | 50 Cent – Ski Mask Way | ❌ wrong (heard the beat) |
| 13 | Moonwalking – Dave East | garbage | ❌ wrong |

**3/6 rescued** — including one with zero MusicBrainz candidates that was 100% manual today. The 2
confidently-wrong (Dave East freestyled over another artist's beat, so Shazam ID'd the beat) are **why
the design never lets Shazam auto-land** — as an input to the referee they contradict YouTube + the
blank fingerprint and park. Fail-soft holds.

## Experiment 7 — inspect head-to-head (lock 7) — **PASS**

**Method.** The one thing the Anthropic key unlocked: real production-path latency of one Haiku
adjudication call (`speed_haiku.py`, `claude-haiku-4-5`, reads `ANTHROPIC_APIKEY`, 12 songs). Path B's
other half (Shazam) measured in exp 6. B_identity = Shazam + Haiku; art-bytes + LRCLIB parallelize off
the critical path (different servers, not behind MusicBrainz's 1/sec floor).

**Result.**

| Path | Identity latency |
|---|---|
| **A — today's beets chain** (AcoustID → MB match → MB year → Last.fm) | **10.96s** (park) / **36.20s** (auto-land) — measured |
| **B — Shazam + Haiku** | Shazam **1.58s** + Haiku **1.37s** median ≈ **~3.0s** |

**~12× faster on the auto-land path.** The identify stage the council measured as the bottleneck (62–85%
of wall clock) collapses from the serial AcoustID→MusicBrainz lookup chain to one Shazam call + one Haiku
call (genre/mood = zero extra network). Haiku was latency-stable at 1.1–1.7s; the ~200-token system prompt
is below Haiku's cache floor so nothing cached, yet full-price input (~500 tokens) is negligible.

**Caveat.** ~3s is the *identity* decision. A fully-landed file still fetches cover-art bytes + synced
lyrics — but those are shared by both paths and parallelize, so they don't reopen A's serial floor. The
lock-7 claim is the inspect head-to-head, and B wins it by a wide margin.

**Verdict: lock 7 PASS.**

## Experiment 8 — Shazam back-to-back throttle probe — **PASS (no throttle)**

**Method.** The one B risk that can't be reasoned, only measured (council §5, exp 8): B makes Shazam a
*primary* sense called on every track, but ADR-019/exp-6 only ever paced it at 2s. `throttle_probe.py`
(3.12 Shazam venv) fired all 26 rips **back-to-back, zero spacing** from the residential IP, 30s hard
timeout per call (a hang is a finding). Artifact: `throttle.jsonl`.

**Result.** 25/26 matched, **0 throttle errors, 0 bans**; the one miss (id 3) is a genuine no-DB
freestyle, not a throttle. Latency **min/median/max = 1.28 / 1.80 / 28.45s**; **1st-half median 1.69s vs
2nd-half 1.83s — flat, not rising.** Two tail spikes (28.45s id 23, 15.93s id 24) with fast calls on
either side → network jitter, not systematic degradation. Total wall 93.8s for 26 songs.

**Verdict: PASS** — Shazam sustains B's per-track cadence on this corpus. **Two bounded caveats:** n=26,
one IP, one session (a 200-song playlist is untested); and the tail proves a **hard per-call timeout is
mandatory** (which also closes the fail-soft-covers-hangs gap the R1.5 spec review flagged).

## Experiment 9 — full architecture-B head-to-head — **B faster AND resolves mistags A can only park**

**Method.** `b_flow.py` (app venv) runs the *whole* proposed B flow per song with **real** calls:
fresh Shazam (exp 8) → **ISRC→MusicBrainz** lookup for a real recording MBID + facts (stdlib HTTP,
1/sec) → one **real Haiku reconcile** call (yt-dlp signals + AcoustID + candidates + Shazam + ISRC-MB →
`{verdict, artist, title, mbid, genre, mood}`). Timed per stage; identity scored against `answer_key.json`.
Artifact: `b_flow_results.json`.

**Result (26 songs).**

| | B (this run) | A (today, measured) |
|---|---|---|
| Identity+facts latency | **median 4.21s** (min 3.26, max 30.37 — the max is *entirely* Shazam tail) | 10.96s park / 36.20s auto-land |
| Speedup | **8.6× vs auto-land, 2.6× vs park** | — |
| Real ID via **ISRC→MB** | **12/26 (46%)**, 11 title-correct | — |
| Identity sensible | 26/26 by a *lenient title scorer* (caveat below) | 17/26 land, **id 7 MIS-lands as Vanessa Bling** |

**The finding that reframed the design (id 7, Pa Salieu "Frontline").** In A the fingerprint matches the
*wrong* recording (Vanessa Bling) and A's only safe move is **park**. In B, yt-dlp **and** Shazam both say
"Pa Salieu," so B **auto-landed the correct answer, zero clicks** — it *resolved* the mistag A can only
flag. **But it did so by trusting two text senses over the fingerprint** — the exact move ADR-021's
veto-only containment forbids. B's power (fix mistakes) and B's risk (override the fingerprint) are the
**same mechanism**; it was validated correct here at **n=1** for the override case specifically.

**Honest caveats.** (1) The 26/26 is a *title-substring* scorer — lenient: e.g. id 11 (Frank Ocean's
*Strawberry Swing*, a Coldplay cover) B labelled "Coldplay" but **parked** it, so no mis-land, but
artist-level accuracy is below 100%. B correctly parked the genuinely ambiguous ones (samples, covers,
freestyles). (2) ISRC→MB covered only 46%; the confident rest still have the **fingerprint's** real MBID,
and genuine freestyles (Nines "Franklin") have **no ID in any database** — a property of the song, not the
design. (3) One IP, one session.

> **T-209 postscript (2026-08-12).** The **4.21s** here is B's senses measured against a **pre-captured**
> AcoustID/MB fixture — it is *not* the integrated identity latency. The built pipeline runs the live
> fingerprint chain (~12s) **and** the senses on top, so end-to-end identity measured **~21s median** in
> T-209. The correctness findings (override, honest parks, fail-soft) all held; only the speed number was
> isolation-inflated. §7's speed bar was amended and **T-208** opened for intra-track concurrency.

## Gate summary

| Lock | Result |
|---|---|
| **1b** — never override a correct fingerprint | ✅ **PASS** — 0/17, caught the Frontline mistag |
| **3** — review labor drops | 🟡 mechanism proven (correct-#1 where a candidate exists; Shazam rescues 3/6 freestyles); final seconds-per-card is owner-timed |
| **7** — Shazam+LLM faster than beets | ✅ **PASS** — ~3s vs 37s, ~12× |

The two hard go/no-go locks (1b, 7) pass. Lock 3's original worry — that the referee would *raise* review
labor — is disproven directly: it parked only 2 extra songs and improved every parked card, so the
seconds-per-card measurement is confirmatory (gather it in real R1.5 use), not a build blocker. **The spike
supports committing to R1.5** — the LLM-adjudicator + Shazam-input build, still per the council's
containment (veto/confirm only, `chosen_mbid` enum-constrained, `_matching_candidate` hard veto, Shazam
never auto-lands).

## Architecture decision — B ("multi-sense reconciliation") locked in (2026-08-10)

Exp 8 + 9 reopened the A-vs-B choice the gate summary above left at "A (adjudicator) per council
containment." **Owner decision (2026-08-10): commit to B, not A.** A only *judges* the fingerprint and
parks its mistakes; B *reconciles* several senses and, when they corroborate, **resolves** them (Pa Salieu,
exp 9) — at ~4s vs ~37s (exp 9) with Shazam proven to sustain the cadence (exp 8). The two guardrails that
make B safe:

- **Rule 1 — senses vote (this SUPERSEDES ADR-021's veto-only clause).** Auto-land requires **≥2 independent
  senses** (yt-dlp title / AcoustID fingerprint / Shazam) to agree on the identity; disagreement → **park**.
  The LLM *may* now land a recording the fingerprint didn't return **iff two other senses corroborate it** —
  which is exactly why Pa Salieu resolved correctly. This is a deliberate reversal of ADR-021's "never
  override the fingerprint," recorded there as an amendment.
- **Rule 2 — facts only from a real lookup (already true; carried forward, NOT new).** The permanent ID comes
  from the fingerprint MBID or the ISRC→MB lookup; the LLM never invents one. No-ID songs (freestyles) land
  untagged and are not deduped — unchanged from today; acoustic dedup stays R2.

**Open, eyes-open:** the override-when-2-agree is validated at n=1; ISRC→MB covers ~46% (fingerprint MBID
covers the confident rest); Shazam needs a hard timeout; the 2-of-3 rule wants a wider real-use sample.
**Consequence:** the drafted `docs/r1.5/spec.md` was written for A and must be **rewritten for B** (the next
step) — its safety §5 is now the 2-of-3 rule, not veto-only.

**Beyond the gate (why this is more than a matcher swap).** A fingerprint answers only "what recording."
An LLM in that seat is a reasoning layer, which is what the PRD's "richly-tagged library" actually needs:
the genre/mood/style opinion layer (council `enrich.py`, exp 4 — untested here for lack of niche-genre
corpus), the human-triggered re-search rescue agent (council §3; deferred T-034/035), and alias/context
disambiguation the audio path structurally cannot do (the Yasiin Bey = Mos Def over-park). Scope these as
R1.5+ follow-ons; they are the upside the go/no-go doesn't capture.

## Artifacts (branch `spike/engine-rethink`)

`server/spike/`: `capture.py` (fixture builder) · `capture.jsonl` (the fixture) · `blinded.json` /
`answer_key.json` (referee input vs withheld truth) · `verdicts_{0,9,18}.json` (Haiku verdicts) ·
`score.py` (the fixed scorer) · `corpus_manifest.json`.
