# ShazamIO — what we know, and what we still have to find out

The **backup identification tier** ratified in ADR-019: `AcoustID → Shazam → manual re-search →
keep-untagged`. Shazam answers only *"what is this?"*; its artist + title feed the existing
MusicBrainz search, and **beets remains the tagging engine (ADR-005 intact)**. The abandoned
`music-cleaner` / secret-mode PRD used ShazamIO **as the engine** — that stays rejected. Same
library, different job; the distinction is the whole decision.

**Not installed.** Absent from `server/requirements.txt`, `import shazamio` fails in the project
venv, and the spike harness lived in a session scratchpad that has since been swept `[source]`
verified 2026-07-30. **No `[source]` claim on this page is possible** — nothing to read.

## Correction to T-038's framing

T-038 filed this page as *"un-evidenced in the repo… unlike the other two there is no spike behind
it… this page starts as 'what we need to find out'."*

**Half right, and the half that's wrong matters.** T-035 *is* a spike, and a thorough one: a
measured rescue rate over the real parked queue, a discovered failure class that changed ADR-019,
and three normalisation findings. What is genuinely un-evidenced is **not** Shazam's answers — it is
the **library's operational behaviour**: rate limits, auth, latency, error taxonomy, breakage mode.

So this page splits accordingly. §1 is as well-evidenced as anything in `docs/engines/`. §2 is
empty on purpose, and that emptiness is the finding.

## 1. Capabilities — measured, n=5, 2026-07-25

**Rescue rate: 4 of 5 distinct parked tracks (80%), all clearing MusicBrainz at score 100** once
normalised `[measured]`. Full table in `docs/backlog/T-035.md`.

> Quote **80%**, not the 44% by-queue-row figure — the gap is entirely one residual having parked
> itself five times. It is a duplicate-parking artifact, not a Shazam property. And **n=5 is a
> strong signal, not a rate.**

**It returns rich fields**: title, artist, album, year, genre, label, ISRC.

**It is strongest where AcoustID is weakest** — Shazam's database is consumer-scale, against
AcoustID's crowd-sourced Chromaprint data, and it is best on exactly the commercial/label tracks
AcoustID tends to miss. The Nipsey Hussle rip AcoustID **could not fingerprint at all**, Shazam
identified cold `[measured]`.

### The failure class that changed the ADR

**Shazam's dangerous output is not a miss — it is a confident wrong answer.**

Run against Frank Ocean's *Strawberry Swing* — a cover sung over Coldplay's original instrumental —
Shazam returned **Coldplay, *Viva La Vida*, ISRC `GBAYE1600219`** `[measured]` 2026-07-27.
Confident, wrong, and **none of "error, timeout, rate-limit or no-match"**, so a fail-soft condition
never engages. `Coldplay / Strawberry Swing` then scores **100** at MusicBrainz — auto-land
territory. The tier would have converted a track the system had **correctly refused to guess at**
into a confidently mistagged file.

**Shazam is working correctly and reporting what it heard.** A fingerprint reads the whole mix, and
most of that mix genuinely *is* Coldplay's master. **This is a class, not a one-off**: covers,
interpolations, mixtape cuts — most of *nostalgia, ULTRA* — and common in exactly the catalogue this
tool is for.

**The engine-level consequence: Shazam's confidence carries no information about this failure
mode.** There is no field in its answer that distinguishes "this is the track" from "this is the
track this was built over". → what was decided about it: **ADR-019 condition 3.**

### Normalisation is load-bearing, not incidental

Feeding Shazam's fields to MusicBrainz **verbatim scored 0 hits on 3 of 4** — which reads as a Shazam
failure and isn't one `[measured]`:

1. **Strip a trailing `(feat. …)` / `ft. …` from the title.** Shazam appends featured artists to the
   title; MusicBrainz keeps them in the credit. **This single regex is the difference between 1/4
   and 4/4** — all four jump to score 100.
2. **Phrase-quote the fields.** An unquoted `"<title> <artist>"` search returns pure garbage — top
   hits *DJ Muggs — "Jay Z"* and *MERO — "Hussle Nipsey"*.
3. **ASCII-fold stylised artist glyphs** (`JAŸ-Z`). Affects **ranking, not hit/miss** — it promoted
   the better JAY-Z recording from 2nd to 1st.

**ISRC is a cheap first probe, never the bridge.** It **missed** for Nipsey (0 MusicBrainz
recordings — MB doesn't index it) and **hit** for JAY-Z, returning the best result of the whole run.
Try it first; fall back to artist + title, which is the reliable bridge.

## 2. Hard limits and cost model — genuinely unknown

**Nothing below has been established.** Listed as the work, not as knowledge:

- **Rate limits** — unknown. Shazam's endpoints are private; no published policy applies.
- **Auth** — unknown whether any key, token or session is needed.
- **Latency per recognition** — never timed, even during the spike.
- **Error taxonomy** — what `shazamio` raises, and whether the classes are distinguishable enough to
  implement ADR-019's fail-soft condition. **This is the load-bearing unknown**: condition 2 is
  written in terms of "error, timeout, rate-limit or no-match", and nobody has checked those are
  separable.
- **Audio input requirements** — format, sample rate, duration window. Unknown whether it
  fingerprints a bounded prefix the way Chromaprint's 120 s window does.
- **Breakage mode** — when the private endpoints change, does it raise cleanly or return nonsense?
  Determines whether the fail-soft condition actually holds when the library rots.

**Accepted risk, eyes open** (ADR-019): `shazamio` hits Shazam's **private, reverse-engineered**
endpoints, may break with no notice, and sits in a ToS grey area. The owner explicitly accepted this
— *"willing to live with that it might not work because it's not an official library."* Mitigation
is the fail-soft condition plus keeping Shazam behind a seam removable without touching the
pipeline: **if it rots, the tier goes quiet and the queue returns to its present size.**

## 3. Where Shazam misses

**Two residual classes, neither an obscure artist** `[measured]`:

- **A particular *cut* of audio** — the Nines `"Franklin"` music-video edit. Shazam identified the
  same artist correctly elsewhere (it nailed Nines' *Outro*), so this is about the edit, not the
  catalogue.
- **A cover over the original instrumental** — §1's Coldplay case, where it answers confidently and
  wrongly rather than missing.

→ the build ticket's requirements, and what the two residuals mean for the tier's place in the
order: `docs/backlog/T-035.md` open item 4, and ADR-019. **One of them is a prerequisite, not a
detail:** a Shazam-derived match must be distinguishable downstream from an AcoustID one, or
ADR-019's condition 3 cannot be enforced at all.

## 4. Rebuilding the harness

~5 minutes, if the measurement ever needs repeating: `uv venv` + `shazamio` **outside** the project
venv (`python3 -m venv` fails here — no `ensurepip`); read the distinct `staging_path`/`url` pairs
out of `reviews`; re-download with **`yt-dlp --js-runtimes node`** (a plain pull 403s in a bare
sandbox — see [`yt-dlp.md`](yt-dlp.md) §1, and note that this is about *extraction in a sandbox*,
not in-app download 403s); recognise; query MusicBrainz.

The results table in `docs/backlog/T-035.md` is the durable copy — the code is gone.
