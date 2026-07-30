"""Re-search: the MusicBrainz query behind ADR-020's exit 1 (T-103).

Offline by construction. Every test here fakes the beets metadata source, because the
things worth pinning are not "does MusicBrainz work" but the four decisions that make
the ranking correct — the artist counts, a real duration counts, an invented one never
does, and the result limit never leaks into global beets config.

The live proof that the right recording actually comes back for the corrected terms is
`/verify` against the parked Frank Ocean fixture, not a unit test.
"""

import pytest

import app.beets_engine as beets_engine
from app.mb_search import SEARCH_LIMIT, SearchTermsError, clean_terms, search_recordings


def _global_search_limit():
    """beets' global `musicbrainz.search_limit`, or None when no plugin has set it.

    Read through a sentinel rather than asserted absent: whether the key exists depends
    on whether some *other* test in the run loaded the real plugins, and the invariant
    being tested is that a re-search leaves it **unchanged** either way.
    """
    from beets import config

    try:
        return config["musicbrainz"]["search_limit"].get(int)
    except Exception:  # noqa: BLE001 — confuse raises NotFoundError when unset
        return None


def _row(track_id, artist, title, length_ms=None):
    """One MusicBrainz SEARCH-RESPONSE row, in beets' normalized shape.

    Note `artist_credit` is **underscored** — beets rewrites MusicBrainz's own
    hyphenated `artist-credit`. Building these fakes off the raw API docs is exactly how
    the artist silently came back None on every row while the ranking still looked
    plausible, so the shape here is copied from a real captured response.
    """
    row = {"id": track_id, "title": title}
    if artist is not None:
        row["artist_credit"] = [{"name": artist, "artist": {"name": artist}}]
    if length_ms is not None:
        row["length"] = length_ms
    return row


class _FakePlugin:
    """A metadata source that answers from fixed search rows and records how it was asked."""

    def __init__(self, rows, *, raises=None):
        self.rows = rows
        self.raises = raises
        self.params = None

    def get_search_query_with_filters(self, query_type, items, artist, name, va_likely):
        return "", {"artist": artist, "recording": name}

    def get_search_response(self, params):
        if self.raises:
            raise self.raises
        self.params = params
        return self.rows


@pytest.fixture
def offline(monkeypatch):
    """Neutralize engine setup and hand out a settable fake source + distance spy."""
    monkeypatch.setattr(beets_engine, "configure_beets", lambda *a, **k: None)

    state = {"plugin": None, "distance_calls": []}

    import beets.autotag as autotag
    import beets.metadata_plugins as mp

    monkeypatch.setattr(mp, "get_metadata_source", lambda _src: state["plugin"])

    def _distance(item, info, incl_artist=False):
        state["distance_calls"].append((item, info, incl_artist))
        # Stand in for beets: a perfect artist+title agreement is distance 0.
        matched = (item.artist or "").lower() == (info.artist or "").lower()
        return 0.1 if matched else 0.6

    monkeypatch.setattr(autotag, "track_distance", _distance)
    return state


# --- the terms the owner typed ----------------------------------------------


def test_either_field_alone_is_a_real_search():
    # Title-only ("I know the song, not how MB credits it") and artist-only are both
    # gestures the owner actually makes; neither is a client bug.
    assert clean_terms("", "Outro") == ("", "Outro")
    assert clean_terms("Nines", None) == ("Nines", "")


def test_both_fields_empty_is_refused_before_the_network():
    # beets would send a filter-less query and MusicBrainz answers that with a 400 —
    # two round-trips after the mistake was already knowable.
    with pytest.raises(SearchTermsError, match="artist, a title, or both"):
        clean_terms("   ", "")


def test_terms_are_trimmed_and_bounded():
    assert clean_terms("  Nines  ", "  Outro  ") == ("Nines", "Outro")
    with pytest.raises(SearchTermsError, match="at most"):
        clean_terms("N" * 201, "Outro")
    with pytest.raises(SearchTermsError, match="must be a string"):
        clean_terms(7, "Outro")


# --- the ranking ------------------------------------------------------------


def test_the_artist_is_counted_or_a_cover_is_unrankable(offline):
    # THE load-bearing assertion of this module. Measured live: with beets' default
    # incl_artist=False, *Strawberry Swing* by Coldplay and by Frank Ocean score an
    # identical 0.571 — the exact tie that makes the fixture unresolvable. The owner
    # just corrected the artist; the distance must read it.
    offline["plugin"] = _FakePlugin([
        _row("abfe9dab-0067-4484-8c83-34b5c4a74b22", "Coldplay", "Strawberry Swing"),
        _row("908e389b-256c-4f6a-9d75-0e0a81815444", "Frank Ocean", "Strawberry Swing"),
    ])
    rows = search_recordings("Frank Ocean", "Strawberry Swing")
    assert all(incl is True for _, _, incl in offline["distance_calls"]), (
        "track_distance must be called with incl_artist=True"
    )
    # Best first — MusicBrainz's own relevance order put Coldplay above Frank Ocean.
    assert rows[0]["candidate_id"] == "908e389b-256c-4f6a-9d75-0e0a81815444"
    assert rows[0]["score"] > rows[1]["score"]


def test_a_real_duration_reaches_the_scoring_item(offline, monkeypatch, tmp_path):
    # Five recordings called "Nines — Outro" tie at an identical score without a
    # duration; the file's real length is the only thing that separates them (one
    # reaches 0.889). So it has to arrive on the item beets measures against.
    import app.mb_search as mb_search

    offline["plugin"] = _FakePlugin([_row("f5d1bcfb-0000-4000-8000-000000000000", "Nines", "Outro")])
    monkeypatch.setattr(mb_search, "_staging_length", lambda _p: 190.056)
    search_recordings("Nines", "Outro", staging_path=str(tmp_path / "song.mp3"))
    item = offline["distance_calls"][0][0]
    assert item.length == pytest.approx(190.056)


def test_an_unreadable_staging_file_yields_no_length_rather_than_zero(tmp_path):
    # `_staging_length` on its own: a missing file is a normal state (T-106), and the
    # answer must be None — the caller treats 0.0 and None differently.
    from app.mb_search import _staging_length

    assert _staging_length(tmp_path / "gone.mp3") is None
    assert _staging_length(None) is None
    junk = tmp_path / "junk.mp3"
    junk.write_bytes(b"not an mp3 at all")
    assert _staging_length(junk) is None


def test_no_readable_duration_means_no_duration_not_a_default(offline, tmp_path):
    # A guessed length is worse than none: an invented 193s measurably lifted three
    # wrong candidates above the right one. So an unreadable file must leave `length`
    # unset rather than fall back to 0.0 or a placeholder.
    offline["plugin"] = _FakePlugin([_row("908e389b-256c-4f6a-9d75-0e0a81815444", "Frank Ocean", "Strawberry Swing")])
    search_recordings("Frank Ocean", "Strawberry Swing", staging_path=str(tmp_path / "gone.mp3"))
    item = offline["distance_calls"][0][0]
    assert not item.length, "an unreadable file must not contribute a fabricated length"


def test_the_result_limit_is_passed_explicitly_never_via_global_config(offline):
    # The hazard this guards: `config["musicbrainz"]["search_limit"]` is global and the
    # acquire path reads it, so raising it in place would quietly widen every future
    # park's candidate list from a search running on another thread.
    offline["plugin"] = plugin = _FakePlugin([_row("908e389b-0000-4000-8000-000000000000", "A", "B")])
    before = _global_search_limit()
    search_recordings("A", "B")
    assert plugin.params.limit == SEARCH_LIMIT
    # beets' default is 5, which measurably loses the Nines fixture's correct recording:
    # it sits at the boundary of a five-result window and drifts out of it between
    # identical calls, because MusicBrainz relevance ordering isn't stable.
    assert SEARCH_LIMIT > 5, "the explicit limit exists to exceed beets' default of 5"
    assert _global_search_limit() == before, (
        "the acquire path's candidate width must be untouched by a re-search"
    )


def test_rows_without_an_id_are_dropped_and_repeats_collapse(offline):
    # An id is the only field a resolve can act on, so a row without one is unusable and
    # must not render as a pickable candidate. MusicBrainz can also repeat a recording
    # across a paged relevance set, and two identical rows read as a UI bug.
    good = "908e389b-0000-4000-8000-000000000000"
    offline["plugin"] = _FakePlugin([
        _row(good, "A", "B"),
        _row(None, "A", "B"),
        _row(good, "A", "B"),  # the same recording again
    ])
    assert [r["candidate_id"] for r in search_recordings("A", "B")] == [good]


def test_a_multi_artist_credit_joins_with_its_joinphrase(offline):
    # "Nines feat. J. Stone" arrives as two parts with a joinphrase between them.
    # Concatenating the names alone gives "NinesJ. Stone", which scores worse than the
    # single-artist rows it competes against.
    offline["plugin"] = _FakePlugin([{
        "id": "908e389b-0000-4000-8000-000000000000",
        "title": "All Get Right",
        "artist_credit": [
            {"name": "Nines", "artist": {"name": "Nines"}, "joinphrase": " feat. "},
            {"name": "J. Stone", "artist": {"name": "J. Stone"}},
        ],
    }])
    assert search_recordings("Nines", "All Get Right")[0]["artist"] == "Nines feat. J. Stone"


def test_a_row_length_is_milliseconds_and_a_missing_one_stays_none():
    # MusicBrainz reports milliseconds; beets scores in seconds. Getting this wrong makes
    # every duration comparison absurd rather than merely slightly off. And a row with no
    # length keeps None — finding 2's rule covers a MISSING value as well as a guessed
    # one, and roughly a quarter of real search rows have no length.
    from app.mb_search import _track_info

    assert _track_info(_row("x", "A", "B", length_ms=235000)).length == 235.0
    assert _track_info(_row("x", "A", "B")).length is None


def test_the_search_response_is_the_only_request_made(offline):
    # The 27s-to-1s fix, pinned. Hydrating each result by id costs one rate-limited
    # round-trip per row (beets' MusicBrainz plugin does not batch `tracks_for_ids`),
    # which measured 27 seconds per search and starved the import pipeline's shared
    # MusicBrainz budget for the duration. If a future edit reaches for per-id lookup
    # again, this fails: the fake plugin does not even offer the hook.
    offline["plugin"] = plugin = _FakePlugin([_row("908e389b-0000-4000-8000-000000000000", "A", "B")])
    assert not hasattr(plugin, "tracks_for_ids")
    assert len(search_recordings("A", "B")) == 1


def test_musicbrainz_being_down_is_an_empty_result_not_a_crash(offline):
    # ADR-020 consequence 2: never a dead panel. The caller renders "search again" and
    # "keep-untagged" off an empty list, so a network failure must not raise past here.
    offline["plugin"] = _FakePlugin([], raises=RuntimeError("musicbrainz unreachable"))
    assert search_recordings("Nines", "Outro") == []


def test_a_missing_metadata_source_is_an_empty_result(offline):
    offline["plugin"] = None
    assert search_recordings("Nines", "Outro") == []


def test_rows_are_candidate_row_shaped_so_the_ui_needs_no_second_path(offline):
    offline["plugin"] = _FakePlugin([_row("908e389b-0000-4000-8000-000000000000", "Frank Ocean", "Strawberry Swing")])
    row = search_recordings("Frank Ocean", "Strawberry Swing")[0]
    # The same key set the parked queue already renders (ADR-010: no album/year/art).
    assert set(row) == {"candidate_id", "title", "artist", "score"}
