# R1.5 Tickets — Multi-sense reconciliation

> **Status: SIGNED OFF — 2026-08-10, from `r1.5/spec.md` (architecture B).** Decompose the R1.5 spec into
> build-order tickets. Two cold-reviews folded (spec-fidelity + drop-in buildability); the T-205 normalizer
> choice ratified (loose/containment). Ready to build. Each ties back to a §7 acceptance item. Same ticket
> format and Definition of Done as `docs/r1/tickets.md` — don't restate them; read that header. Numbering
> is the **T-2xx** series to avoid collision with R1 (T-0xx / backlog) and R1.1 (T-1xx).
>
> **How the "Done when"s trace.** The behaviour tickets (T-205, T-206, T-202) each tie to a named §7
> checkbox. The plumbing tickets (T-201, T-203, T-204) have no *standalone* §7 payoff — their §7 value
> is emergent and is proven in the **T-209 sweep**; they trace to their §2/§5/§6 spec clause instead.
> T-207 (the UI) traces to **§4/§6 + its ADR-016 design gate** — §7 has no review-card *render* item
> (it covers only persistence), so T-207's acceptance is self-contained by design (see the ticket).

**Scope guard (roadmap rule).** R1.5's scope is its §7 exit criteria. Findings surfaced while building are
captured as tickets and triaged at birth — required for §7 → here; else → `docs/backlog/`. The fence is
spec §3: **no LLM-authored genre/mood (R1.6), no Shazam art/lyrics (dropped), no pipeline concurrency
beyond serial land (R2.x/R3), no re-search *agent* (later).** Do not let any of them creep in.

**This extends R1/R1.1 — it changes only the *identity* stage and adds *senses*.** Download, transcode,
landing, enrichment (art/genre/lyrics), dedup, and the Jellyfin scan are untouched (spec §2). A parity
regression in any of them is a build failure (§7), not a trade-off.

## Build order

Three independent sense-gatherers fan out first — **disjoint file sets, clean 3-way parallel**:

- **T-201** SourceSignals (`download.py`) ∥ **T-202** Shazam (`shazam.py` + subprocess) ∥ **T-203**
  ISRC→MusicBrainz (`isrc.py`, new).

Then the spine, sequential (all in `import_seam.py`, so **not** parallel with each other):

- **T-204** reconcile seam (build evidence → validated `Verdict`) → **T-205** the 2-of-3 gate + degrade
  → **T-206** review-row persistence (`db.py` + `create_review`).

Then the UI and the pass:

- **T-207** review-card UI — **ADR-016 design gate first** (it changes a user-visible state) → **T-209**
  end-to-end verify against the whole §7 checklist. (**T-208 is a reserved slot** — held for a mid-build
  finding that closing §7 turns out to require; empty by design, not a gap.)

**T-200** (owner: `ANTHROPIC_APIKEY` in `.env`) has no dependency and should land first so T-205's
happy path is exercisable; it is a two-minute owner task, not a blocker on building the seam offline
(the reconcile call is stubbed in tests, exactly as `dominance_fn` is).

Definition of Done per ticket is the repo rule (`docs/workflow.md`): `/code-review` on the diff, the
acceptance re-read, `/verify` the real side effect for pipeline tickets, integrate onto `main` with the
status line flipped in the closing commit, transcribe corrections to `docs/learnings.md`.

---

## Setup

### T-200 — Owner setup: `ANTHROPIC_APIKEY` in `.env`
- **Status:** todo
- **Depends on:** none
- **Agent:** owner
- **What:** Owner obtains an Anthropic API key and puts it in the git-ignored repo-root `.env` as
  **`ANTHROPIC_APIKEY`** (spec §6 — note the name **differs from the SDK default** `ANTHROPIC_API_KEY`;
  it is read explicitly, mirroring how `LASTFM_APIKEY` / `acoustid_apikey` are read in `app/config.py`).
  Add the key to `.env.example` and the R1.5 row of the secrets table. Until it is set, the pipeline
  degrades to the R1 fingerprint-only gate (T-205) — **absent key is not a hard failure**, it is a
  logged, eyes-open fallback (spec §6 degrade row).
- **Done when:** `ANTHROPIC_APIKEY` is set and readable in-process (a boot log line reports `set/unset`,
  like the existing `config loaded:` line at `main.py:30`); `.env.example` documents it. (Spec §6 secrets.)

---

## Phase A — the three senses (parallel fan-out)

### T-201 — SourceSignals from yt-dlp (sense 1)
- **Status:** done
- **Depends on:** none
- **Agent:** back-end
- **What:** Stop discarding the yt-dlp `info` dict at `download.py:299`. Surface a `SourceSignals` value —
  `{ title, uploader, channel_is_topic, description_head, tags, duration, video_id, yt_artist, yt_title,
  yt_album, yt_release_year }` (spec §2) — from the already-extracted `info`, and carry it through the job
  so it reaches `choose_item` in the import seam (it is **sense 1**, the YouTube claim, and the reconcile
  call's textual evidence). `channel_is_topic` is derived from the uploader/channel being an auto-generated
  `"… - Topic"` channel; `description_head` is a bounded prefix of the description (don't ship the whole
  blob). `download_song` currently returns a bare `Path` (`download.py:321`) — widen it to return
  `(Path, SourceSignals)` (or attach the signals to the job) and thread it through `jobs.py`'s `import_song`
  call into the seam. Define the shape once (a dataclass/TypedDict) so T-204 imports it. **This is plumbing
  only — it changes no matching behaviour.**
- **Prefer YouTube's structured music fields; parse the title only as a fallback.** For official / `"- Topic"`
  uploads, yt-dlp returns clean structured fields — `info.get("artist")`, `info.get("track")`,
  `info.get("album")`, `info.get("release_year")` — which beat splitting the raw title string. Resolve the
  two **voting** fields T-205's code comparison needs:
  - `yt_artist` ← `info["artist"]` if present; else parse `"Artist - Title"` out of `title` reusing
    `app/normalize.py`'s leading-`Artist -` split (T-006); else the Topic **uploader** (`"Artist - Topic"`);
    else `None`. When `None`, T-205 treats `yt` as unable to support any candidate (conservative → parks).
  - `yt_title` ← `info["track"]` if present; else the parsed title; else the raw `title`.
- **`yt_album` + `yt_release_year` are JUDGMENT-ONLY evidence for the AI — never a written fact, never in
  the code vote.** They ride in `SourceSignals` (and so into the reconcile evidence, with `description_head`
  + `tags`) to help the LLM *pick the right candidate*. They are **not** used by T-205's 2-of-3 code check
  and are **never** written to the file — YouTube's `release_year` is the *upload* year and its `album` is
  often a `"- Topic"` auto-album, so the written facts still come only from MusicBrainz/ISRC (spec §5,
  facts-from-a-real-lookup). This is the "use everything to judge, write facts only from MusicBrainz" rule.
- **Done when:** (a — closes here) a unit test asserts the field mapping from a captured `info` fixture:
  the structured-field path (`info["artist"]`/`["track"]` present → used directly), the title-parse
  fallback (`"Artist - Title"`), the Topic-channel fallback, and a bare-title case → `yt_artist=None`; and
  that `yt_album`/`yt_release_year` are carried but flagged judgment-only. Every field present (empty/`None`
  where yt-dlp is silent, never missing). (b — exercised once T-204 lands) the populated `SourceSignals`
  arrives at `choose_item`. (Spec §2 SourceSignals; §6 reconcile evidence.)

### T-202 — Shazam sense via isolated 3.12 subprocess (sense 3) + ADR
- **Status:** done
- **Depends on:** none
- **Agent:** back-end
- **What:** Add `app/shazam.py`: one recognition call per track → the §6 Shazam record
  `{ shazam_artist, shazam_title, isrc, art_url?, lyrics?, matched, error }`. Because the app's 3.14 venv
  has no `shazamio-core` wheel, **invoke `shazamio` as a subprocess against the existing 3.12
  `server/.venv-shazam`** (spec §5 "Open build seam") — a process boundary that quarantines the
  reverse-engineered dependency (ADR-019's accepted risk) and can be **killed on timeout** without touching
  the worker. Own the subprocess contract: the I/O shape (audio path in → JSON record out) and
  kill-on-timeout. **Hard wall-clock timeout (default 8s, tunable)** maps a hang → `{matched:false,
  error:"timeout"}` — a hang is not "unavailable"; on the serial pipeline it would otherwise block every
  later track (exp 8 saw ~28s tail spikes). Any error/empty/timeout ⇒ Shazam is a non-vote (T-205 drops
  `sz`); it is **never** written as a tag on its own authority. **File a short ADR (next free number)
  covering BOTH decisions:** (a) subprocess-against-3.12 chosen (pin-3.12 / vendor-wheel are documented
  fallbacks only), and (b) **the per-track widening of ADR-019** — Shazam now runs on *every* track, not
  only on an AcoustID miss ("backup tier"). The widening is authorized by spec §2 (safe only under the
  serial pipeline) but reverses ADR-019's tier order, so the repo's no-silent-reversal rule requires it be
  recorded. **Capture `art_url`/`lyrics` in the record but write neither** (spec §3 — dropped; art/lyrics
  land via the existing beets path).
- **Done when:** a known track returns a populated `matched:true` record with an ISRC; a forced Shazam
  **error** and a forced **hang** both return `{matched:false, error:...}` within the wall-clock cap with
  the worker unblocked; the ADR is filed. (Spec §5 fail-soft + hard timeout; §7 fail-soft + timeout item.)

### T-203 — ISRC → MusicBrainz fact lookup
- **Status:** done
- **Depends on:** none
- **Agent:** back-end
- **What:** Add `app/isrc.py`: one exact lookup `GET /ws/2/isrc/{isrc}?fmt=json&inc=artist-credits`
  (User-Agent **required**, 1 req/sec — respect ADR-001's rate limit, shared with MusicBrainz) → the real
  **recording MBID + artist + title**, or `None` when the ISRC does not resolve (the ~54% gap). This is the
  **only** network floor B keeps on the identity path (spec §6) and the sole source of a *real* MBID for the
  Pa Salieu correction. Injectable (a plain function T-204 can stub offline), fail-soft (network error →
  `None`, treated as "no ISRC entry"). **It authors nothing** — it returns what MusicBrainz says or nothing.
- **Done when:** a real ISRC resolves to a real recording MBID + artist/title (offline test uses a
  captured MB response); an unresolvable/garbage ISRC returns `None`; the call sets a User-Agent and does
  not exceed 1/sec. (Spec §5 facts-from-a-real-lookup; §6 ISRC→MusicBrainz.)

---

## Phase B — the reconcile spine (sequential; all in `import_seam.py` + `db.py`)

### T-204 — Reconcile seam: inject the three fns, build augmented candidates, return a validated `Verdict`
- **Status:** done
- **Depends on:** T-201, T-202, T-203
- **Agent:** back-end
- **What:** Extend `FingerprintTrustSession` (`import_seam.py:434`) with three constructor params
  **alongside** the existing `dominance_fn` (`:452`), each stubbable offline exactly as `dominance_fn` is:
  `source_signals` (T-201's blob for this track), `shazam_fn` (T-202, called once per track, hard-timeout),
  and `reconcile_fn(evidence) -> Verdict`. In `choose_item` (`:477`), the order is: existing `dominance_fn`
  → `shazam_fn` → **build the augmented `candidates[]`** = beets' MusicBrainz candidates **++** a synthetic
  entry for the **ISRC→MB recording** (T-203) *iff* the Shazam ISRC resolves. Each entry carries
  `{ n, artist, title, mbid, source }` with `source ∈ {"musicbrainz","isrc"}` and **`mbid` from a real
  lookup only** (spec §5). Order is **canonical and fixed** — serialized identically into the prompt and
  reused for index resolution and persistence, so an index never resolves against a different order than
  the LLM saw. Call `reconcile_fn` at **temperature 0**, one call per track, structured-output-constrained
  to the §6 `Verdict` schema; `chosen_candidate` is an **enum over the present `n` values** (or `null`) —
  there is **no free-text identity field**. **Drop any `confidence` field at this boundary** before the
  Verdict travels further (spec §5 — confidence is never load-bearing). The Anthropic key is
  `ANTHROPIC_APIKEY` (T-200). **This ticket produces the augmented `candidates[]` + a validated `Verdict`;
  it does not itself land or park** — that is T-205. Evidence passed = `SourceSignals` + `dominance`
  (`top_score` + `top_recording_ids`) + augmented `candidates[]` + the optional Shazam record.
- **Structured-output mechanism (don't invent it, and don't copy the spike).** Use Anthropic **tool-use
  with a forced `tool_choice`** on a single `record_verdict` tool whose input schema is the §6 `Verdict`,
  with `chosen_candidate` built **per-track as an `enum` of the present `n` values + `null`** and `ranking`
  an array over the same values — so the model can only point at a real-MBID entry by index. Consult the
  **`claude-api` skill** for the current SDK call shape (model id, tool-use, `tool_choice`) rather than
  guessing. **⚠️ Do NOT copy `spike/b_flow.py`** — its schema is *free-text* `{artist,title,mbid,…}` parsed
  with a regex and lets the **LLM author the MBID**, the exact thing this spec forbids (spec §5, no
  free-text identity). Reuse its **ISRC lookup** (`isrc_to_mb`, now T-203) and its normalizer idea (T-205),
  but author a **fresh index-selection system prompt** here — the spike's prompt is the forbidden shape.
- **Done when:** with stubbed `shazam_fn`/`reconcile_fn`/ISRC resolver, `choose_item` builds the augmented
  candidate list (including the synthetic ISRC entry when the ISRC resolves, and **not** when it doesn't),
  passes the fixed-order evidence to `reconcile_fn`, and returns a schema-valid `Verdict` whose
  `chosen_candidate` indexes into that exact list; a returned `confidence` is stripped before it leaves the
  seam. Offline (no network). (Spec §5 augmented candidates; §6 reconcile seam + Verdict schema.)

### T-205 — The 2-of-3 accept gate + degrade fallback (the safety spine)
- **Status:** done
- **Depends on:** T-204
- **Agent:** back-end
- **What:** Consume T-204's `Verdict` + augmented `candidates[]` + the three senses, and decide land-vs-park
  — replacing R1's `_matching_candidate + SCORE_MIN` boolean. **Presence (spec §5):** `yt` always present;
  `fp` present **only** when `dominance.top_recording_ids` is non-empty; `sz` present **only** when Shazam
  `matched`. **Support (spec §5):** `fp` supports `candidates[chosen]` iff `candidate.mbid ∈
  top_recording_ids`; `sz` iff the candidate is the ISRC-sourced entry **or** Shazam (artist AND title)
  normalized-match it; `yt` iff yt (artist AND title) normalized-match it (using T-201's `yt_artist`/
  `yt_title`; when `yt_artist is None`, `yt` supports nothing). **The gate RE-DERIVES `agreeing_senses` in
  code** — intersect the LLM's proposal with *present* senses, re-check support, and use the
  **code-validated** count, never the raw LLM number.
- **DECISION — how "normalized-match" is computed (owner RATIFIED 2026-08-10: loose/containment).**
  The spec leaves the normalizer unspecified, but the §7 acceptance cases (Pa Salieu lands, Strawberry
  Swing parks) are *exactly* the exp-9 cases, so match the code that produced them: **port
  `spike/b_flow.py:43`'s normalizer** — alnum-fold `re.sub(r"[^a-z0-9]", "", s.lower())` — into a shared
  `app/` helper, and compare with the spike's **substring-containment** test (not strict equality), applied
  to **artist AND title** independently. Owner ratified containment over strict equality (2026-08-10): it
  catches YouTube's extra-word cases (`(Official Video)`, `feat.`) that equality would wrongly park, and
  the 2-of-3 rule covers its short-name false-match risk (a lone loose match auto-lands nothing).
  **A sense supports a candidate only if BOTH its
  normalized artist and normalized title match the candidate's** — this is what parks Strawberry Swing
  (yt-artist "frankocean" ⊄ candidate "coldplay"). **Auto-land iff ALL hold:** (1) `verdict ==
  "accept"`; (2) code-validated agreeing count, from present senses only, **≥ 2**; (3)
  `candidates[chosen].mbid` non-null. Any failure → **park** carrying `reason` + `contradictions` (persisted
  by T-206). An accepted `recording_id = candidates[chosen].mbid` lands via the **same**
  `_forced_match`/`resolve_import` machinery a manual resolve uses (`import_seam.py:1102`) — no new landing
  path. **Reconcile-call failure** (timeout/5xx/non-schema) → park with `reason:"adjudication unavailable"`,
  never a silent land. **Degrade:** `ANTHROPIC_APIKEY` absent **or** rejected (401/expired) → fall back to
  the **R1 fingerprint-only gate** with a logged warning (spec §6 degrade row — a stale key degrades, it
  does not park every track; a mid-run *transient* failure on a valid key still parks that one track).
  **Must-not-happen (spec §5):** a lone agreeing/present sense lands; Shazam is ever the *sole* agreeing
  sense; an LLM-authored MBID is ever written.
- **Done when:** fingerprint+Shazam(+yt) agreeing → auto-land (R1 happy path); fingerprint dissents but
  yt+Shazam support the ISRC candidate → **lands the correction** (Pa Salieu, real MBID from ISRC); only
  one sense present/agreeing → **parks**; Shazam alone never lands; a real-but-wrong ISRC (Strawberry Swing:
  yt="Frank Ocean", sz="Coldplay") **parks** (< 2 agree on artist AND title); forced reconcile failure
  parks; `ANTHROPIC_APIKEY` unset falls back to the R1 gate and still lands/parks (logged). All offline
  with stubs. **One test must prove the code re-derivation is load-bearing:** feed a stub `Verdict` whose
  `agreeing_senses` claims 2 agree while the *senses themselves* support only 1 (an over-eager LLM) → the
  gate **parks** on the code-validated count, not the LLM's. (Without this, a builder can stub `reconcile_fn`
  to return `agreeing_senses:["yt","fp"]` and pass every other case while never writing the re-derivation
  that is the whole safety point.) (Spec §5 the 2-of-3 rule; §7 happy-path, override, vote-holds,
  no-invented-facts, reconcile-parks, degrade.)

### T-206 — Review row: persist `reason` + `contradictions` + LLM-ranked candidate order
- **Status:** done
- **Depends on:** T-205
- **Agent:** back-end
- **What:** Persist the park discriminators so they **survive a restart** (ADR-010's lesson — a
  discriminator that lives only in the live SSE event is unimplementable after a restart). Add columns via
  the existing additive-migration list `db.py:_ADDED_COLUMNS` (**not** a `CREATE TABLE` edit — that is a
  no-op on the owner's live DB): `("reviews","reason","TEXT")`, `("reviews","contradictions_json","TEXT")`.
  Reorder `candidate_ids` by the Verdict's `ranking` **before** `create_review` (`import_seam.py:758`), so
  the persisted order already reflects the LLM ranking and a restart re-hydrates it in that order.
  Reordering `candidate_ids` is order-safe **because `candidate_scores_json` is an MBID-keyed map, not a
  parallel array** (`db.py:20-21`, `import_seam.py:764`) — it cannot drift when the ID list is reordered,
  so no second reorder is needed there. `track.review_required` carries
  `reason` + `contradictions` alongside the (ranked) candidates. **No route signatures change** (spec §6).
- **Done when:** a parked card's `reason`, `contradictions`, and ranked candidate order are written to
  SQLite and **survive a backend restart** (read back via `GET /api/reviews`); the `_ADDED_COLUMNS` path
  applies the columns to a pre-existing DB. (Spec §6 review-row additions; §7 persistence item.)

---

## Phase C — UI

### T-207 — Review card: reason, contradictions, Shazam hint, LLM-ranked candidates
- **Status:** done
- **Depends on:** T-206
- **Agent:** front-end
- **Design gate (ADR-016) — BEFORE component code.** This changes a user-visible **state** (what the
  review card shows), so it passes the design gate first: flat HTML scenario screens, **one per scenario
  including failure/edge states** (weak-match park with `reason` + `contradictions` + ranked candidates;
  park carrying the ISRC→MB synthetic candidate — how Shazam surfaces, ADR-019, **no standalone hint**;
  reconcile-unavailable park — `reason:"adjudication unavailable"`, no contradictions; candidate-less park →
  re-search / keep-untagged; and the two states that show **no card** — override auto-landed and degrade-mode
  land), published for owner sign-off. Runs *ahead of* the DoD, not inside it (`docs/workflow.md`).
- **Acceptance is self-contained (no §7 item).** §7 has no review-card *render* checkbox — it covers only
  persistence (T-206). So this ticket's exit criterion is **its own**: the ADR-016 screens signed off, then
  each persisted field observed rendering in a real browser (below). *(If the owner later wants a formal §7
  render item, that's a one-line spec §7 amendment — flagged, not assumed here.)*
- **What:** The review card renders the persisted (T-206) `reason` and `contradictions`, and shows
  candidates in **LLM-ranked order**. A Shazam suggestion surfaces only where it **already** reaches the
  card — the ISRC→MB synthetic candidate and the `contradictions` text; the **standalone Shazam hint is
  deferred (T-212)**, so no new payload field and no Shazam-specific control here. Owner actions are
  unchanged (accept / alternate / reject / re-search / keep-untagged). **Do not render LLM confidence** (it
  never reaches the row) and do not print raw scores as a verdict (T-017's lesson — the discriminator stays
  the fingerprint/tag `score`).
- **Done when:** the design screens are signed off; then a parked card shows its `reason`, contradictions,
  and ranked candidates; accepting routes through the existing exits with no new landing path; verified in a
  browser. (Spec §4 review card; §6 review-row additions; ADR-016 + ADR-020.)

---

## Verification

### T-209 — End-to-end verify pass against the §7 acceptance checklist
- **Status:** todo
- **Depends on:** T-200 (live key) + T-201–T-207 (all). Without T-200 only the *degrade* item is
  exercisable — every other §7 item needs a real reconcile call.
- **Agent:** verify
- **What:** Drive the real flow — a `/verify` replay of the spike corpus, **offline-isolated** (temp
  `DB_PATH` + temp beets library; `pgrep -af uvicorn` first — see `docs/workflow.md` + the `/verify`
  skill) — and observe the real **land/park side effect + a tag diff against R1** for **every** §7 item:
  **speed** (identity-stage median < 6s vs the 10.96s/36.20s baseline); **happy path** (auto-land, zero
  clicks); **the Pa Salieu override** (lands the correct identity with the real ISRC MBID); **the vote
  holds** (one-sense parks; Shazam alone never lands); **no invented facts** (agreed identity with no real
  MBID parks/keeps-untagged); **fail-soft + timeout** (Shazam error *and* hang both behave as absent);
  **reconcile failure parks**; **degrade** (`ANTHROPIC_APIKEY` unset → R1 gate, still lands/parks);
  **persistence** (reason/contradictions/ranked order survive a restart); **FEATURE PARITY** (same
  embedded art, synced lyrics, genre, year, tags, `Artist/Album/` as R1, side-by-side on ≥3 songs — any
  regression **fails**); **landing still serial** (pool = 1); **genre unchanged** (still `lastgenre`, the
  R1.6 fence held). Transcribe any correction to `docs/learnings.md`.
- **Done when:** every §7 checkbox is proven by `/verify` observing the real side effect (a correctly-
  tagged MP3 320 in the right place, land or park as specified) — not by "the code looks right". (Spec §7,
  whole checklist.)

---

## Backlog (not R1.5 — captured, triaged at birth per the scope guard)

Findings that surface while building go to `docs/backlog/` unless closing §7 **requires** them. Already
filed from the spike/audit and explicitly out of R1.5: `T-042` replaygain, `T-043` scrub, and the
migrate-job plugins (`mbsync`/`duplicates`/`fromfilename`) folded into the R2.5 migrate idea
(`docs/backlog/README.md`). The R1.6 genre work (ADR-023, exp 4 first) and the re-search *agent*
(T-034/035) are the deliberate §3 fence — not backlog gaps, deferred by design.
