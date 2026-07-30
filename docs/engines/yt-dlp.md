# yt-dlp — capabilities, limits, cost model, gotchas

The download stage (`app/download.py`, T-004). Pinned to **2026.7.4** and bumped *deliberately* —
yt-dlp releases often and YouTube breaks older pins fast, so a bump means re-verifying a real
download.

This page covers **the tool's behaviour**. The module's own decisions (URL classification, the
one-song contract) are documented at length in `app/download.py`'s docstrings and are not restated
here. Tag convention in [`README.md`](README.md).

## 1. The three behaviours that have actually bitten

### `extract_info(download=True)` downloads *everything* before it returns

**This is the sharp edge.** On a collection-shaped result, yt-dlp pulls **every entry** into staging
before handing anything back `[measured]` 2026-07-2x, `learnings.md`. A mistyped channel or
`@handle` URL would drag the entire channel onto disk before any post-extract guard could fire.

**`noplaylist=True` does not save you here.** It only picks the single video out of a
`watch?v=…&list=…`; a channel URL **names no single video**, so there is nothing to single out.

**Consequence for any caller:** the URL must be judged *before* `extract_info` is reached, not
after. `names_one_song` does that at the route; the post-extract check in `download_song` is
belt-and-braces, not the guard. → the validator lesson this produced: `learnings.md` (T-027).

### A scheme-less URL silently falls through to the *generic* extractor

yt-dlp picks its extractor by **regex over the raw string**, and no YouTube `_VALID_URL` pattern
matches without a scheme `[measured]` 2026-07-19. So `youtu.be/<id>` — exactly what a copy from a
text message looks like — reaches the **generic** extractor, which is not a YouTube extractor and
**does not honour `noplaylist`**, by then the sole one-song guarantee.

**Consequence: the normalised string is what must be stored and downloaded**, not just what gets
classified. → the general rule: `learnings.md` 2026-07-19.

### A `403 Forbidden` at download can be purely transient

One job errored at `download`; **the same URL through the same code succeeded minutes later,
unchanged** `[measured]` 2026-07-28.

**The `--js-runtimes node` explanation was tested directly and refuted** — with and without a JS
runtime the same video downloaded **byte-identically (3,385,336 B)** `[measured]`.

So **a 403 here is not evidence of a cause** — retry once before diagnosing one. And the JS-runtime
note (2026-07-25) describes **metadata extraction in a bare sandbox**, a different operation; it is
a real finding that does not generalise to download 403s. → `learnings.md` 2026-07-28.

## 2. Capabilities relied on

| Option | Why it's there |
|---|---|
| `format: "bestaudio/best"` | audio only; **no transcode here** — that's T-005 / ADR-002 |
| `postprocessors: [FFmpegMetadata]` | the API equivalent of `--embed-metadata` |
| `noplaylist: True` | **load-bearing, not a backup** — see below |
| `outtmpl: "%(id)s.%(ext)s"` | stable, filesystem-safe name; ext filled by the chosen stream |

**`--embed-metadata` is not optional.** A bare `-x` rip strips tags → beets runs an **empty**
MusicBrainz query → **HTTP 400** `[measured]`, `learnings.md`. The embedded title/artist is also the
tag fallback when the match is weak.

**`noplaylist=True` is the sole one-song guarantee.** It was once a second guard behind a classifier
that refused every `list=` URL. Since 2026-07-18 the classifier deliberately **accepts** a song
carrying a `list=` — YouTube appends `&list=RD…` by itself whenever you play from Liked Videos or a
search result, so refusing them **blocked the owner's primary flow outright** while protecting
nothing. Verified live against the exact radio URL: yt-dlp returned **one** line, the named track
`[measured]` 2026-07-18. Do not delete this option as redundant.

→ the two validator rules this produced: `learnings.md` 2026-07-18.

**The final path is on `requested_downloads`, not `prepare_filename`.** The latter is only the
pre-postprocess guess; after `FFmpegMetadata` runs, the container may differ. Reading the guess
surfaces as a mis-attributed `FileNotFoundError` two stages later, in the transcode.

## 3. Failure modes and how they present

| Cause | How it presents | What to do |
|---|---|---|
| Transient YouTube refusal | `HTTP Error 403: Forbidden` | **retry once** before diagnosing |
| **Private** playlist | generic *"invalid URL" / can't-resolve*, **no hint that visibility is the cause** `[measured]` 2026-07-14 | check the privacy setting first — a playlist must be public or unlisted. Hours lost to this once |
| Collection-shaped result | `_type` in `playlist`/`multi_video`, or non-empty `entries` | fail on the **download** stage with a clear reason |
| No JS runtime *(bare sandbox, metadata extraction)* | `403` on a from-scratch pull | `yt-dlp --js-runtimes node` — **and see §1**: this does *not* explain in-app download 403s |

**Test `entries` by truthiness, not key presence** — a single video can carry an empty `entries` and
must not be mistaken for a collection.

## 4. Cost model

Network-bound, seconds to tens of seconds, **blocking** — so it never runs on the asyncio event loop
(`app/jobs.py:11`, ADR-001). No rate limiter in play; YouTube throttles by its own rules, which are
undocumented and change. There is no batching to exploit: ADR-001 makes the pipeline sequential, and
R1 takes exactly one song per run.

The two pure, network-free classifiers (`is_playlist_url`, `names_one_song`) are free and run on
every `POST /api/jobs` — which is the point: the expensive mistake is reaching `extract_info` at all
with a bad URL.

## 5. On the version pin

`yt-dlp==2026.7.4`. **Bump deliberately, and re-verify a real download when you do** — this is the
one dependency where "it installed fine" tells you nothing. YouTube-side changes break extraction
without any local signal, and the failure surfaces as a 403 or an opaque extractor error rather than
as an import failure.

## 6. Open — not established

- **`[assumed]`** Whether the in-app download path uses a different client than a bare CLI pull.
  `learnings.md` 2026-07-25 speculates it ("ran before this tightened / use a different client
  path") and the 2026-07-28 byte-identical test makes the whole question moot for 403 diagnosis.
  Left open because it was never settled, not because it matters today.
- **Unknown** — YouTube's actual throttling thresholds. Never hit at one-song-per-run.
