# R1.5 Spec — CleanMuzik (multi-sense reconciliation: fingerprint + Shazam + yt-dlp → LLM)

> **Status: DRAFT v2 (architecture B) — 2026-08-10, pending owner sign-off.** Supersedes the v1 draft,
> which specced the abandoned "A / veto-only adjudicator." The test of done is unchanged: *an agent that
> has never seen this project could read this file and build the right thing without asking a question.*

Product brief: `cleanmuzik-prd.md`. Binding constraints: `docs/r1/adr.md` — esp. **ADR-021 (amended
2026-08-10: veto-only → 2-of-3 senses vote)**, **ADR-022** (land serial), **ADR-020** (manual exits),
**ADR-019** (Shazam conditions), **ADR-009/010** (dedup + candidate fields). Evidence: the spike ledger
`docs/research/engine-rethink-spike.md` — the A-vs-B decision (exp 8 throttle, exp 9 full-flow head-to-head)
is why this spec is B. This **extends R1/R1.1**; it changes the *identity* stage and adds *senses*, and
leaves the rest of the pipeline (download, transcode, landing, enrichment, dedup, scan) intact.

---

## 1. Goal of R1.5

Replace R1's slow, single-sense identity stage with **multi-sense reconciliation**. Today identity is a
serial lookup chain (AcoustID → fuzzy MusicBrainz match → MB year → Last.fm), 62–85% of a track's wall
clock. R1.5 gathers **three senses** — the yt-dlp title, the AcoustID fingerprint, and a Shazam
recognition — and has one LLM call **reconcile** them into a decision, taking one exact ISRC→MusicBrainz
lookup for the real facts. Measured on the spike corpus: **~4s vs today's 11s/37s (~8.6×)**, and it
**resolves** mistags today can only park (the Pa Salieu case, exp 9).

Three properties, all binding:

- **Speed** — the identity stage collapses from a serial 1/sec chain to `Shazam + reconcile + one ISRC
  lookup`. Art/genre/lyrics enrichment is unchanged and stays **inline/serial** as in R1 — it was never
  the bottleneck, and the identity collapse alone is the ~8.6×. No intra-track concurrency is introduced.
- **Safety by vote (ADR-021 amended)** — auto-land requires **≥2 of the 3 senses to agree**; one dissenter
  parks. The LLM *may* override a wrong fingerprint, but only when two other senses corroborate.
- **Feature parity (hard)** — B must land **everything R1 lands** (embedded cover art, synced lyrics,
  genre, year, correct title/artist/album tags, organized `Artist/Album/`). Faster must never mean *less*;
  a song that lands with poorer tags than today is a **fail**, not a trade-off.

## 2. In scope

- **`SourceSignals` from yt-dlp** — stop discarding the `info` dict at `download.py:~299`; surface
  `{ title, uploader, channel_is_topic, description_head, tags, duration, video_id, yt_artist, yt_title,
  yt_album, yt_release_year }` into the session. This is **sense 1** (the YouTube claim) and the reconcile
  call's textual evidence. **Prefer YouTube's structured music fields** (`info["artist"]`/`["track"]`/
  `["album"]`/`["release_year"]`) when present — cleaner than splitting the raw title; the title-parse and
  Topic-uploader are fallbacks for `yt_artist`/`yt_title` (T-201). **`yt_album`/`yt_release_year` are
  judgment-only evidence for the reconcile call — never a written fact and never in the §5 code vote**
  (YouTube's year is the *upload* year; its album is often a `"- Topic"` auto-album), so written facts
  still come only from a real MusicBrainz/ISRC lookup (§5 facts-from-a-real-lookup).
- **Shazam as sense 3** (`app/shazam.py`) — one recognition call per track → `{ shazam_artist, shazam_title,
  isrc, art_url?, lyrics?, matched, error }`. **Fail-soft with a hard timeout** (§5). Called per-track (not
  only on an AcoustID miss — a widening of ADR-019's "backup tier," safe only under the serial pipeline).
- **The reconcile call** at `import_seam.py :: choose_item`, injected the way `dominance_fn` is (offline
  tests inject a stub). Given the 3 senses + the augmented candidate list, it returns a `Verdict` (§6): a
  decision, the **chosen candidate index**, which senses agree, a **ranking** for the review card, and genre/mood.
- **The 2-of-3 accept rule** (§5) — the safety spine, replacing R1's `_matching_candidate + SCORE_MIN`
  boolean and A's veto-only clause.
- **Facts from a real lookup only (ADR-021 Rule 2, carried forward, not new)** — the landed recording MBID
  comes from the **fingerprint** (`dominance.top_recording_ids`) **or** the **ISRC→MusicBrainz** lookup;
  the LLM never authors an MBID/ISRC/year. ISRC→MB covered ~46% on the spike corpus; the confident rest are
  covered by the fingerprint MBID (§5).
- **Landing unchanged and serial (ADR-022, pool = 1)** — an accepted identity is applied through the
  **same** `resolve_import`/`_forced_match` machinery a manual resolve uses (`import_seam.py:1102`).
- **Enrichment unchanged** — cover art, genre (`lastgenre`), and lyrics land exactly as R1 does them,
  inline in beets' serial import (parity). R1.5 does **not** parallelize enrichment; the speed win is
  entirely the identity-stage collapse (below), so no intra-track concurrency is introduced.
- **Review card gains `reason` + `contradictions` + LLM-ranked candidates, persisted to SQLite** (§6).
- **Anthropic key** read from repo-root `.env` as **`ANTHROPIC_APIKEY`** (§6 — differs from the SDK default).

## 3. Explicitly out of scope

The fence — tempting, deliberately not R1.5.

- **LLM-authored genre/mood (ADR-023) → R1.6.** R1.5 keeps genre from the existing source (`lastgenre`) for
  parity. R1.6 opens with **exp 4** (the never-run confident-wrong-rate test + the curated enum with an
  `uncertain` member) and only then hands genre to the LLM. The reconcile call *may emit* a genre suggestion,
  but R1.5 **does not write it** — `lastgenre` still owns the genre tag.
- **Shazam art/lyrics — DROPPED (beets audit 2026-08-10, `docs/learnings.md`).** Not deferred, dropped:
  synced lyrics are fully covered by the `lyrics` plugin (LRCLIB, `synced=True`); cover art comes from our
  `artwork.py` (CAA + iTunes) and Shazam's `art_url` is the *same iTunes source* — redundant. R1.5 captures
  Shazam's `art_url`/`lyrics` fields in the record shape but **writes neither**; art/lyrics land via the
  existing path exactly as R1. If art coverage is ever thin, add sources to `artwork.py`, not Shazam.
- **Pipeline concurrency beyond serial land (ADR-022 parallel half) → R2.x/R3.** Gated on throttle evidence;
  exp 8 cleared Shazam's *own* cadence but not full-pipeline fan-out. Serial land only.
- **The re-search rescue *agent*** (tool-using MB-search loop; council §3 / T-034/035) → later. R1.5's
  reconcile is a **single** structured call over the candidates already present; it does not loop or search.
- **Writing any LLM confidence to the gate or the review row** — forbidden (§5).

## 4. User flow (what changes from R1)

R1's flow (`docs/r1/spec.md §4`) is unchanged except at **identify** (step 3–4) and the **review card**:

3. **Identify (now multi-sense).** Sequentially (no intra-track concurrency; exp 9 hit ~4s this way):
   yt-dlp signals are already in hand → the AcoustID fingerprint runs as today → a Shazam call runs
   (hard-timeout, fail-soft) → the augmented candidates + three senses go to one reconcile call.
4. **The gate (2-of-3, ADR-021 amended):**
   - **≥2 senses agree on an identity that resolves to a real MBID** → auto-tag and land, zero clicks. If the
     fingerprint is one of the two, this is the R1 happy path; if the fingerprint *dissents* but yt-dlp +
     Shazam agree, B **lands the corrected identity** (the Pa Salieu resolve, exp 9).
   - **Senses disagree (no 2 agree), or the agreed identity has no real MBID** → **park**, carrying the
     `reason` + `contradictions` onto the card.
5. **Review card:** candidates **ranked by the LLM** with a `reason` and `contradictions`. A Shazam
   suggestion surfaces only where it **already** reaches the card — as the ISRC→MB synthetic **candidate**
   (when the ISRC resolves) and inside the LLM's `contradictions` text — **not** as a standalone hint. The
   standalone Shazam artist/title hint is **deferred (T-212)**: it reaches no transport today, helps only a
   narrow slice (Shazam right *and* no ISRC — otherwise it is already a candidate), and can pre-fill a
   confident-wrong guess (the Strawberry Swing cover). Owner actions unchanged (accept / alternate / reject /
   re-search / keep-untagged).

Landing, dedup, enrichment (art/genre/lyrics), staging retention, the Jellyfin scan, and the failure rule
are exactly R1 — only faster and reached via the vote.

## 5. Behaviour details

- **The candidate list is AUGMENTED so the override has a channel (closes the v2 blocker).** The reconcile
  call is handed **one** `candidates[]` list that is the union of every real-MBID-bearing option: beets'
  MusicBrainz candidates **plus**, when the Shazam ISRC resolves, a synthetic entry for the **ISRC→MB
  recording**. Every entry carries `{n, artist, title, mbid, source}` where `mbid` came from a real lookup
  (`source: "musicbrainz"` or `"isrc"`). The LLM selects by **index** into this list; **the landed
  `recording_id` is `candidates[chosen_candidate].mbid`.** This is how the Pa Salieu correction lands — the
  right recording is the appended ISRC entry, selectable by index — while Rule 2 holds because *no* entry's
  MBID was authored by the LLM. If the ISRC does not resolve (the ~54% gap), no synthetic entry exists; the
  only selectable identities are beets' fingerprint/text candidates, exactly as R1.
- **The three senses, and when each is PRESENT.** `yt` (yt-dlp title/uploader) — always present. `fp`
  (AcoustID) — present **only when `dominance.top_recording_ids` is non-empty** (a high `top_score` with an
  empty recording list is *not* an fp identity). `sz` (Shazam) — present only when `matched` (error / empty /
  timeout ⇒ absent, not a vote).
- **The 2-of-3 accept rule (the safety spine).** A sense **supports** `candidates[chosen_candidate]` iff:
  `fp` → `candidate.mbid ∈ dominance.top_recording_ids`; `sz` → the candidate is the `isrc`-sourced entry
  **or** the Shazam (artist AND title) normalized-match the candidate; `yt` → the yt (artist AND title)
  normalized-match the candidate. `agreeing_senses` is proposed by the LLM but **the gate re-derives it in
  code** — intersecting with *present* senses and re-checking support — and uses the **code-validated**
  count, never the raw LLM number. **Auto-land iff ALL hold:**
  1. `verdict == "accept"`;
  2. code-validated `agreeing_senses`, drawn only from present senses, has **≥ 2** members;
  3. `candidates[chosen_candidate].mbid` is non-null (always true — every entry carries a real MBID).

  Any failure → **park** with `reason` + `contradictions`. **Consequences a builder can't get wrong:**
  (a) a lone present/agreeing sense → **park**; Shazam *alone* never lands (ADR-019); (b) `chosen_candidate
  == null` or no augmented candidate for the agreed identity → **park / keep-untagged**, never an
  LLM-invented ID; (c) the fingerprint is *overridden* only when `yt + sz` both **support a non-fp
  candidate** (the deliberate ADR-021 reversal). **The real-but-wrong-ISRC class (Strawberry Swing):** Shazam
  can return a real ISRC for the *wrong* recording (a cover). It parks correctly here because agreement is on
  **artist AND title** — yt says "Frank Ocean", sz says "Coldplay", so neither supports the other's candidate
  → < 2 agree. **Eyes-open residual:** where two senses are *genuinely* fooled together onto the same wrong
  identity, B auto-lands wrong; the override case is validated at n=1 (Pa Salieu). Accepted, recorded risk.
- **Shazam fail-soft AND hard timeout.** `app/shazam.py` returns the §6 record or `{matched:false,
  error:...}`. A **hard wall-clock timeout** (default 8s, tunable) maps a hang to `{matched:false,
  error:"timeout"}` — a hang is *not* "unavailable" and, on the serial pipeline, would otherwise block every
  later track (exp 8 showed real tail spikes to ~28s). Any Shazam error/empty/timeout simply drops `sz` to a
  non-vote; the pipeline proceeds on the remaining senses. Shazam is **never** written as a tag on its own
  authority and **never** the sole agreeing sense.
- **Reconcile-call failure → park.** If the LLM call itself fails (timeout, 5xx, non-schema output) on a
  track, that track **parks** with `reason:"adjudication unavailable"` — never a silent auto-land. (Distinct
  from `ANTHROPIC_APIKEY` absent, below.)
- **LLM confidence is never load-bearing — enforced structurally.** The reconcile boundary **drops any
  confidence field before the gate function and before persistence**; it reaches neither the accept decision
  nor the review row. The row's discriminator stays the fingerprint/tag `score` (R1).
- **Feature parity.** The landed file must match R1's outputs exactly (art, synced lyrics, genre, year,
  tags, `Artist/Album/`). Enrichment plugins **and their inline/serial scheduling** are unchanged — only the
  *identity* stage feeding them changes. A parity regression is a build failure (see §7).
- **Determinism + cost.** Temperature 0; one reconcile call per track. Council-estimated ~$0.05–0.20 for the
  corpus (an estimate, not a measured spike figure).

### Open build seam — Shazam packaging (resolve in the Shazam ticket; record as an ADR)

The spike ran `shazamio` in an isolated **Python 3.12** venv (`server/.venv-shazam`) — the app's 3.14 venv
has no `shazamio-core` wheel. **Decision (this spec): invoke it as a subprocess against the 3.12 venv** —
it quarantines the reverse-engineered dependency (ADR-019's accepted risk) behind a process boundary that
can be killed on timeout without touching the worker, and keeps the app on 3.14. The Shazam ticket records
this as a short ADR and owns the subprocess contract (I/O shape, kill-on-timeout); pin-3.12 / vendor-wheel
are documented fallbacks only if the subprocess path fails in build.

## 6. Interfaces

### The reconcile seam (`import_seam.py`)

`FingerprintTrustSession` gains three constructor params alongside the existing `dominance_fn`:
`source_signals` (the yt-dlp blob for this track), `shazam_fn` (called once per track, hard-timeout,
returns the §6 Shazam record), and `reconcile_fn(evidence) -> Verdict`. Offline tests inject stubs for all
three, exactly as `dominance_fn` is stubbed today. In `choose_item`, the order is: existing `dominance_fn`
→ `shazam_fn` → **build the augmented `candidates[]`** (beets candidates + a synthetic ISRC entry if the
Shazam ISRC resolves via the ISRC→MB lookup) → `reconcile_fn(evidence)` → apply the 2-of-3 gate (§5). An
accepted `recording_id = candidates[chosen_candidate].mbid` is landed via `_forced_match`/`resolve_import`.
Evidence = `SourceSignals` + `dominance` (`top_score` + `top_recording_ids`) + the augmented `candidates[]`
(canonical fixed order) + the optional Shazam record.

### Verdict schema (structured output)

The **augmented** `candidates[]` handed to the call (each entry carries a real MBID):

```jsonc
// candidates[] = beets MusicBrainz candidates ++ (ISRC→MB entry, if the ISRC resolved)
[ { "n": 0, "artist": "…", "title": "…", "mbid": "<real>", "source": "musicbrainz" },
  { "n": 5, "artist": "Pa Salieu", "title": "Frontline", "mbid": "<real>", "source": "isrc" } ]
```

```jsonc
// Verdict
{
  "verdict": "accept" | "park",
  "chosen_candidate": <int n into candidates[]> | null,   // enum-constrained; NEVER a free-text identity
  "agreeing_senses": ["yt","fp","sz"],      // LLM proposal; the gate RE-DERIVES + validates in code (§5)
  "ranking": [<int n>, ...],                 // FULL ordering of candidates[] for the review card
  "reason": "<one line>",
  "contradictions": ["<why a sense disagrees>", ...],
  "genre_suggestion": "<str|null>",          // R1.5 does NOT write this (parity: lastgenre owns genre)
  "mood_suggestion": "<str|null>"            // captured, unused until R1.6
}
```

`candidates[]` order is **canonical and fixed**, serialized identically into the prompt and reused for
`chosen_candidate`/`ranking` resolution and persistence — an index never resolves against a different order
than the LLM saw. There is **no free-text identity field**: the LLM can only point at a real-MBID entry, so
it can never author an identity or an MBID. No `confidence` field (dropped at the boundary, §5).

### Shazam record (`app/shazam.py`)

```jsonc
{ "shazam_artist": "Pa Salieu", "shazam_title": "Frontline", "isrc": "GBxxx...",
  "art_url": "https://...", "lyrics": "<text|null>",   // captured; R1.5 still writes art/lyrics via beets
  "matched": true, "error": null }                     // error set (matched:false) on any failure/timeout
```

### ISRC → MusicBrainz (facts)

One exact lookup `GET /ws/2/isrc/{isrc}?fmt=json&inc=artist-credits` (User-Agent required, 1/sec) → real
recording MBID + artist/title. This is the only network floor B keeps on the identity path.

### Review row / SSE additions — **must persist** (ADR-010 lesson)

`reviews` gains **columns** `reason TEXT`, `contradictions_json TEXT`, and the stored candidate list
(`candidate_ids_json`) is written in **LLM-ranked order** — reorder `candidate_ids` by `ranking` *before*
`create_review` (around `import_seam.py:758`), so the persisted order already reflects the ranking and a
restart re-hydrates it. A discriminator that lives only in the live SSE event and not in SQLite is
unimplementable after a restart (ADR-010 addendum). `track.review_required` carries `reason` +
`contradictions` alongside the (ranked) `candidates`; no route signatures change.

### Secrets (`.env`) — addition to R1's table

| Key | Needed by | R1.5 behaviour if missing |
|---|---|---|
| `ANTHROPIC_APIKEY` | reconcile | **Required for multi-sense auto-land.** Differs from SDK default — read explicitly. **Absent OR rejected (401/expired)** → degrade to the **R1 fingerprint-only gate** (logged warning), so a stale key degrades gracefully rather than parking *every* track. *This reopens the wrong-recording mistag class (e.g. Pa Salieu auto-lands as Vanessa Bling) — an eyes-open operational fallback, not an invisible one.* (A mid-run *transient* failure on a valid key still parks that one track, per §5.) |

## 7. Acceptance checklist (R1.5 is "done" when…)

- [ ] **Speed:** on a `/verify` replay of the spike corpus, the identity stage's **median wall-clock is
      < 6s** (exp 9 measured ~4.2s), vs today's instrumented **10.96s park / 36.20s auto-land** baseline.
      Shazam tail spikes are capped by the §5 timeout, not counted as sustained latency.
- [ ] **Happy path:** fingerprint + Shazam (+yt) agree → auto-tag and land, **zero clicks**, same outcome as R1.
- [ ] **The override win (Pa Salieu):** fingerprint matches the *wrong* recording but yt-dlp + Shazam agree →
      B **lands the correct identity** (Pa Salieu), zero clicks, with the real MBID from the ISRC lookup.
- [ ] **The vote holds:** a track where only **one** sense has an identity (the others miss/disagree) **parks** —
      never auto-lands. Shazam alone never lands.
- [ ] **No invented facts:** an agreed identity with **no** real MBID (no fingerprint match, no ISRC hit) parks
      or keeps-untagged; no LLM-authored MBID/year is ever written.
- [ ] **Fail-soft + timeout:** forcing Shazam to **error** *and* to **hang** both leave the pipeline behaving
      as if Shazam were simply absent (the hang is capped by the timeout, worker not blocked).
- [ ] **Reconcile failure parks:** forcing the LLM call to fail parks the track (not a silent land).
- [ ] **Degrade:** with `ANTHROPIC_APIKEY` unset, the pipeline falls back to the R1 fingerprint gate and still
      lands/parks (logged), proving the layer is additive to basic flow.
- [ ] **Persistence:** a parked card's `reason`, `contradictions`, and ranked candidate order **survive a
      backend restart** (SQLite columns, not just the SSE event).
- [ ] **FEATURE PARITY:** every landed file has the **same** embedded cover art, synced lyrics, genre, year,
      and title/artist/album tags it would have under R1 — verified side-by-side on ≥3 songs. Any regression fails.
- [ ] **Landing is still serial** (pool = 1); no concurrency introduced.
- [ ] **Genre unchanged:** genre is still written by `lastgenre`; the R1.6 fence (no LLM genre) held.

---

*Verification (Definition of Done): the safety, override, and parity items are proven by `/verify` replaying
the spike corpus offline (isolated `DB_PATH` + temp beets library; `pgrep -af uvicorn` first) and observing
the real land/park side effect + a tag diff against R1 — not by "the code looks right." Transcribe corrections
to `docs/learnings.md`.*
