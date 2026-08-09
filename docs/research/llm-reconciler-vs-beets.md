# LLM Reconciler vs. beets/AcoustID-alone — Research Findings

> **New file.** No prior `docs/research/` or `docs/notes/` convention existed (`docs/` holds
> `r1/`, `r1.1/`, `r2/`, `backlog/`, `primers/`, `learnings.md`, `roadmap.md`, `workflow.md`).
> Created `docs/research/` as the home for this and future spike research. Touches no other file.

**Question:** Would an **LLM reconciler** — given yt-dlp metadata + AcoustID candidates + a
**ShazamIO** fingerprint result, asked to pick/verify the best match — beat the current
beets/AcoustID-alone engine on identification accuracy for CleanMuzik's corpus (UK
rap/grime/dancehall/hip-hop YouTube rips, mixed Topic and non-Topic)?

**Grounding (confirmed in repo, 2026-08-09):**
- Engine is beets 2.12 driven from a long-lived FastAPI backend, plugins in this order:
  `musicbrainz`, `chroma` (AcoustID), `lastgenre`, `fetchart`, `embedart`, `lyrics`, `ftintitle`
  (`server/app/beets_engine.py:52`). `chroma` shells out to Chromaprint `fpcalc`.
- Strong AcoustID matches auto-land; weak matches park in a review queue
  (`server/app/reviews.py`, `import_seam.py`). ADR-005: *beets is the engine, never hand-roll one.*
- ADR-001 pins **sequential** processing (no parallelizing the pipeline); ADR-002 pins MP3 320.
  Both bear on where an LLM call could sit.
- The trigger bug: "Pa Salieu — Frontline" (MixtapeMadness rip) auto-landed **confidently wrong**
  as "Vanessa Bling & The Heatwave — Frontline" (dancehall). AcoustID mapped the fingerprint to
  the wrong MusicBrainz recording and **nothing cross-checked the match against the
  YouTube-provided title**. For non-Topic uploads yt-dlp returns no structured
  artist/track/album (all `None`) — just a messy title, uploader, and genre tags; for official
  "Topic"/YT-Music uploads it returns clean artist/track/album/release_year
  (`server/app/download.py`).

---

## Verdict (up front)

**A cross-check reconciler is worth building. Adding ShazamIO into it is not — treat that as a
separate, lower-confidence spike with real legal/maintenance risk.**

Split the claim in two, because the evidence does:

1. **"Cross-check the AcoustID match against the yt-dlp title/uploader before auto-landing"** —
   **high confidence this helps.** The Pa Salieu failure was *not* a fingerprinting-quality
   problem; it was the **absence of any second signal**. The engine already *has* a second signal
   in hand (yt-dlp's title/uploader) and simply never consulted it before auto-landing. Any
   reconciler — LLM or a plain string-similarity gate — that refuses to auto-land when the
   AcoustID artist/title diverges hard from the YouTube title would have caught it. This is the
   real fix and it needs no new dependency. An LLM is a *good* implementation of that gate
   (messy titles, feat. credits, remix suffixes, transliteration are exactly where fuzzy string
   matching breaks and an LLM shines), but the LLM is the nice-to-have; **the cross-check itself
   is the load-bearing part.**

2. **"ShazamIO's fingerprint will catch tracks AcoustID misses"** — **plausible in mechanism,
   unproven in evidence, and carrying the biggest risk.** Shazam's DB (Apple Music's commercial
   catalogue) genuinely has better coverage of exactly this corpus than the community-contributed
   AcoustID→MusicBrainz mapping, and its algorithm is different (see §2). But there is **no
   credible published accuracy comparison** for this genre (§3), and ShazamIO is an
   **unofficial, reverse-engineered, ToS-violating** client that is **not actively maintained**
   (§1). Depending on it in a tool that must "just work" is the shakiest link in the chain.

**Biggest risk:** ShazamIO is a reverse-engineered private-endpoint client whose use violates
Shazam/Apple terms (§1), with no rate-limit contract and no active maintenance — a single
server-side change at Apple silently breaks the pipeline with no recourse. **Do not let the ID
engine's correctness depend on it.** If you spike it, gate it behind a flag, treat every call as
best-effort, and keep the pipeline correct when it returns nothing.

**Confidence:** high on (1), low-to-moderate on (2).

---

## Sub-question findings

### 1. ShazamIO viability, maintenance, legality

**What it is.** ShazamIO's own README: *"a FREE asynchronous library from reverse engineered
Shazam API written in Python 3.10+ with asyncio and aiohttp."* MIT-licensed. It talks to Shazam's
**private/undocumented endpoints** — not an official SDK, not ShazamKit.
([GitHub](https://github.com/shazamio/ShazamIO))

**Maintenance status (GitHub API, checked 2026-08-09):**
- `created_at` 2021-02-03, **`pushed_at` 2025-06-11** — i.e. **~14 months since the last commit**
  as of this writing.
- 28 open issues, 932 stars, **not archived**, MIT, default branch `master`.
- Read: *slowing / semi-dormant*, not dead, not actively developed. For a reverse-engineered
  client, "last touched 14 months ago" is a liability — these break whenever the upstream private
  API shifts, and nobody is watching.
  ([api.github.com/repos/shazamio/ShazamIO](https://api.github.com/repos/shazamio/ShazamIO))

**Rate limits / auth.** No documented rate limits, throttling contract, or auth requirements —
because it is an unofficial client of a private endpoint, there is no published contract at all.
That means: unknown throttling, unknown ban behavior, and no SLA. In practice reverse-engineered
Shazam clients are rate-limited/blocked opaquely by the server side.

**Legality / ToS — the sharp edge.** The project makes **no** statement about ToS compliance,
legal risk, or authorization. Meanwhile the counterparties' terms are explicit:
- Shazam's user agreement requires that recipients *"agree not to reverse engineer the
  Confidential Information."*
- Apple's **ShazamKit** terms bar using or comparing ShazamKit data *"for the purpose of
  improving or creating another audio recognition service."*
  ([WebSearch summary of Shazam user agreement + ShazamKit terms](https://shazam.net/shazamwebapps/user_agreement.html))

So: building on a reverse-engineered Shazam endpoint is a **terms-of-service violation** on its
face. For a **single-user personal tool** that never redistributes Shazam data and isn't a
commercial audio-recognition product, the *practical* enforcement risk is low — but it is a real
policy violation, it is fragile by construction, and it should never be load-bearing. **Sane to
depend on? No — sane to *spike behind a flag as a best-effort enrichment signal*, maybe.**

### 2. Is Shazam's DB/algorithm actually different from AcoustID — enough to catch its misses?

**Yes, on both axes — and the difference favours exactly this corpus.**

**Algorithm.** They are genuinely different fingerprinting families:
- **AcoustID/Chromaprint** is *chroma-based*: it maps spectral energy onto the 12 semitone
  pitch classes and compares harmonic content. Chromaprint's own README: *"an audio fingerprint
  library developed for the AcoustID project… designed to identify near-identical audio… It's
  **not a general purpose audio fingerprinting solution. It trades precision and robustness for
  search performance.**"* ([GitHub/acoustid/chromaprint](https://github.com/acoustid/chromaprint))
- **Shazam** is *landmark/constellation-based* (Wang 2003): it finds spectral peaks in the
  STFT spectrogram and hashes triplets of peaks by their relative time/frequency offsets — noise-
  and distortion-resistant, designed to ID a short, degraded clip against a huge catalogue.
  ([Wang 2003, "An Industrial-Strength Audio Search Algorithm"](https://www.ee.columbia.edu/~dpwe/papers/Wang03-shazam.pdf))

Because Chromaprint targets *near-identical* audio, a YouTube rip that has been re-encoded,
loudness-normalized, or that is a slightly different master/upload than the MusicBrainz recording
can fingerprint to the **wrong** recording or **no** recording — which is consistent with the Pa
Salieu misfire.

**Database coverage — the bigger factor.** This matters more than the algorithm for a
"catch AcoustID's misses" argument:
- AcoustID is community-contributed. Its own project states it holds **~30M fingerprints with
  ~10M mapped to MusicBrainz** — mapping is the bottleneck, and it skews toward what enthusiasts
  have submitted. ([AcoustID via WebSearch](https://acoustid.biz/))
- Shazam's catalogue is effectively Apple Music's commercial catalogue — dense precisely where
  AcoustID/MusicBrainz is thin: UK-rap/grime/dancehall singles, label uploads, chart singles.

**So the mechanism for "Shazam catches what AcoustID misses" is real** — different algorithm,
and materially better commercial-catalogue coverage for this genre. What's missing is *evidence
of how much*, for this corpus (§3).

### 3. Match-accuracy evidence (be honest: it's thin)

**There is no credible, published head-to-head accuracy comparison of AcoustID vs Shazam vs
LLM-assisted tagging for this (or any) music corpus that I could locate in primary sources.**
What exists:
- General descriptions of how each engine matches (beets/Picard docs, Chromaprint README, Wang
  2003) — mechanism, not measured accuracy.
  ([beets MusicBrainz plugin](https://beets.readthedocs.io/en/latest/plugins/musicbrainz.html))
- Community threads on Picard/beets matching accuracy — anecdotal, not benchmarked.
  ([MetaBrainz Discourse](https://community.metabrainz.org/t/matching-accuracy-and-apple-itunes-match/485953))

Do **not** inflate "Shazam recognizes noisy clips well" (a well-established property of the
algorithm) into "Shazam tags YouTube rips more accurately than AcoustID" (an unmeasured claim).
The honest position: the coverage argument is strong *a priori*; the accuracy delta for this
corpus is **unquantified and would need a spike to establish** (§ Needs a spike).

### 4. LLM-as-reconciler prior art

**No primary-source project or paper turned up that uses an LLM specifically to reconcile music
metadata from multiple fingerprint/tag signals.** beets and Picard both already do *multi-source
reconciliation* — but with **penalty-weighted string distance**, not an LLM: they combine existing
file tags + AcoustID + source-specific weightings (MusicBrainz, Discogs) and pick the lowest-
distance candidate. ([beets MusicBrainz plugin](https://beets.readthedocs.io/en/latest/plugins/musicbrainz.html),
[Picard vs beets](https://slashdot.org/software/comparison/MusicBrainz-Picard-vs-beets/))

The gap the LLM would fill is not "reconcile multiple sources" (beets does that) but **"apply
semantic judgment to a messy free-text title vs a structured candidate list"** — deciding that
`"Pa Salieu - Frontline (Music Video) | MixtapeMadness"` is closer to a *Pa Salieu* recording than
to *Vanessa Bling*, a call that penalty-weighted edit distance makes poorly on garbage titles.
That is a defensible, if unproven, niche. Reported accuracy/failure modes for it: **none found in
primary sources** — so treat expected lift as a hypothesis, and note LLMs' own failure mode here
(confident hallucination — it can *invent* an artist just as AcoustID confidently mapped a wrong
one, so the reconciler must be constrained to *choose among / veto* candidates, never free-generate).

### 5. Cost + latency of one LLM call per track

Per the `claude-api` skill's cached model table (2026-06-24) — Claude API first-party rates:

| Model | Input $/1M | Output $/1M |
|---|---|---|
| Claude Haiku 4.5 (`claude-haiku-4-5`) | $1.00 | $5.00 |
| Claude Sonnet 5 (`claude-sonnet-5`) | $3.00 ($2.00 intro thru 2026-08-31) | $15.00 ($10.00 intro) |
| Claude Opus 5 (`claude-opus-5`) | $5.00 | $25.00 |

**Per-track payload estimate** (yt-dlp metadata blob + ~5 AcoustID candidates + optional ShazamIO
result + prompt) ≈ **1,500–2,500 input tokens, ~300–500 output tokens** with structured output.
Using ~2,000 in / ~400 out:

| Model | ~ per track | **50-song batch** |
|---|---|---|
| Haiku 4.5 | ~$0.004 | **~$0.20** |
| Sonnet 5 (intro) | ~$0.008 | **~$0.40** (~$0.60 at full price) |
| Opus 5 | ~$0.02 | **~$1.00** |

**Cost is a non-issue** for a single-user tool: even Opus is ~$1 per 50-song batch. Recommend
**Haiku 4.5** (cheap, fast, entirely adequate for choose-among-candidates), escalating only if a
spike shows it under-performs.

**Latency:** one extra sequential API call per track. Haiku is sub-second-to-low-seconds; the call
lands inside an already-**sequential** pipeline (ADR-001), so it adds to per-track wall time but
does not fight the architecture. Use structured outputs (`output_config.format`) to force a
pick-from-candidates JSON and keep output tokens (and latency) minimal. Note the claude-api skill's
prompting guidance for current models: **do not** over-instruct — state the goal (verify/choose,
never invent), pass the candidates, and let it decide.

### 6. Cover-art + lyrics "fetch it ourselves" sources (with terms)

Relevant because the yt-dlp thumbnail is a **16:9 video frame, not square album art** — so the
engine already needs a real art source; `fetchart`/`embedart` cover this today, but a
"fetch it ourselves" path may want direct sources.

**Cover art:**
- **Cover Art Archive** — `coverartarchive.org`, keyed by MusicBrainz MBID:
  `GET /release/{mbid}/front` and `GET /release-group/{mbid}/front`. **No auth. "There are
  currently no rate limiting rules in place."** Images ride MusicBrainz's licensing; approval
  state is exposed. The natural first choice once you have an MBID (which the pipeline does).
  ([Cover Art Archive API](https://musicbrainz.org/doc/Cover_Art_Archive/API))
- **iTunes Search API** — great for square commercial art and dense on this genre, **but**:
  ~**20 calls/min** (subject to change); art usable only *"to promote store content and not for
  entertainment purposes"*; commercial integrations require Apple Partner enrollment. Fine as a
  personal-use fallback, watch the rate cap and the promotional-use clause.
  ([Apple Performance Partners – Search API](https://performance-partners.apple.com/search-api))
- **Deezer API** — free for registered apps, no per-call fee; good catalogue coverage. (Full-track
  *streaming* requires a paid subscriber, but *artwork/metadata* lookups don't.) A viable
  no-cost art source. ([Deezer terms of use](https://developers.deezer.com/termsofuse))

**Lyrics:**
- **LRCLIB** (`lrclib.net`) — *"a completely free service for finding and contributing synchronized
  lyrics, with an easy-to-use and machine-friendly APIs."* MIT-licensed server (Rust/Axum/SQLite).
  Returns both synced (LRC) and plain lyrics; the hosted API is keyless. **Endpoint specifics,
  the requested `User-Agent` politeness header, and current rate guidance live at
  [lrclib.net/docs](https://lrclib.net/docs) — confirm there before wiring it in** (they weren't in
  the GitHub README). ([tranxuanthang/lrclib](https://github.com/tranxuanthang/lrclib))
- **First-party lyrics APIs (Genius/Musixmatch/etc.)** carry **licensing caveats** — most license
  lyrics text and restrict storage/redisplay; beets' `lyrics` plugin already brokers these. LRCLIB
  is the cleanest "fetch it ourselves" path precisely because it sidesteps that licensing thicket.

---

## What's unproven / needs a spike

1. **[Highest value, lowest risk] The cross-check gate itself.** Prototype a rule that, before
   auto-landing, compares the AcoustID-chosen artist/title against the yt-dlp title/uploader and
   **diverts to the review queue on hard divergence.** Try it *first as plain fuzzy matching*, then
   as an LLM (Haiku) pick/veto. Measure: does it catch Pa Salieu without flooding the review queue
   with false diversions? This is the actual fix for the trigger bug and it may not need an LLM at
   all.
2. **Does ShazamIO measurably catch AcoustID's misses on this corpus?** No published evidence
   (§3). Spike: run ~30–50 real UK-rap/grime/dancehall rips (Topic and non-Topic) through
   AcoustID-alone vs AcoustID+ShazamIO+reconciler; count correct auto-lands and confident-wrong
   auto-lands. Only this tells you if ShazamIO earns its risk.
3. **ShazamIO reliability under real use.** Unknown rate limits / ban behavior / breakage
   cadence (§1). Spike must log failures and confirm the pipeline stays correct when ShazamIO
   returns nothing.
4. **LLM confident-hallucination rate as reconciler.** No prior-art failure numbers (§4).
   Constrain the LLM to choose-among/veto candidates (structured output, no free-generation) and
   measure whether it ever *invents* a wrong answer the candidates didn't contain.
5. **ADR-005 tension.** "beets is the engine, never hand-roll one." A reconciler that *post-
   processes beets' candidate list and can veto an auto-land* is arguably a complement, not a
   replacement — but it should be written up as an ADR before building, because it changes who has
   final say over an auto-land.

---

### Sources
- ShazamIO — https://github.com/shazamio/ShazamIO ; https://api.github.com/repos/shazamio/ShazamIO
- Shazam user agreement — https://shazam.net/shazamwebapps/user_agreement.html
- Chromaprint — https://github.com/acoustid/chromaprint
- AcoustID — https://acoustid.biz/
- Wang 2003 (Shazam algorithm) — https://www.ee.columbia.edu/~dpwe/papers/Wang03-shazam.pdf
- beets MusicBrainz plugin — https://beets.readthedocs.io/en/latest/plugins/musicbrainz.html
- Picard vs beets — https://slashdot.org/software/comparison/MusicBrainz-Picard-vs-beets/
- MetaBrainz matching-accuracy thread — https://community.metabrainz.org/t/matching-accuracy-and-apple-itunes-match/485953
- Cover Art Archive API — https://musicbrainz.org/doc/Cover_Art_Archive/API
- iTunes Search API — https://performance-partners.apple.com/search-api
- Deezer terms of use — https://developers.deezer.com/termsofuse
- LRCLIB — https://github.com/tranxuanthang/lrclib ; https://lrclib.net/docs
- Model pricing — `claude-api` skill (cached model table, 2026-06-24)
