"""Thin MusicBrainz candidates for the acquire path (T-208).

## What this collapses

Identifying one song fired ~11 serialized MusicBrainz `recording/<id>` lookups behind
MB's global 1/sec limit (T-218's profile), and that fan-out was 80–90% of the identify
gate *and* its entire variance. The waste has **two** independent sources that meet in
`beets.autotag.match.tag_item`:

1. **chroma's fan-out** — `AcoustidPlugin.item_candidates` calls `track_for_id` once per
   fingerprint recording id (up to `MAX_RECORDINGS`, default 5).
2. **the MusicBrainz plugin's fan-out** — its inherited `item_candidates` runs one search,
   then hydrates each result by id (`tracks_for_ids` → `track_for_id`, `search_limit`=5).

They overlap, which is the "same MBID hydrated twice" T-218 caught (`tag_item` de-dupes by
id only *after* both network calls were paid).

## The fix, in two patches installed here

Both producers already hold everything scoring reads — `track_id`, `title`, `artist`,
`length` — in a response they've *already* fetched (the MB search response; the AcoustID
lookup's `meta=recordings`). The stock code throws that away and re-fetches each id. These
patches build a **thin** `TrackInfo` from the in-hand data instead, marked `cm_thin` so the
seam re-hydrates the ONE recording that actually lands (`import_seam._ensure_full_match`) —
never landing a hollow file. Auto-land goes ~11 MB calls → 1 (the winner); the search and
the AcoustID lookup are themselves untouched.

- `install_thin_candidates()` — patches fan-out #2 (Step 2).
- `install_thin_chroma()` — patches fan-out #1 (Step 3).

Both are installed from `configure_beets()` after `load_plugins()`, so every entry point
(acquire, resolve, re-search) sees one consistent engine.

**Parity is the whole correctness story.** A thin candidate's `title`/`artist`/`length`
must be byte-identical to what full hydration produces, because they feed `track_distance`
(candidate order, the persisted score) and the reconcile LLM's evidence. So the title and
artist are built with the MusicBrainz plugin's *own* helpers (`_key_with_preferred_alias`,
`_parse_artist_credits`), not a reimplementation — with a guarded fallback for the fields a
search row can lack. The acceptance gate (T-208 "Done when") is a measured land/park +
tag + timing compare against the current engine over the spike corpus.

Beets-heavy at module scope, so every beets import is inside the function that needs it —
the same lazy-engine discipline as `mb_search`/`import_seam` (T-001).
"""

import logging

logger = logging.getLogger("cleanmuzik")


def _thin_title(row: dict) -> str | None:
    """The row's title, using the plugin's alias-preference so it matches full hydration.

    `track_info` builds titles via `_key_with_preferred_alias`; mirror it so a preferred
    alias produces the same string here as it would after a full lookup. A search row that
    lacks the alias structure falls back to the plain title rather than raising.
    """
    try:
        from beetsplug.musicbrainz import _key_with_preferred_alias

        return _key_with_preferred_alias(row, key="title")
    except Exception:  # noqa: BLE001 — a lighter search row just costs the alias
        return row.get("title")


def _fallback_artist_credit(row: dict) -> str | None:
    """Concatenate the artist-credit parts by hand (names + joinphrases).

    The fallback when the plugin's `_parse_artist_credits` can't read a search row (it
    indexes `artist.sort_name`/`artist.id`, which a lighter row may omit). Same join
    logic `mb_search._artist_credit` proved on the Frank Ocean fixture — keeps a
    multi-credit ("Nines feat. J. Stone") from collapsing to "NinesJ. Stone".
    """
    parts = row.get("artist_credit") or []
    if not isinstance(parts, list):
        return None
    out: list[str] = []
    for part in parts:
        if isinstance(part, str):  # a bare joinphrase
            out.append(part)
            continue
        if not isinstance(part, dict):
            continue
        name = (part.get("artist") or {}).get("name") or part.get("name")
        if name:
            out.append(name)
        out.append(part.get("joinphrase") or "")
    return "".join(out).strip() or None


def thin_track_info(plugin, row: dict):
    """One MusicBrainz search-response row → a thin, `cm_thin`-marked `TrackInfo`.

    Carries only the fields `track_distance` reads (`track_id`, `title`, `artist`,
    `length`) plus whatever artist granularity `_parse_artist_credits` yields for free.
    Every other tag — ISRC, genre, work/artist relations, the release ids cover art keys
    off — is deliberately absent and lands only when `_ensure_full_match` re-hydrates the
    winner. `length` stays `None` when the row omits it (absent on ~1/4 of rows), never
    0.0 — a wrong length corrupts ranking worse than a missing one (mb_search finding 2).
    """
    from beets.autotag.hooks import TrackInfo

    track_id = row.get("id")
    if not track_id:
        return None

    length = row.get("length")
    fields = {
        "track_id": track_id,
        "title": _thin_title(row),
        "length": (length / 1000.0) if length else None,  # MB reports ms; beets scores s
        "data_source": "musicbrainz",
        "cm_thin": True,
    }
    try:
        # Full-parity artist fields (artist, artist_sort, artists, artist_id, …) with no
        # network — the search row already carries the credit structure.
        fields.update(plugin._parse_artist_credits(row.get("artist_credit") or []))
    except Exception:  # noqa: BLE001 — a lighter row: keep just the concatenated string
        fields["artist"] = _fallback_artist_credit(row)
    return TrackInfo(**fields)


def _thin_mb_item_candidates(plugin):
    """A replacement `item_candidates` for the MusicBrainz plugin (fan-out #2, Step 2).

    Reuses the plugin's own `_get_candidates` — so the query, filters and `search_limit`
    are byte-for-byte the stock search (deliberately NOT mb_search's explicit 25: this is
    the acquire path, whose candidate width must not change) — then maps each response row
    through `thin_track_info` instead of `tracks_for_ids`' per-id hydration. De-dupes by id
    within the one response (MB can page the same recording twice).
    """

    def item_candidates(item, artist, title):
        results = plugin._get_candidates("track", [item], artist, title, False)
        seen: set = set()
        for row in results:
            rid = row.get("id")
            if not rid or rid in seen:
                continue
            seen.add(rid)
            info = thin_track_info(plugin, row)
            if info is not None:
                yield info

    return item_candidates


def install_thin_candidates() -> bool:
    """Patch the loaded MusicBrainz plugin's `item_candidates` to yield thin rows.

    Idempotent (re-patching the same instance is harmless). Returns True when patched.
    Called from `configure_beets()` after `load_plugins()`; a missing plugin is a
    misconfig (ADR-007 loads it) and is logged, not raised — the engine still runs, just
    without the speed win.
    """
    from beets import metadata_plugins

    plugin = metadata_plugins.get_metadata_source("musicbrainz")
    if plugin is None:
        logger.error("musicbrainz source not loaded — cannot install thin candidates")
        return False
    plugin.item_candidates = _thin_mb_item_candidates(plugin)
    logger.debug("T-208: thin MusicBrainz item_candidates installed")
    return True


# ---------------------------------------------------------------------------
# Step 3 — chroma's fan-out (fan-out #1)
#
# chroma's stock `item_candidates` hydrates each fingerprint recording id with a live
# `track_for_id`, discarding the title/artist/duration the AcoustID lookup (run with
# `meta="recordings releases"`) already returned. We fork `acoustid_match` to ALSO stash
# that metadata in a side table, then replace `item_candidates` to build thin candidates
# from it — zero network. Everything the stock function writes (`_matches`, `_fingerprints`,
# `_acoustids`, the release sort) is preserved untouched, so `track_distance`,
# `apply_acoustid_metadata` and the album `candidates`/`_all_releases` path are unaffected.
# ---------------------------------------------------------------------------

# Recording metadata already present in the AcoustID response, keyed by path then MBID:
# {path: {recording_id: {"title", "artist", "length"}}}. Populated by the forked
# acoustid_match, read by the thin item_candidates.
_chroma_recording_meta: dict = {}

# SHA-256 of the beets 2.12.0 `chroma.acoustid_match` source the fork below mirrors. A
# beets upgrade that changes that function trips the drift-guard test (test_mb_thin.py)
# so the fork is reviewed against the new upstream rather than silently diverging.
STOCK_ACOUSTID_MATCH_SHA256 = (
    "74bd9542a7056ef2a424a49f10bf6f172cc2e96256b9d008b5937c9a0c4d7229"
)


def _acoustid_artist(recording: dict) -> str | None:
    """Join an AcoustID recording's `artists` (name + joinphrase) into one string.

    AcoustID returns `artists` as `[{id, name, joinphrase}]` — the same feat.-preserving
    shape MusicBrainz uses, so the join matches `_fallback_artist_credit`'s logic.
    """
    artists = recording.get("artists") or []
    if not isinstance(artists, list):
        return None
    out: list[str] = []
    for a in artists:
        if not isinstance(a, dict):
            continue
        if name := a.get("name"):
            out.append(name)
        out.append(a.get("joinphrase") or "")
    return "".join(out).strip() or None


def _acoustid_match_with_meta(log, path):
    """Fork of `beetsplug.chroma.acoustid_match` that also captures recording metadata.

    Byte-faithful to stock (pinned by `STOCK_ACOUSTID_MATCH_SHA256`) in everything it
    writes to chroma's own dicts and the release ordering — the ONLY addition is the
    `_chroma_recording_meta[path]` side table built from `result["recordings"]`, the
    title/artist/duration the stock function reads past. Keep this in lockstep with stock
    on any beets upgrade the drift guard flags.
    """
    import beetsplug.chroma as chroma  # the real module dicts we must populate

    try:
        duration, fp = chroma.acoustid.fingerprint_file(chroma.util.syspath(path))
    except chroma.acoustid.FingerprintGenerationError as exc:
        log.error(
            "fingerprinting of {} failed: {}",
            chroma.util.displayable_path(repr(path)),
            exc,
        )
        return
    fp = fp.decode()
    chroma._fingerprints[path] = fp
    try:
        res = chroma.acoustid.lookup(
            chroma.API_KEY, fp, duration, meta="recordings releases", timeout=10
        )
    except chroma.acoustid.AcoustidError as exc:
        log.debug(
            "fingerprint matching {} failed: {}",
            chroma.util.displayable_path(repr(path)),
            exc,
        )
        return
    log.debug("chroma: fingerprinted {}", chroma.util.displayable_path(repr(path)))

    if res["status"] != "ok" or not res.get("results"):
        log.debug("no match found")
        return
    result = res["results"][0]  # Best match.
    if result["score"] < chroma.SCORE_THRESH:
        log.debug("no results above threshold")
        return
    chroma._acoustids[path] = result["id"]

    if not result.get("recordings"):
        log.debug("no recordings found")
        return
    recording_ids = []
    releases = []
    meta: dict = {}  # T-208 addition: the metadata stock throws away
    for recording in result["recordings"]:
        recording_ids.append(recording["id"])
        duration_s = recording.get("duration")
        meta[recording["id"]] = {
            "title": recording.get("title"),
            "artist": _acoustid_artist(recording),
            "length": float(duration_s) if duration_s else None,
        }
        if "releases" in recording:
            releases.extend(recording["releases"])

    country_patterns = chroma.config["match"]["preferred"]["countries"].as_str_seq()
    countries = [chroma.re.compile(pat, chroma.re.I) for pat in country_patterns]
    original_year = chroma.config["match"]["preferred"]["original_year"]
    releases.sort(
        key=chroma.partial(
            chroma.releases_key, countries=countries, original_year=original_year
        )
    )
    release_ids = [rel["id"] for rel in releases]

    log.debug("matched recordings {} on releases {}", recording_ids, release_ids)
    chroma._matches[path] = recording_ids, release_ids
    _chroma_recording_meta[path] = meta  # T-208


def _thin_chroma_item_candidates(plugin):
    """Replacement `AcoustidPlugin.item_candidates` — thin, from the side table (Step 3).

    Mirrors stock's shape (same `_matches` guard, same `prefix(recording_ids,
    MAX_RECORDINGS)`), but yields a thin `cm_thin` `TrackInfo` built from the captured
    AcoustID metadata instead of a live `track_for_id` per id. `data_source="musicbrainz"`
    because a chroma candidate IS a MusicBrainz recording — so `_ensure_full_match`
    re-hydrates the winner through the MB plugin exactly as before.
    """
    from beets.autotag.hooks import TrackInfo

    def item_candidates(item, artist, title):
        import beetsplug.chroma as chroma

        if item.path not in chroma._matches or plugin.mb is None:
            return
        recording_ids, _ = chroma._matches[item.path]
        meta = _chroma_recording_meta.get(item.path, {})
        for recording_id in chroma.prefix(recording_ids, chroma.MAX_RECORDINGS):
            m = meta.get(recording_id, {})
            yield TrackInfo(
                track_id=recording_id,
                title=m.get("title"),
                artist=m.get("artist"),
                length=m.get("length"),
                data_source="musicbrainz",
                cm_thin=True,
            )

    return item_candidates


def install_thin_chroma() -> bool:
    """Patch chroma to capture AcoustID metadata and yield thin candidates (Step 3).

    Patches the module-level `acoustid_match` (looked up as a global by `fingerprint_task`
    at call time, so the swap takes) and the loaded plugin instance's `item_candidates`.
    Idempotent. A missing chroma plugin is logged, not raised.
    """
    from beets import metadata_plugins
    import beetsplug.chroma as chroma

    # Preserve the stock function once, so the drift guard can still hash it after the
    # swap and a double-install never saves the fork over the original.
    if getattr(chroma, "_cm_original_acoustid_match", None) is None:
        chroma._cm_original_acoustid_match = chroma.acoustid_match
    chroma.acoustid_match = _acoustid_match_with_meta

    plugin = metadata_plugins.get_metadata_source("acoustid")
    if plugin is None:
        logger.error("acoustid (chroma) source not loaded — thin chroma not installed")
        return False
    plugin.item_candidates = _thin_chroma_item_candidates(plugin)
    logger.debug("T-208: thin chroma candidates installed")
    return True
