"""Unit tests for `shazam_runner.py`'s parse helpers (T-221).

The runner runs *inside* the isolated 3.12 venv in production, but the module
imports only stdlib at top level (`shazamio` is imported lazily inside
`_recognize`), so its pure `track`-dict → record-field extraction is importable
and testable here with the app interpreter — no venv, no network.

These cover the T-221 widening: album/year/genre pulled from the `recognize`
`track` dict (the SONG section's metadata rows + `genres.primary`) that the
record now carries as the T-220 tag payload.

Run from `server/`: `./.venv/bin/pytest tests/test_shazam_runner.py -v`
"""

from app import shazam_runner


# A realistic `recognize().track` shape (shazamio 0.8.x): album + release date
# live only as `{title, text}` rows in the SONG section's `metadata`; genre is
# `genres.primary`; lyrics are their own section.
_TRACK = {
    "title": "Frontline",
    "subtitle": "Pa Salieu",
    "isrc": "GBKPL2000123",
    "genres": {"primary": "Hip-Hop/Rap"},
    "images": {"coverart": "http://c", "coverarthq": "http://hq"},
    "sections": [
        {
            "type": "SONG",
            "metadata": [
                {"title": "Album", "text": "Send Them to Coventry"},
                {"title": "Label", "text": "Warner"},
                {"title": "Released", "text": "2020"},
            ],
        },
        {"type": "LYRICS", "text": ["line one", "line two"]},
    ],
}


# --- The widened fields extract from a populated track --------------------------

def test_album_from_song_metadata():
    assert shazam_runner._labelled(_TRACK, "Album") == "Send Them to Coventry"


def test_year_from_released_metadata():
    assert shazam_runner._year(_TRACK) == 2020


def test_year_extracts_from_a_full_date_string():
    """Shazam can title 'Released' as a full date — the year field takes the year."""
    track = {"sections": [{"type": "SONG", "metadata": [
        {"title": "Released", "text": "September 25, 2020"},
    ]}]}
    assert shazam_runner._year(track) == 2020


def test_year_is_none_when_no_four_digit_run():
    track = {"sections": [{"type": "SONG", "metadata": [
        {"title": "Released", "text": "unknown"},
    ]}]}
    assert shazam_runner._year(track) is None


def test_genre_from_genres_primary():
    assert shazam_runner._genre(_TRACK) == "Hip-Hop/Rap"


def test_labelled_is_case_insensitive():
    assert shazam_runner._labelled(_TRACK, "album") == "Send Them to Coventry"


def test_existing_fields_still_extract():
    assert shazam_runner._art_url(_TRACK) == "http://hq"
    assert shazam_runner._lyrics(_TRACK) == "line one\nline two"


# --- A field the track omits is None, never a crash (fail-soft) -----------------

def test_missing_album_is_none():
    track = {"sections": [{"type": "SONG", "metadata": [{"title": "Label", "text": "X"}]}]}
    assert shazam_runner._labelled(track, "Album") is None


def test_missing_genre_is_none():
    assert shazam_runner._genre({}) is None
    assert shazam_runner._genre({"genres": {}}) is None


def test_empty_track_yields_all_none():
    assert shazam_runner._labelled({}, "Album") is None
    assert shazam_runner._year({}) is None
    assert shazam_runner._genre({}) is None


def test_metadata_only_read_from_song_sections():
    """A stray metadata row under a non-SONG section is not mistaken for album."""
    track = {"sections": [{"type": "LYRICS", "metadata": [{"title": "Album", "text": "wrong"}]}]}
    assert shazam_runner._labelled(track, "Album") is None


# --- The empty record already carries the full widened shape --------------------

def test_empty_record_has_the_widened_keys():
    rec = shazam_runner._empty_record()
    assert rec["album"] is None
    assert rec["year"] is None
    assert rec["genre"] is None
    assert rec["matched"] is False
