# AcoustID + Chromaprint — capabilities, limits, cost model, gotchas

**The live identification tier.** Fingerprint the audio, get a MusicBrainz recording id back. This is
what makes the queue small: T-008 measured **88% auto-accept (22/25, 0 wrong)**.

Three distinct things, routinely conflated:

| | What it is | Where it lives |
|---|---|---|
| **Chromaprint** | the fingerprint *algorithm* | `fpcalc`, a **system binary** — not a pip dependency |
| **`pyacoustid`** | the Python client | `acoustid.py` (top-level module in site-packages) |
| **AcoustID** | the *web service* mapping fingerprints → MBIDs | `http://api.acoustid.org/v2/` |

Reached by **two independent paths**: beets' `chroma` plugin during import, and `app/jobs.py:49`
which imports `acoustid` directly to catch `NoBackendError`. Paths below are relative to
`server/.venv/lib/python3.14/site-packages/`; tag convention in [`README.md`](README.md).

## 1. Correction: `ACOUSTID_APIKEY` does not do what `.env.example` says

`.env.example` states the key is *"OPTIONAL — beets' built-in key works… **Set only for higher rate
limits**."* **The second half is wrong** `[source]`:

- **Lookups always use beets' hardcoded key**, unconditionally: `API_KEY = "1vOwZtEn"`
  (`beetsplug/chroma.py:43`), passed straight into `acoustid.lookup(API_KEY, …)` at
  `chroma.py:111-112`. Nothing consults config on this path.
- **`config["acoustid"]["apikey"]` is a *user* key for submission only**, read exclusively by the
  `beet submit` CLI subcommand (`chroma.py:274`) and `submit_items` (`chroma.py:402`). **CleanMuzik
  never submits fingerprints**, so today the setting has no effect at all.

`app/beets_engine.py:110-113` already says this correctly ("chroma uses this for AcoustID
*submission*; lookups use beets' built-in"). **`.env.example` is the file that's wrong** — fix it
there, and don't set the key expecting throughput.

## 2. Hard limits — the ones that decide whether you get an answer

**Only the first 120 seconds are fingerprinted.** `MAX_AUDIO_LENGTH = 120` `[source]`
`acoustid.py:43`, the default for both `fingerprint()` and `fingerprint_file()`. Two tracks that
differ only after two minutes are indistinguishable to this tier — plausibly relevant to the
`"Franklin"` music-video-edit residual (T-035), though **`[assumed]`**: not tested.

**A match below 0.5 is discarded silently.** `SCORE_THRESH = 0.5` `[source]` `chroma.py:44,128`.

**Only the single best result is considered.** `result = res["results"][0]` `[source]`
`chroma.py:127` — the rest of the response is dropped, then bounded further by `MAX_RECORDINGS = 5`
and `MAX_RELEASES = 5` `[source]` `chroma.py:47-48,235,252`.

**Rate limit: 3 req/s, its own limiter.** `REQUEST_INTERVAL = 0.33` `[source]` `acoustid.py:42`,
enforced by a thread-safe `_rate_limit` decorator holding a lock and sleeping `[source]`
`acoustid.py:153-180`. **This is a separate bucket from beets' 1.0 req/s MusicBrainz limiter** — the
two do not interact, and AcoustID is never the bottleneck under ADR-001's sequential pipeline.

**The API is plain HTTP.** `API_BASE_URL = "http://api.acoustid.org/v2/"` `[source]`
`acoustid.py:40` — not HTTPS. Irrelevant on a single-user localhost tool (ADR-004), noted so nobody
"discovers" it twice.

## 3. The gotcha that matters most: a lookup failure is indistinguishable from "no match"

`acoustid_match` **catches and logs both failure classes, then returns `None`** — the same thing it
returns when nothing matched `[source]` `chroma.py:95-124`:

```python
except acoustid.FingerprintGenerationError as exc:
    log.error(...); return          # fingerprinting broke
...
except acoustid.AcoustidError as exc:
    log.debug(...); return          # the web service broke  <- log.debug!
```

So a network outage, a rate-limit rejection and a genuinely unknown track are **the same event
downstream**: the track parks. Fail-soft, which is the behaviour ADR-019 relies on — but it means
**"AcoustID missed" in this repo's logs never distinguishes "wasn't in the database" from "couldn't
ask".** The web-service failure is logged at `debug`, so at default log level it is invisible.

Consequence for any future measurement: **an AcoustID miss rate computed from parked reviews is an
upper bound, not a miss rate.** Don't quote one without checking the debug log first.

The one exception that *does* escape is `NoBackendError` — `fpcalc` missing entirely — which
`app/jobs.py:335` catches and turns into a stage failure rather than a park. Correct: a vanished
fingerprint backend is an environment fault, not a property of the track.

## 4. `fpcalc` — a system binary, and the WSL trap

`chroma` shells out to `fpcalc`; **pip will not install it.** `pyacoustid` honours `$FPCALC` and
otherwise falls back to `fpcalc` on `PATH` (`app/beets_engine.py:142-171`; setup in
`server/README.md`).

**Do not gate on the execute bit.** `_resolve_fpcalc` uses `os.path.isfile`, **not**
`os.access(X_OK)`, deliberately: on a WSL `/mnt/c` mount a Windows-downloaded binary frequently
lacks the Unix execute bit **yet execs fine**, because pyacoustid just subprocesses it and never
checks `X_OK` `[source]` `app/beets_engine.py:150-155`. The real runnability test is the `-version`
probe, and a found-but-unrunnable binary surfaces as a missing version rather than a missing path.

**It blocks for seconds.** Hence ADR-001 and `app/jobs.py:11` — the pipeline never runs on the
asyncio event loop.

**Plugin order is binding:** `musicbrainz` must precede `chroma`, because AcoustID lookups return
MBIDs that `chroma` needs the MusicBrainz plugin to resolve (ADR-007; `chroma.py:200`,
`app/beets_engine.py:47-54`).

## 5. Cost model

| Step | Cost |
|---|---|
| `fingerprint_file` | local CPU, seconds, first 120 s of audio only; **blocking** |
| `acoustid.lookup` | **1** HTTP request, `timeout=10`, `meta="recordings releases"` `[source]` `chroma.py:111-112` |
| resolving returned MBIDs | MusicBrainz requests, bounded by `MAX_RECORDINGS`/`MAX_RELEASES` = 5 each — **at 1.0 req/s**, see [`musicbrainz.md`](musicbrainz.md) |

The AcoustID call itself is cheap and single. **The cost lands downstream in MusicBrainz**, on the
slower limiter — which is the general shape of every cost surprise in this codebase.

## 6. Where it misses, and what that unblocked

AcoustID's database is crowd-sourced Chromaprint data; Shazam's is consumer-scale. AcoustID tends to
miss exactly the commercial/label tracks Shazam is strongest on (T-035) — which is the entire
argument for ADR-019's backup tier.

Two documented residuals, neither an obscure artist `[measured]` 2026-07-25/27:

- **The Nipsey Hussle rip** AcoustID could not fingerprint at all — Shazam identified it cold.
- **Frank Ocean's *Strawberry Swing*** — AcoustID silent, and the live T-103 fixture.

**A hypothesis worth not forgetting, still unsettled.** Coldplay tops Frank Ocean's live candidate
list at 0.52 and nobody has explained how. If AcoustID fingerprint-matched the *shared instrumental*
— *nostalgia, ULTRA* is sung over the original masters — the candidates arrived **by sound, not by
title-mangling**, which would explain why reproducing it as a title search returned 0 hits.
**`[assumed]`, explicitly** — settling it needs the actual query logged (T-034's instrumentation
item).

## 7. Open — not established

- **`[assumed]`** Whether the 120 s fingerprint window explains the `"Franklin"` music-video-edit
  miss. Cheap to test: fingerprint the edit and the album cut, compare.
- **`[assumed]`** AcoustID's per-key rate policy beyond the client's self-imposed 3 req/s. Never
  hit, never investigated; under ADR-001 it is unlikely to matter.
- **Unknown** — the real AcoustID miss rate, for the reason in §3: the logs cannot currently tell a
  miss from an outage. Fixing that is a one-line log-level change if the number is ever wanted.
