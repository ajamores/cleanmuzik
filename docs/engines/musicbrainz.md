# MusicBrainz WS/2 — capabilities, limits, cost model, gotchas

The metadata authority. CleanMuzik never speaks to it directly — everything goes through **beets'
own built-in HTTP client** (`beetsplug/musicbrainz.py` + `beetsplug/_utils/musicbrainz.py`; no
`musicbrainzngs` dependency in 2.12). That intermediary is the source of most of the surprises here,
so read [`beets.md`](beets.md) §2–§4 alongside this.

Paths are relative to `server/.venv/lib/python3.14/site-packages/`. Tag convention in
[`README.md`](README.md).

## 1. The search API almost never returns zero results

**The single most load-bearing fact on this page, and it inverts the obvious design assumption.**

MusicBrainz search matches **loose tokens**, not phrases. A deliberate-nonsense search returned
**25 results** `[measured]` 2026-07-29 (ADR-020 amendment; full measurement in `learnings.md`).

So "this song is not in MusicBrainz" **does not present as an empty list.** It presents as *many
results, all wrong, best score ~0.40* — the wrong-but-present dead end, one level down.

**A low score does not mean absence either.** On the Nines fixture the *correct* answer sits at
**0.757** among five near-identical rows `[measured]`, so no score threshold separates "wrong" from
"not there".

→ what this binds in the product (don't gate an exit on a zero count, don't invent a confidence
bar): the ADR-020 amendment, with ADR-006 and ADR-010 behind it.

**Relevance ordering is not stable between identical calls.** The Nines fixture's known-correct
recording (`f5d1bcfb…`) sits at the boundary of a five-result window and **drifts in and out of it**
across identical searches `[measured]` — which is why `SEARCH_LIMIT = 25` rather than beets' default
of 5 (`app/mb_search.py:35-42`). A limit is not just "how many you show"; at the default it decides
whether the right answer is *present at all*.

**A filter-less query is an HTTP 400**, two round-trips after the mistake `[source]`
`app/mb_search.py` `clean_terms` docstring. Artist-only and title-only are both legal half-queries.

## 2. Rate limits — 1.0 req/s, and the config key that does nothing

The official host is pinned to **1.0 req/s**, and this is the number that governs every cost
estimate in these pages.

The trap `[source]` `beetsplug/_utils/musicbrainz.py:586-606`:

```python
mb_config.add({"host": "musicbrainz.org", "https": False,
               "ratelimit": 1, "ratelimit_interval": 1})
hostname = mb_config["host"].as_str()
if hostname == "musicbrainz.org":
    self.api_host, self.rate_limit = "https://musicbrainz.org", 1.0   # <- hardcoded
else:
    ...  self.rate_limit = ratelimit / ratelimit_interval             # <- config honoured
```

**`musicbrainz.ratelimit` and `ratelimit_interval` are registered as config keys and then silently
ignored against the official host.** They apply only when `host` points somewhere else (a local
mirror). Setting them on the default host looks like tuning and does nothing — no warning, no error.
Likewise `https: False` is overridden to HTTPS for the official host.

**The bucket is shared process-wide, across threads** — the session is a singleton (`beets.md` §3).
A search issued from the web thread and the acquire pipeline draw on the same 1.0 req/s. This is not
a theoretical concern: one 27 s re-search starved a running import for its full duration
`[measured]` 2026-07-30.

**429s are retried with backoff, not raised** (`total=6, backoff_factor=0.5`, `[source]`
`_utils/requests.py:78-88`). Over-limit traffic therefore manifests as *slowness*, never as an
error you can catch. If a route gets mysteriously slow, suspect the limiter before suspecting the
network.

## 3. Cost model — search response vs per-id lookup

| Call | Requests | What comes back |
|---|---|---|
| `GET /ws/2/recording?query=…&limit=N` | **1** | N rows: `id`, `title`, `artist-credit`, `length` (~75% of rows), `score` |
| `GET /ws/2/recording/{id}` (`track_for_id`) | **1 per id** | the above **plus** aliases, ISRCs, work-level relations, artist relations |

`RECORDING_INCLUDES` — what the per-id lookup adds — is `artists, aliases, isrcs, work-level-rels,
artist-rels` `[source]` `_utils/musicbrainz.py:69-75, 692-697`.

**The search response already carries everything beets' scorer reads.** `track_distance` reads only
`length`, `title`, `artist`, `index`, `track_id`, `medium`, `data_source` — and `index`/`medium` are
`None` on a recording lookup too, so nothing is lost by not asking (`app/mb_search.py` `_track_info`).

Hence the rule: **hydrating search results by id is pure waste here.** 26 round-trips, ~27 s, for
fields already in hand `[measured]` — the full arithmetic is in [`beets.md`](beets.md) §2.

**`length` is absent on roughly a quarter of search rows** `[measured]` (~19 of 25 on the fixtures).
It stays `None` there rather than becoming `0.0`: a *wrong* duration corrupts ranking harder than a
missing one — an invented 193 s lifted three wrong candidates above the right one `[measured]`.
Those rows skip the duration penalty and can rank slightly high; accepted, per ADR-020's bar that
the right recording be *present*, not first.

**Units: MusicBrainz reports `length` in milliseconds; beets scores in seconds.** Divide by 1000
(`app/mb_search.py` `_track_info`). A silent 1000× error in a distance function does not raise —
it just ranks everything wrongly.

## 4. Recording vs release — the distinction ADR-010 turns on

**A recording is a performance; a release is a product it appears on. One recording appears on
many releases.**

This is why a review candidate is `title + artist + score` and nothing more. beets builds a
singleton candidate through `item_candidates → tracks_for_ids → track_for_id → track_info(recording)`
— a **recording** payload, carrying title, artist, track_id, length, ISRC.

**Album, year and cover art are properties of a release**, so nothing in a recording payload carries
them. **The cost of reaching them is the fact worth knowing:** one extra browse-releases call **per
candidate** at 1.0 req/s, plus a heuristic to choose *which* release.

Cover art still reaches the **file** via `fetchart`/`embedart` — that path goes through the importer
and does have a release.

→ what was decided about the resulting nulls, and the process change that miss forced: **ADR-010**
and the Definition of Done's acceptance check in `CLAUDE.md`.

## 5. Gotchas already paid for

- **`artist-credit` → `artist_credit`.** beets normalizes hyphenated MusicBrainz field names to
  underscores. Reading the hyphenated name yields `artist=None` on every row and fails **silently as
  a ranking bug** — title and duration still score, so the list looks plausibly ordered with the
  right answer near the top `[measured]` 2026-07-30. Build fixtures from a **captured real
  response**, never from the upstream API docs, whenever a client library sits in between.
- **An artist credit is a list, not a string.** Parts of `{name, artist, joinphrase}` — "Nines feat.
  J. Stone" arrives as two parts with a joinphrase. Concatenating names alone loses the join
  (`app/mb_search.py` `_artist_credit`).
- **MusicBrainz `score` (0–100) is not beets' score.** The candidate `score` in this app is
  `1 − beets' tag distance`, computed locally. Both fixtures sit at MusicBrainz score **100** while
  scoring very differently in beets. Don't conflate them.
- **Covers collide by design.** *Strawberry Swing* by Coldplay and by Frank Ocean are genuinely the
  same title; without `incl_artist=True` they score identically at 0.571 `[measured]`. See
  [`beets.md`](beets.md) §5.

## 6. Open — not established

- **`[assumed]`** The ~25% `length`-absent rate comes from two fixtures at `limit=25`. Treated as
  "often missing", not as a rate. Don't quote it as a statistic.
- **`[assumed]`** MusicBrainz publishes a 1 req/s guideline for anonymous clients and higher
  allowances for authenticated ones. beets 2.12 sends only a User-Agent `[source]`
  `_utils/requests.py:76`; whether an authenticated path exists here has **not** been investigated.
  Relevant only if throughput ever matters, which under ADR-001's sequential pipeline it does not.
