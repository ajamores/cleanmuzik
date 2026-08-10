# R1.5 Spec — CleanMuzik (LLM adjudicator + Shazam input)

> **Status: DRAFT — 2026-08-09, pending owner sign-off.** The test of done: *an agent that has never
> seen this project could read this file and build the right thing without asking a question.* If a
> section would still make it guess, that section has a hole — fix it here, don't guess in code.

Product brief this narrows: `cleanmuzik-prd.md`. Binding constraints: `docs/r1/adr.md` (esp. the newly
ratified **ADR-021 / ADR-022**, and the standing **ADR-020**). Engine evidence: the spike ledger
`docs/research/engine-rethink-spike.md` and its design companion `docs/research/engine-rethink-council.md`.
Mistakes already paid for: `docs/learnings.md`. This spec **extends R1/R1.1** — it does not restate the
pipeline; it changes exactly one organ (the match gate) and adds one sense (Shazam).

---

## 1. Goal of R1.5

Replace R1's **bare match gate** — a `_matching_candidate` + `SCORE_MIN` boolean — with an **LLM
adjudicator** that can *catch a confident fingerprint that matched the wrong recording*, and feed it a
new best-effort ID input from **Shazam**. Nothing else about the pipeline moves: download → transcode →
identify → land → scan is unchanged, landing is still beets, facts are still MusicBrainz, and **landing
stays strictly serial**. The whole release is one sentence: *the fingerprint still proposes; an LLM now
gets a veto, and Shazam whispers in its ear.*

The gate met on the spike (lock 1b PASS: **0/17** overrides; lock 3: review-labor mechanism proven;
lock 6/7: Shazam reliable + ~12× faster). R1.5 graduates that spike harness into the real pipeline.

**Explicitly deferred to R1.6:** the genre/mood enrichment (ADR-023). It is ratified as a *decision* but
its validation experiment (exp 4, the confident-wrong rate) never ran; R1.6 opens with that experiment
and only then wires `app/enrich.py`. R1.5 does **not** touch genre. See §3.

## 2. In scope

- **`SourceSignals` surfaced from the download stage.** Stop discarding yt-dlp's `info` dict at
  `download.py:~299`. Surface a small blob up through `run_pipeline` into the import session:
  `{ title, uploader, channel_is_topic (the "- Topic" suffix), description_head, tags, duration,
  video_id }`. Today only `--embed-metadata` tags survive; this is the adjudicator's textual evidence.
- **Shazam as a best-effort ID input** (new `app/shazam.py`). One recognition call per track, returning
  `{ shazam_artist, shazam_title, isrc, matched, error }` (genre is captured if present but unused until
  R1.6). It is **one more input to the adjudicator**, never a verdict, and **never auto-lands** (ADR-019).
  Fail-soft is absolute: any error, empty, or wrong answer leaves the pipeline behaving exactly as it does
  today without Shazam.
- **The LLM adjudicator** at `import_seam.py :: choose_item`, injected the way `dominance_fn` already is
  (so tests stay offline). Two modes (§5):
  - **VETO/CONFIRM on the auto-land path** — the LLM may only confirm the fingerprint's own top recording
    or veto-to-park. It can **never** land a recording the fingerprint didn't return.
  - **CHOOSE-AMONG on the park/rescue path** — the LLM ranks a parked card's candidates best-first and
    writes a one-line `reason` + `contradictions`, replacing the dash-split `guess_terms()` ordering.
- **The Verdict is structured output**, schema graduated from the spike (§6). `chosen_candidate` is
  **enum-constrained to the supplied candidate list** — the structural half of the override guarantee.
- **`_matching_candidate` survives as a hard veto at land time** — the second, independent half of the
  guarantee (an LLM-accepted recording must still be one the fingerprint produced).
- **Landing remains pool = 1** (ADR-022). The adjudicator and Shazam calls may run per-track, but the
  land path is untouched and serial.
- **The review row carries the adjudicator's `reason` + `contradictions`** so a vetoed/parked card
  explains *why* it's there (feeds the review UI; design-gate note in §3).
- **Anthropic API key** read from the repo-root `.env` as **`ANTHROPIC_APIKEY`** (§6 — the name differs
  from the SDK default; R1.5 code reads it explicitly).

## 3. Explicitly out of scope

The fence. Tempting to fold in; deliberately *not* R1.5.

- **Genre/mood enrichment (ADR-023) → R1.6.** No `app/enrich.py`, no dropping `lastgenre`, no genre enum.
  R1.6 opens with **exp 4** (confident-wrong rate + owner-curated enum with an `uncertain` member) and
  wires the writer only if it passes. R1.5 leaves genre exactly as R1 left it.
- **Pipeline concurrency / fan-out (ADR-022's parallel half) → R2.x/R3.** ADR-022 *authorizes* per-stage
  parallelism but gates it on the throttle probes (spike exp 5/8), which **have not run**. R1.5 ships the
  serial land only. No worker pool, no overlapping identify.
- **The re-search rescue *agent*** (tool-using MB-search loop, council §3 / T-034/T-035) → later. R1.5's
  choose-among is a **single structured call** that ranks the candidates already present — it does not
  loop, search, or reformulate.
- **Writing any LLM confidence number to the review row or the accept gate** — forbidden (ADR-021 risk
  R2). The `confidence` field in the Verdict is for the `reason`/debug only; the accept gate reads the
  **fingerprint** score, never the LLM's.
- **Playlists / batches / migrate** → R2 / R2.5, unchanged by this release.
- **A new review *screen*.** R1.5 adds fields (`reason`, `contradictions`) to the existing review row.
  Because that changes a user-visible state, the review-card presentation passes the **ADR-016 design
  gate** (flat scenario screens, including the veto and honest-empty states) before component code — but
  the gate is scoped to *how the reason renders*, not a queue redesign.

## 4. User flow (what changes from R1)

The R1 flow (§4 of `docs/r1/spec.md`) is unchanged except at **the gate** (step 4) and the **review
card** (step 5):

4. **The gate (now ADR-021, was ADR-006):** after the fingerprint ranks candidates, the app gathers
   `SourceSignals` + the AcoustID score + the MusicBrainz candidates + a best-effort Shazam result and
   hands them to the adjudicator.
   - **Fingerprint dominant AND the LLM confirms it** → auto-tag and land, zero clicks — same outcome as
     R1, now with a second opinion that agreed.
   - **Fingerprint dominant BUT the LLM vetoes** (it sees YouTube-says-X vs match-says-Y) → **park**,
     carrying the `contradictions` onto the card. *This is the new behaviour* — the Pa Salieu "Frontline"
     → Vanessa Bling catch. Worst case a veto costs one review card; it can never mistag.
   - **Weak / ambiguous fingerprint** → park as before, but the card's candidates are now **ranked by the
     LLM** with a `reason` and, where nothing fits, an honest *"none of these fit, here's why"* instead of
     a silent wall of wrong results.
5. **Review card:** shows the LLM's ranked candidates + its `reason`/`contradictions`. Owner actions are
   unchanged (accept / pick alternate / reject / re-search / keep-untagged — ADR-020). A Shazam suggestion,
   when present, appears as one more labelled candidate the owner can accept; it is never pre-accepted.

Everything else — download, transcode, landing, dedup, Jellyfin scan, staging retention, failure rule —
is exactly R1.

## 5. Behaviour details

- **The accept-rule (the whole safety story).** In `choose_item`, auto-accept iff **all three** hold:
  1. `dominance.top_score >= SCORE_MIN` — the R1 fingerprint gate, unchanged;
  2. `verdict == "accept"`;
  3. the LLM's `chosen_candidate` resolves to a recording whose MBID **is in**
     `dominance.top_recording_ids` (i.e. the LLM picked the recording the fingerprint matched).

  Any divergence → park, storing `contradictions[]` on the review row. **Two independent guards make an
  override impossible:** `chosen_candidate` is enum-constrained to the supplied candidate list at
  generation time, and `_matching_candidate` re-checks recording-MBID identity at land time. A blank
  fingerprint (no dominance) with `verdict == "accept"` is a **false-accept and must never land** — it
  parks. Veto-to-park is worst-case-equals-R1; override-to-a-different-recording is the failure this
  release exists to prevent, and it is structurally unreachable.
- **The adjudicator is a single structured call.** One Haiku-class call per track, temperature 0,
  `chosen_candidate` enum-constrained. It sees *only* the evidence blob — never a ground-truth label. On
  the park path the same call shape ranks candidates and writes the reason. No tools, no loop (that's the
  deferred rescue agent).
- **Shazam is fail-soft and advisory.** `app/shazam.py` exposes one function: given the staging audio,
  return the record shape in §6 or a record with `matched: false, error: <reason>`. The pipeline calls it
  best-effort during identify; its result is *added to the adjudicator's evidence* and *offered as a
  labelled candidate on a parked card*. It is **never** written as a tag on its own authority and **never**
  auto-lands. If Shazam is unavailable (see the build risk below), the app degrades to no-Shazam and every
  other behaviour is identical.
- **LLM confidence is never load-bearing.** The Verdict's `confidence` never enters the accept gate and is
  never written to the review row as a match score (ADR-021 risk R2). The row's discriminator stays the
  fingerprint/tag `score`, as in R1.
- **Determinism + cost.** Temperature 0; one call per track on the auto-land path, one per parked card on
  the review path. Budget is trivial (spike measured ~$0.05–0.20 for the whole corpus).

### Open build seam — Shazam packaging (must be resolved in the Shazam ticket)

The spike ran `shazamio` in an **isolated Python 3.12 venv** (`server/.venv-shazam`) because the app's
3.14 venv has no prebuilt `shazamio-core` wheel and no Rust toolchain to build one. R1.5 must decide how
the *main app* invokes Shazam. Candidate resolutions (pick one, record it as an ADR):
(a) call the 3.12 venv as a subprocess boundary; (b) pin the server to 3.12 so `shazamio-core` installs
directly; (c) build/vendor the wheel. This is a real seam, not a detail — it blocks the Shazam ticket and
belongs in `docs/r1/architecture.md` once decided.

## 6. Interfaces

### The adjudicator seam (`import_seam.py`)

Injected like `dominance_fn`: `llm_adjudicate(evidence) -> Verdict`. Evidence assembled per track from
`SourceSignals`, `dominance` (AcoustID score + `top_recording_ids`), the MusicBrainz `candidates` list,
and the optional Shazam record. Offline tests inject a stub, exactly as `dominance_fn` is stubbed today.

### Verdict schema (structured output — graduated from the spike)

```jsonc
{
  "verdict": "accept" | "park",
  "chosen_candidate": <int index into the supplied candidates[]> | null,  // enum-constrained
  "confidence": 0.0–1.0,          // reason/debug ONLY — never the accept gate, never a row score
  "reason": "<one line>",
  "contradictions": ["<why the textual identity disagrees with the audio match>", ...]
}
```

`chosen_candidate` is an **index into the candidate list handed to the call**, which is what makes
"return a recording the fingerprint didn't produce" unrepresentable. In persistence and land-time checks
it resolves to that candidate's recording MBID (the value `_matching_candidate` and the accept-rule test).

### Shazam record (`app/shazam.py`)

```jsonc
{
  "shazam_artist": "JAŸ-Z",       // null if no match
  "shazam_title": "My 1st Song",  // null if no match
  "isrc": "USDJ20301465",         // null if absent — a cheap FIRST probe toward an MBID, never the bridge
  "matched": true,
  "error": null                    // populated string on any failure; matched=false
}
```

### Review row / SSE additions

The parked-review shape (R1 spec §6) gains two fields, populated by the adjudicator:

- `reason: string` — the one-line why-it's-parked.
- `contradictions: string[]` — present on a veto; empty on a plain weak match.

`track.review_required` carries them alongside the existing `candidates`. No route signatures change; no
new endpoints. (Candidate ordering in the payload is now the LLM's ranking.)

### Secrets (`.env`, git-ignored) — addition to R1's table

| Key | Needed by | R1.5 behaviour if missing |
|---|---|---|
| `ANTHROPIC_APIKEY` | the adjudicator | **Required for auto-land adjudication.** Name differs from the Anthropic SDK default (`ANTHROPIC_API_KEY`) — read it explicitly. If absent: degrade to the **R1 gate** (fingerprint-only auto-accept) with a logged warning; the pipeline still lands and parks, just without the veto/choose-among layer. |

## 7. Acceptance checklist (R1.5 is "done" when…)

- [ ] A track whose fingerprint is **dominant and the LLM confirms** auto-tags and lands with **zero
      clicks** — same outcome as R1, unchanged path.
- [ ] The **Pa Salieu "Frontline"** fixture (AcoustID matches the *Vanessa Bling* recording at 0.994) is
      **vetoed to the review queue**, not auto-landed as Vanessa Bling. The card shows the contradiction.
- [ ] The adjudicator **never overrides a correct fingerprint**: across the spike corpus (or a `/verify`
      replay of it), 0 accepts land a recording outside `dominance.top_recording_ids`.
- [ ] A **blank-fingerprint** track (score 0.0) with any LLM output **parks** — never a false-accept.
- [ ] A **parked card** shows candidates **ranked by the LLM** with a `reason`; where nothing fits, an
      honest *"none of these fit"* line rather than a silent wrong list.
- [ ] **Shazam is called best-effort** and its result appears as a labelled candidate on a parked card;
      **forcing Shazam to error leaves every other behaviour identical** (fail-soft proven).
- [ ] With **`ANTHROPIC_APIKEY` unset**, the pipeline degrades to the R1 fingerprint gate and still
      lands/parks (logged warning), proving the adjudicator is additive, not load-bearing for basic flow.
- [ ] **Landing is still serial** (pool = 1); no concurrency was introduced.
- [ ] **Genre behaviour is unchanged from R1** — R1.5 shipped no enrichment (the R1.6 fence held).

---

*Verification (per Definition of Done): the fingerprint-catch and no-override items are proven by
`/verify` replaying the spike corpus offline (isolated `DB_PATH` + temp beets library; `pgrep -af
uvicorn` first) and observing the real park/land side effect — not by "the code looks right." Transcribe
any correction to `docs/learnings.md`.*
