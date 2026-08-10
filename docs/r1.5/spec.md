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
  lookup`; art/genre/lyrics enrichment is unchanged but fetched **in parallel**, off the critical path.
- **Safety by vote (ADR-021 amended)** — auto-land requires **≥2 of the 3 senses to agree**; one dissenter
  parks. The LLM *may* override a wrong fingerprint, but only when two other senses corroborate.
- **Feature parity (hard)** — B must land **everything R1 lands** (embedded cover art, synced lyrics,
  genre, year, correct title/artist/album tags, organized `Artist/Album/`). Faster must never mean *less*;
  a song that lands with poorer tags than today is a **fail**, not a trade-off.

## 2. In scope

- **`SourceSignals` from yt-dlp** — stop discarding the `info` dict at `download.py:~299`; surface
  `{ title, uploader, channel_is_topic, description_head, tags, duration, video_id }` into the session.
  This is **sense 1** (the YouTube claim) and the reconcile call's textual evidence.
- **Shazam as sense 3** (`app/shazam.py`) — one recognition call per track → `{ shazam_artist, shazam_title,
  isrc, art_url?, lyrics?, matched, error }`. **Fail-soft with a hard timeout** (§5). Called per-track (not
  only on an AcoustID miss — a widening of ADR-019's "backup tier," safe only under the serial pipeline).
- **The reconcile call** at `import_seam.py :: choose_item`, injected the way `dominance_fn` is (offline
  tests inject a stub). Given the 3 senses + MusicBrainz candidates, it returns a `Verdict` (§6): a decision,
  the chosen identity, which senses agree, a candidate **ranking** for the review card, and genre/mood.
- **The 2-of-3 accept rule** (§5) — the safety spine, replacing R1's `_matching_candidate + SCORE_MIN`
  boolean and A's veto-only clause.
- **Facts from a real lookup only (ADR-021 Rule 2, carried forward, not new)** — the landed recording MBID
  comes from the **fingerprint** (`dominance.top_recording_ids`) **or** the **ISRC→MusicBrainz** lookup;
  the LLM never authors an MBID/ISRC/year. ISRC→MB covered ~46% on the spike corpus; the confident rest are
  covered by the fingerprint MBID (§5).
- **Landing unchanged and serial (ADR-022, pool = 1)** — an accepted identity is applied through the
  **same** `resolve_import`/`_forced_match` machinery a manual resolve uses (`import_seam.py:1102`).
- **Enrichment unchanged, parallelized** — cover art, genre (`lastgenre`), and lyrics land exactly as R1
  does them (parity), but fetched concurrently off the identity critical path.
- **Review card gains `reason` + `contradictions` + LLM-ranked candidates, persisted to SQLite** (§6).
- **Anthropic key** read from repo-root `.env` as **`ANTHROPIC_APIKEY`** (§6 — differs from the SDK default).

## 3. Explicitly out of scope

The fence — tempting, deliberately not R1.5.

- **LLM-authored genre/mood (ADR-023) → R1.6.** R1.5 keeps genre from the existing source (`lastgenre`) for
  parity. R1.6 opens with **exp 4** (the never-run confident-wrong-rate test + the curated enum with an
  `uncertain` member) and only then hands genre to the LLM. The reconcile call *may emit* a genre suggestion,
  but R1.5 **does not write it** — `lastgenre` still owns the genre tag.
- **Shazam-sourced art/lyrics replacing the beets plugins → R1.6.** R1.5 captures Shazam's `art_url`/`lyrics`
  if present but still writes art/lyrics via `fetchart`/`lyrics` (parity, and synced-lyrics quality). Deciding
  Shazam-vs-LRCLIB for *synced* lyrics is an R1.6 measurement.
- **Pipeline concurrency beyond serial land (ADR-022 parallel half) → R2.x/R3.** Gated on throttle evidence;
  exp 8 cleared Shazam's *own* cadence but not full-pipeline fan-out. Serial land only.
- **The re-search rescue *agent*** (tool-using MB-search loop; council §3 / T-034/035) → later. R1.5's
  reconcile is a **single** structured call over the candidates already present; it does not loop or search.
- **Writing any LLM confidence to the gate or the review row** — forbidden (§5).

## 4. User flow (what changes from R1)

R1's flow (`docs/r1/spec.md §4`) is unchanged except at **identify** (step 3–4) and the **review card**:

3. **Identify (now multi-sense).** In parallel where possible: yt-dlp signals are already in hand; the
   AcoustID fingerprint runs as today; a Shazam call runs (hard-timeout, fail-soft). The three senses +
   MusicBrainz candidates go to one reconcile call.
4. **The gate (2-of-3, ADR-021 amended):**
   - **≥2 senses agree on an identity that resolves to a real MBID** → auto-tag and land, zero clicks. If the
     fingerprint is one of the two, this is the R1 happy path; if the fingerprint *dissents* but yt-dlp +
     Shazam agree, B **lands the corrected identity** (the Pa Salieu resolve, exp 9).
   - **Senses disagree (no 2 agree), or the agreed identity has no real MBID** → **park**, carrying the
     `reason` + `contradictions` onto the card.
5. **Review card:** candidates **ranked by the LLM** with a `reason`; a Shazam suggestion appears as a
   **labelled** hint (accepted via the existing re-search / keep-untagged exits — ADR-020 — not a new landing
   path). Owner actions unchanged (accept / alternate / reject / re-search / keep-untagged).

Landing, dedup, enrichment (art/genre/lyrics), staging retention, the Jellyfin scan, and the failure rule
are exactly R1 — only faster and reached via the vote.

## 5. Behaviour details

- **The 2-of-3 accept rule (the safety spine).** Let the three senses be `yt` (yt-dlp title/uploader), `fp`
  (AcoustID: `dominance.top_recording_ids` + `top_score`), `sz` (Shazam: artist/title/isrc). The reconcile
  call returns `verdict`, a `chosen` identity, and `agreeing_senses` (which of yt/fp/sz support `chosen`).
  **Auto-land iff ALL hold:**
  1. `verdict == "accept"`;
  2. `len(agreeing_senses) >= 2`;
  3. `chosen` resolves to a **real recording MBID** — either in `dominance.top_recording_ids` (fp) **or**
     returned by the ISRC→MB lookup (sz). *The landed match is built from that MBID via `_forced_match`* —
     the land is **sourced from the real lookup, never from the LLM's free-text identity.**

  Any failure → **park**, storing `reason` + `contradictions`. **Consequences, spelled out so a builder
  can't get it wrong:** (a) a lone sense (only fp, or only sz) is `agreeing_senses == 1` → **park**, never
  auto-land — so Shazam *alone* never lands (ADR-019 preserved); (b) if `chosen` has no real MBID from
  either source, it **cannot** auto-land regardless of agreement — park or keep-untagged, never an
  LLM-invented ID; (c) the fingerprint may be *overridden* only when `yt + sz` agree against it (the
  deliberate ADR-021 reversal). **Eyes-open:** the override case is validated at n=1 (Pa Salieu); this is an
  accepted, recorded risk, not a proof.
- **`agreeing_senses` is the LLM's judgment, `chosen`'s MBID is structural.** The count of agreeing senses is
  a reasoning task (does "Pa Salieu" ≈ the yt title ≈ the Shazam artist?), so it is LLM-produced — that is
  the probabilistic half. The **facts** half is structural: whatever `chosen` is, the *landed* recording MBID
  must come from fp or the ISRC lookup, or it parks. Do not let the LLM's `chosen` string become a tag.
- **Facts sourcing + the 46% ISRC gap.** Prefer the ISRC→MB MBID when the agreed identity is Shazam-driven;
  else use the fingerprint MBID. If neither yields an MBID for `chosen`, the track parks (or keep-untagged
  via ADR-020). The LLM never fills the gap.
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
  tags, `Artist/Album/`). Enrichment plugins are unchanged; only their scheduling (parallel) changes. A
  parity regression is a build failure (see §7).
- **Determinism + cost.** Temperature 0; one reconcile call per track. Council-estimated ~$0.05–0.20 for the
  corpus (an estimate, not a measured spike figure).

### Open build seam — Shazam packaging (resolve in the Shazam ticket; record as an ADR)

The spike ran `shazamio` in an isolated **Python 3.12** venv (`server/.venv-shazam`) — the app's 3.14 venv
has no `shazamio-core` wheel. **Lean: invoke it as a subprocess against the 3.12 venv**, which also
quarantines the reverse-engineered dependency (ADR-019's accepted risk) behind a process boundary that can
die on timeout without touching the worker. Alternatives (pin the server to 3.12; vendor the wheel) are the
fallback. Blocks the Shazam ticket.

## 6. Interfaces

### The reconcile seam (`import_seam.py`)

`reconcile(evidence) -> Verdict`, injected like `dominance_fn`. Evidence assembled per track from
`SourceSignals`, `dominance` (`top_score` + `top_recording_ids`), the MusicBrainz `candidates` list (a
canonical, fixed order — see below), and the optional Shazam record. Offline tests inject a stub.

### Verdict schema (structured output)

```jsonc
{
  "verdict": "accept" | "park",
  "chosen_candidate": <int index into candidates[]> | null,   // enum-constrained to the list
  "agreeing_senses": ["yt","fp","sz"],      // subset; auto-land needs length >= 2
  "ranking": [<int>, ...],                   // FULL ordering of candidates[] for the review card
  "reason": "<one line>",
  "contradictions": ["<why a sense disagrees>", ...],
  "genre_suggestion": "<str|null>",          // R1.5 does NOT write this (parity: lastgenre owns genre)
  "mood_suggestion": "<str|null>"            // captured, unused until R1.6
}
```

`candidates[]` order is **canonical and fixed** (the order beets produced), serialized identically into the
prompt and reused for `chosen_candidate`/`ranking` resolution and persistence — so an index never resolves
against a different order than the LLM saw. No `confidence` field (dropped at the boundary, §5).

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

`reviews` gains **columns** `reason TEXT`, `contradictions_json TEXT`, and the candidate list is stored in
**LLM-ranked order** — a discriminator that lives only in the live SSE event and not in SQLite is
unimplementable after a restart (ADR-010 addendum). `track.review_required` carries `reason` +
`contradictions` alongside the (ranked) `candidates`; no route signatures change.

### Secrets (`.env`) — addition to R1's table

| Key | Needed by | R1.5 behaviour if missing |
|---|---|---|
| `ANTHROPIC_APIKEY` | reconcile | **Required for multi-sense auto-land.** Differs from SDK default — read explicitly. If absent: degrade to the **R1 fingerprint-only gate** (logged warning). *This reopens the wrong-recording mistag class (e.g. Pa Salieu auto-lands as Vanessa Bling) — an eyes-open operational fallback, not an invisible one.* |

## 7. Acceptance checklist (R1.5 is "done" when…)

- [ ] **Speed:** a representative track's identity stage completes in **~single-digit seconds** (target: beat
      today's 11s/37s by a wide margin on a `/verify` replay of the spike corpus).
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
