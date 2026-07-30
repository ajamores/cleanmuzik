"""Re-search MusicBrainz in the owner's own words (T-103, ADR-020 exit 1).

The park-time gate searches with what the *machine* read off a YouTube rip. When that
was wrong, the candidate list is wrong, and no amount of picking from it helps — the
owner has to be able to change the question. That is all this module does: take an
artist and a title the owner typed, ask MusicBrainz, and hand back candidate rows in
the same shape the queue already renders (`events.candidate_row`).

**Stateless by design.** It writes nothing: the review row's stored `candidate_ids` are
left exactly as parked. The chosen recording travels back through the existing
`POST /reviews/{id}/resolve`, which is why ADR-020's first binding consequence was to
relax `_validate_weak_match` — a re-searched recording is by definition *not* in the
row's candidate list. Persisting the new candidates instead would mean a second write
path, a second staleness question (ADR-006 stores ids precisely to avoid caching
candidate objects), and no gain: the owner is looking at the results when they choose.

## Three findings that make the scoring work, each paid for on a real fixture

1. **`incl_artist=True` is load-bearing, not a tuning preference.** beets' default
   omits the artist from a singleton's distance. Measured on the Frank Ocean fixture,
   that scores *Strawberry Swing* by Coldplay and by Frank Ocean at an identical
   **0.571** — the two recordings are indistinguishable, which is exactly the dead-end
   this ticket exists to fix (it is a cover, so the title genuinely collides). With the
   artist included: Frank Ocean 0.667, Coldplay 0.467. The owner just told us the
   artist; ignoring it throws away the only thing they corrected.

2. **Duration must be read off the file, or left out entirely.** A *real* length
   sharpens the ranking hard — Frank Ocean 0.667 → 0.889, and it is the only thing that
   separates five different recordings all called "Nines — Outro" (they tie at 0.667
   without it, one reaches 0.889 with it). But a *guessed* length actively corrupts the
   result: an invented 193s lifted three wrong candidates above the right one, because
   their true durations happened to sit nearer the invention. So the length comes from
   the staging file or not at all — never from a default.

3. **beets' `search_limit` default of 5 is too small here.** The Nines fixture's
   known-correct recording (`f5d1bcfb…`) sits at the boundary of a five-result window
   and drifts in and out of it between identical calls, because MusicBrainz relevance
   ordering is not stable. At 25 it is reliably present. The limit is passed
   **explicitly** rather than by setting `config["musicbrainz"]["search_limit"]`: that
   config is read by the acquire path too, so raising it in place would quietly widen
   every future park's candidate list from a search route running on another thread.

4. **The rows are built from the search response itself — `tracks_for_ids` is NOT
   called, and that is the difference between a 1-second feature and a 27-second one.**
   The obvious implementation (and the one this module shipped first) hydrates each
   result by id, the way `item_candidates` does. Measured, that costs **27 s per
   search, every time**: beets' MusicBrainz plugin does not override `tracks_for_ids`,
   so it falls through to one `GET /ws/2/recording/{id}` per result through a shared
   **1.0 req/s** limiter — 26 serialised round-trips at a measured 1.04 s each. There
   is no cache to warm; three identical searches cost 26.8 / 28.9 / 27.7 s. Worse, that
   limiter is the *same* token bucket the acquire pipeline uses, so a re-search starved
   a running import of MusicBrainz for the whole 27 s.
   The 25 lookups were also **pure waste**: they fetch aliases, ISRCs and work/artist
   relations, while everything downstream reads only `track_id`, `title`, `artist` and
   `length` — and the single search response already carries all four (`length` on
   ~19 of 25; see `_track_info`). One request, ~1 s, same fields.

## An empty result is an answer, not a failure

ADR-020's second consequence: no dead panel. A search that finds nothing returns `[]`
and the caller offers *search again* and *keep-untagged*. Real cause, not an error —
bootlegs, mixtape rips and YouTube-only mixes genuinely aren't in the database.

Beets-heavy at module scope, so it is imported *inside* the route that needs it — the
same lazy-engine discipline as `import_seam` (T-001).
"""

import logging

from app.events import candidate_row

logger = logging.getLogger("cleanmuzik")

# How many MusicBrainz results to consider. Above beets' default of 5 for the reason in
# finding 3; raising it is nearly free because the results ride the ONE search response
# (finding 4) rather than costing a rate-limited lookup each. Still bounded — this is a
# list a human reads, and relevance is worthless past the first screenful.
SEARCH_LIMIT = 25

# What the owner types, bounded. Not a security boundary (single-user localhost,
# ADR-004) — it stops a pasted wall of text becoming a MusicBrainz query that can only
# fail slowly.
_TERM_MAX = 200


class SearchTermsError(Exception):
    """The owner's search terms can't be turned into a query → 400.

    Distinct from "found nothing": that is a legitimate empty result (see the module
    docstring), whereas this means there was no question to ask in the first place.
    """


def clean_terms(artist, title) -> tuple[str, str]:
    """Bound and normalize the typed artist/title, or raise `SearchTermsError`.

    Either field may be empty — a title-only search is a real gesture (the owner knows
    the song but not how MusicBrainz credits it) and so is an artist-only one. Both
    empty is not: beets would send a filter-less query and MusicBrainz answers that with
    an HTTP 400, two network round-trips after the mistake was made.
    """
    artist, title = _clean_term("artist", artist), _clean_term("title", title)
    if not (artist or title):
        raise SearchTermsError("Give an artist, a title, or both to search for.")
    return artist, title


def _clean_term(name: str, raw) -> str:
    """One typed field, trimmed and bounded. Absent → `""`, which is a legal half-query."""
    if raw is None:
        return ""
    if not isinstance(raw, str):
        raise SearchTermsError(f"'{name}' must be a string.")
    term = raw.strip()
    if len(term) > _TERM_MAX:
        raise SearchTermsError(
            f"'{name}' must be at most {_TERM_MAX} characters (got {len(term)})."
        )
    return term


def _staging_length(staging_path) -> float | None:
    """The staging file's real duration in seconds, or None if it can't be read.

    None rather than 0.0 or a default, deliberately — finding 2 in the module docstring:
    a wrong length is worse than no length. A missing or unreadable file is a normal
    state here (T-106: the audio can be gone while the row survives), so this never
    raises; the search still works, just with title/artist as the only discriminators.
    """
    if not staging_path:
        return None
    try:
        from mediafile import MediaFile

        length = MediaFile(str(staging_path)).length
    except Exception as exc:  # noqa: BLE001 — an unreadable file just costs precision
        logger.warning("could not read length of %s (%s)", staging_path, exc)
        return None
    return float(length) if length else None


def _track_info(row: dict):
    """One MusicBrainz search-response row → the `TrackInfo` fields scoring reads.

    Deliberately built from the search response instead of a per-id lookup (finding 4).
    `track_distance` reads only `length`, `title`, `artist`, `index`, `track_id`,
    `medium` and `data_source`; `index`/`medium` are `None` on a recording lookup too,
    so nothing is lost by not asking.

    `length` is **absent on roughly a quarter of rows** and stays `None` there rather
    than becoming 0.0 — finding 2's rule applies to a missing value exactly as it does
    to a guessed one. The honest consequence: those rows skip the duration penalty and
    can rank slightly high. That is accepted, not overlooked — an imperfectly ordered
    list the owner can re-search in a second beats a perfectly ordered one that takes
    half a minute, and the acceptance bar in ADR-020 is that the right recording is
    *present*, not that it ranks first.
    """
    from beets.autotag.hooks import TrackInfo

    length = row.get("length")
    return TrackInfo(
        track_id=row.get("id"),
        title=row.get("title"),
        artist=_artist_credit(row),
        # MusicBrainz reports milliseconds; beets scores in seconds.
        length=(length / 1000.0) if length else None,
        data_source="musicbrainz",
    )


def _artist_credit(row: dict) -> str | None:
    """The row's artist as one display string, joining a multi-credit properly.

    A credit is a list of `{name, artist, joinphrase}` parts — "Nines feat. J. Stone"
    arrives as two parts with a joinphrase between them. Concatenating names alone would
    produce "NinesJ. Stone" and score worse than the single-artist rows it competes with.

    The key is `artist_credit`, **underscored**: beets' client normalizes MusicBrainz's
    own hyphenated `artist-credit` on the way through. Reading the hyphenated name off
    the raw API docs silently yields `None` for every row — which still *ranks* roughly
    right on title and duration, so it fails as "every result says Unknown artist" and a
    dead `incl_artist=True`, not as an error.
    """
    parts = row.get("artist_credit") or []
    if not isinstance(parts, list):
        return None
    out = []
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


def search_recordings(
    artist: str,
    title: str,
    *,
    staging_path=None,
) -> list[dict]:
    """MusicBrainz recordings matching `artist`/`title`, best-scoring first.

    Rows are `events.candidate_row` shaped — the same three fields the queue already
    renders, so the UI needs no second code path for "new results" (and ADR-010 still
    applies: a recording is not a release, so no album/year/art).

    `staging_path` is the parked audio, read only for its duration. Never raises for a
    MusicBrainz failure: an empty list is the caller's cue to offer *search again*.
    """
    from beets import metadata_plugins
    from beets.autotag import track_distance
    from beets.library import Item
    from beets.metadata_plugins import SearchParams

    from app.beets_engine import configure_beets

    # Same contract as `resolve_import` / `import_song`: the entry point configures the
    # engine rather than trusting a caller to have done it. Without this the plugin
    # lookup below finds nothing (ADR-007: the library API never auto-loads plugins) and
    # every search would quietly return zero results. Idempotent and lock-guarded.
    configure_beets()

    plugin = metadata_plugins.get_metadata_source("musicbrainz")
    if plugin is None:  # configure_beets loads it (ADR-007); a miss is a misconfig
        logger.error("musicbrainz metadata source is not loaded — cannot re-search")
        return []

    # The item is a scoring yardstick, not something we import: it carries the owner's
    # corrected terms so `track_distance` measures each result against what they typed.
    # `length` is set only when the file gave us a real one (finding 2).
    item = Item(artist=artist, title=title)
    if (length := _staging_length(staging_path)) is not None:
        item.length = length

    try:
        query, filters = plugin.get_search_query_with_filters(
            "track", [item], artist, title, False
        )
        # Explicit limit — NOT via global config, see finding 3. ONE request: the rows
        # carry every field scoring needs, so no per-id hydration follows (finding 4).
        responses = plugin.get_search_response(
            SearchParams("track", query, filters, SEARCH_LIMIT)
        )
    except Exception as exc:  # noqa: BLE001 — MusicBrainz down/rate-limited is not a 500
        logger.warning("re-search for %r / %r failed (%s)", artist, title, exc)
        return []

    # De-duplicate by recording id: MusicBrainz can return the same recording twice
    # across a paged relevance set, and two identical rows in the list read as a UI bug.
    seen: set = set()
    infos = []
    for row in responses:
        rid = row.get("id")
        if not rid or rid in seen:
            continue
        seen.add(rid)
        infos.append(_track_info(row))

    scored = [
        (1.0 - float(track_distance(item, info, incl_artist=True)), info)
        for info in infos
    ]
    # Best first: MusicBrainz returns its own relevance order, which put Coldplay's
    # *Strawberry Swing* above Frank Ocean's. beets' distance — with the artist counted
    # — puts the answer the owner asked for at the top.
    scored.sort(key=lambda pair: -pair[0])
    logger.info(
        "re-search %r / %r → %d candidates", artist, title, len(scored)
    )
    return [
        candidate_row(
            getattr(info, "track_id", None),
            title=getattr(info, "title", None),
            artist=getattr(info, "artist", None),
            score=score,
        )
        for score, info in scored
    ]
