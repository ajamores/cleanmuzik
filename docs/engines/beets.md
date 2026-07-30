# beets 2.12 — capabilities, limits, cost model, gotchas

The tagging engine (ADR-005: never hand-roll one). Pinned to **2.12.0** on purpose — `importer` and
`autotag` are not beets' stable API. Paths below are relative to
`server/.venv/lib/python3.14/site-packages/`; see [`README.md`](README.md) for the `[source]` /
`[measured]` / `[assumed]` convention.

## 1. Two seams, and they are not interchangeable

beets offers two ways in, and almost every mistake in this repo's history comes from treating them
as one.

| | **Import seam** | **Read/search API** |
|---|---|---|
| Entry | `importer` pipeline, driven by `app/import_seam.py` | `autotag.tag_item`, `metadata_plugins.*` |
| Runs plugin stages? | **Yes** — this is the only thing that does | **No** |
| Produces | a tagged file on disk, with art and genre | in-memory `TrackInfo` / `AlbumInfo` |
| Writes to the library? | yes | no |
| Used for | acquiring a track (the everyday flow) | re-search, candidate lists, scoring |

**What the stages give you, and what bypassing them costs.** The six plugins load in a fixed order
— `musicbrainz` must precede `chroma` (ADR-007) — and only the importer runs them:

| Plugin | Provides | Lost if you bypass the importer |
|---|---|---|
| `musicbrainz` | the match itself | — (the read API reaches it directly) |
| `chroma` | AcoustID fingerprint → recording id | fingerprint matching; see [`acoustid.md`](acoustid.md) |
| `lastgenre` | genre tag from Last.fm | genre. Currently lost anyway — no API key set |
| `fetchart` | cover art download | art |
| `embedart` | art embedded into the MP3 | art in the file (Jellyfin reads it from there) |
| `lyrics` | lyrics sidecar | lyrics (and see backlog T-023/T-030 on Jellyfin's second scan) |

**In beets 2.12 MusicBrainz is itself a plugin**, not core — and the library API never auto-loads
plugins, so `beets.plugins.load_plugins()` must be called explicitly or `chroma` never fingerprints
`[source]` — `app/beets_engine.py:11-19,121` records this; ADR-007 binds it.

### The `never call autotag.tag_item directly` rule — its actual scope

Stated flat in three places: `docs/r1/architecture.md:35`, `docs/r1/spec.md:29`,
`docs/r1/tickets.md:132`. **The reason is real but import-specific:** `tag_item` runs no plugin
stages, so a track tagged through it gets no art and no genre.

**Scope: the rule governs the acquire path, where stages are the point. It does not govern a
read-only search** that lands nothing and writes nothing — that case was never what the rule was
about. Give the rule its scope; don't soften the verb.

**Correction to T-038's own filing.** The ticket records a nuance — that the rule reached the right
answer anyway because *"`tag_item` internally calls `item_candidates`, which is the 27-second
path."* That is true only for one of its two call forms `[source]` `beets/autotag/match.py:485-540`:

- `tag_item(item)` **with no `search_ids`** → falls through to `metadata_plugins.item_candidates`
  at `match.py:530` → the expensive path. The nuance holds, and this is the form that was
  contemplated.
- `tag_item(item, search_ids=[…])` → takes the `tracks_for_ids` branch at `match.py:505-509` and
  **returns at `match.py:518-522` without ever reaching `item_candidates`.**

So the nuance needs its own scope line — which is, with some irony, the exact defect the ticket was
filed to fix. Neither form was cheap enough to use here, so the conclusion is unchanged.

## 2. Cost model — which calls fan out into N requests

**This is the section that pays for the page.** beets hides request count behind method names that
read like single operations.

`item_candidates` is **1 + N requests**, where N = `search_limit` `[source]`
`beets/metadata_plugins.py:448-452`:

```python
def item_candidates(self, item, artist, title):
    results = self._get_candidates("track", [item], artist, title, False)   # 1 search request
    return filter(None, self.tracks_for_ids(r["id"] for r in results))      # + one request EACH
```

The trap is `tracks_for_ids`. Its docstring says *"Batch lookup"* and *"Plugins may implement this
for optimized batched lookups"* — but the **default implementation is a generator expression, one
HTTP call per id** `[source]` `beets/metadata_plugins.py:261-270`:

```python
return (self.track_for_id(id_) for id_ in ids)
```

…and **beets' MusicBrainz plugin does not override it** `[source]` — verified absent from both
`beetsplug/musicbrainz.py` and `beetsplug/_utils/musicbrainz.py`. `MusicBrainzPlugin` inherits
`item_candidates` from `SearchApiMetadataSourcePlugin` (`metadata_plugins.py:351`) and
`tracks_for_ids` from `MetadataSourcePlugin` (`:172`), so the fan-out is inherited silently, with no
MusicBrainz-specific code to read.

Each `track_for_id` is one `GET /ws/2/recording/{id}` carrying `RECORDING_INCLUDES` — artists,
aliases, ISRCs, work-level and artist relations `[source]` `beetsplug/_utils/musicbrainz.py:69-75,
692-697`.

**What that costs, measured.** At `search_limit=25`: 1 search + 25 lookups = 26 serialised
round-trips at ~1.04 s each → **26.8 / 28.9 / 27.7 s** for three identical searches, flat every time
— there is no cache to warm `[measured]` 2026-07-30, live server, `learnings.md` same date. Building
rows from the search response instead: **0.3–1.0 s**.

**The search response already carried all four fields anything downstream reads** — see
[`musicbrainz.md`](musicbrainz.md) §3 for the payload comparison. → the three rules this produced
(what to check before hydrating, why this latency class is invisible to tests, and what a result
limit multiplies): `learnings.md` 2026-07-30.

## 3. Rate limiting — one shared bucket, process-wide

Three mechanisms stack, and the sharing is the part that bites.

**The session is a singleton** `[source]` `beetsplug/_utils/requests.py:44-65`.
`TimeoutAndRetrySession` uses `metaclass=SingletonMeta`, which keeps one instance **per class** in a
process-wide dict. `LimiterTimeoutSession(LimiterMixin, TimeoutAndRetrySession)` inherits it. So
every caller in the process shares one session — *including callers on different threads*.

That is the mechanism behind the starvation: **a re-search on the web thread and the acquire
pipeline are the same token bucket**, so one 27 s re-search stalled a running import for the whole
27 s `[measured]` 2026-07-30.

**Two limiters on top of it:**

- `RateLimitAdapter(rate_limit=0.25)`, mounted for `http://` and `https://` on the base session — a
  0.25 s minimum gap (4 req/s ceiling), enforced by **sleeping while holding a lock** in `send()`
  `[source]` `beetsplug/_utils/requests.py:89-131`. Process-wide, all hosts.
- `LimiterMixin(per_second=…)` for MusicBrainz specifically — **1.0 req/s**, the binding constraint.
  Details in [`musicbrainz.md`](musicbrainz.md).

Also on the base session: retries with `total=6, backoff_factor=0.5` on 500/502/503/504/**429**
`[source]` `_utils/requests.py:78-88`. A rate-limit rejection is therefore retried with backoff
rather than surfaced — which makes over-limit traffic look like *slowness*, not an error.

> **`[assumed]` — a hazard worth knowing, not yet hit.** `SingletonMeta.__call__` uses its
> constructor arguments **only on the first instantiation** and silently discards them thereafter
> `[source]` `_utils/requests.py:55-62`. So the *first* code path to construct a
> `LimiterTimeoutSession` fixes `per_second` for every later one. Benign today — MusicBrainz is the
> only constructor and its rate is hardcoded — but if a second plugin ever builds one with a
> different rate, whichever runs first wins process-wide, silently. Not observed; flagged.

## 4. Config — what is global and what is per-plugin

The distinction that motivated a fork nobody needed (`learnings.md` 2026-07-30).

**`search_limit` is a per-plugin node, default 5.** It is added to `self.config` — the *plugin's*
subtree — in `MetadataSourcePlugin.__init__` `[source]` `beets/metadata_plugins.py:199-204`. So
`musicbrainz.search_limit` is scoped to the `musicbrainz` plugin; it is **not** the global config
tree, and a scoped set/restore is legitimate.

That said, per-plugin is **not** per-request: the acquire pipeline reads the same node, so mutating
it from a web thread still widens every concurrent park's candidate list. This is why `mb_search.py`
passes the limit **explicitly as an argument** instead — the right call, reached originally via the
wrong reason (`app/mb_search.py:35-42`).

Other config worth knowing:

- `musicbrainz.ratelimit` / `ratelimit_interval` — **silently ignored against the official host.**
  See [`musicbrainz.md`](musicbrainz.md) §2; this one is a genuine trap.
- `musicbrainz.searchlimit` (no underscore) — deprecated alias, still honoured with a warning,
  marked *TODO: remove in 3.0.0* `[source]` `beetsplug/musicbrainz.py:305-313`.
- `data_source_mismatch_penalty` / `source_weight` — default **0.5** `[source]`
  `metadata_plugins.py:180,190-195`.
- `acoustid.apikey` — used by `chroma` for **submission** only; lookups use beets' built-in key
  (`app/beets_engine.py:110-113`). See [`acoustid.md`](acoustid.md).

## 5. Gotchas already paid for

- **`artist-credit` arrives as `artist_credit`.** beets normalizes MusicBrainz's hyphenated field
  names to underscores. Reading the hyphenated name gives `artist=None` and fails **silently as a
  ranking bug, not an error** — title and duration still score, so the list comes back plausibly
  ordered `[measured]` 2026-07-30. Build API-shape fixtures from a **captured real response**, never
  from upstream docs, when a client library sits in between.
- **`incl_artist=True` is load-bearing on singletons.** beets' default omits the artist from a
  singleton's distance, scoring Coldplay and Frank Ocean identically at 0.571 on the same title
  `[measured]` — details in `app/mb_search.py:19-25`.
- **Plugins never auto-load via the library API** (ADR-007) — covered in §1.
- **beets deletes the old file before copying the new one**, which is why ADR-009 forbids
  auto-replace: a failed copy loses both (`docs/backlog/README.md`).
- **beets shells out to `fpcalc`** and blocks for seconds, so the pipeline must never run on the
  asyncio event loop (`app/jobs.py:11`, ADR-001).

## 6. Re-check on a version bump

The line numbers here are stable only while `beets==2.12.0` holds. On a bump, re-verify in this
order — each is a claim that has already cost something:

1. `tracks_for_ids` still not overridden by the MusicBrainz plugin (§2)
2. the session still a singleton, and the MusicBrainz rate still hardcoded (§3)
3. `search_limit` still a per-plugin node (§4)
4. `searchlimit` deprecation — **removal is scheduled for 3.0.0** (§4)
