"""T-201 tests — SourceSignals mapping from a yt-dlp `info` dict (sense 1, spec §2).

Pure and offline: `SourceSignals.from_info` takes a captured `info` dict and returns the
sense-1 blob. These lock the four resolution paths for the voting pair
(`yt_artist`/`yt_title`), the judgment-only carriage of `yt_album`/`yt_release_year`, and
the "every field always present" invariant.
"""

from dataclasses import fields

from app.source_signals import SourceSignals


# A captured "- Topic" upload: YouTube attached clean structured music fields. This is
# the case the spec says to PREFER over splitting the raw title.
_TOPIC_INFO = {
    "id": "abc123",
    "title": "Frontline (Official Audio)",
    "uploader": "Pa Salieu - Topic",
    "channel": "Pa Salieu - Topic",
    "description": "Provided to YouTube by a distributor\n\nFrontline · Pa Salieu\n" + "x" * 2000,
    "tags": ["UK rap", "afroswing"],
    "duration": 180.0,
    "artist": "Pa Salieu",
    "track": "Frontline",
    "album": "Send Them to Coventry",
    "release_year": 2021,
}


def test_structured_music_fields_are_used_directly():
    """`info["artist"]`/`["track"]` present → the voting pair comes straight from them,
    not from splitting the raw promotional title."""
    sig = SourceSignals.from_info(_TOPIC_INFO)
    assert sig.yt_artist == "Pa Salieu"
    assert sig.yt_title == "Frontline"
    # These beat the title split even though the raw title carries promo cruft.
    assert sig.title == "Frontline (Official Audio)"


def test_channel_is_topic_detected_from_topic_uploader():
    sig = SourceSignals.from_info(_TOPIC_INFO)
    assert sig.channel_is_topic is True


def test_title_parse_fallback_when_no_structured_fields():
    """No `artist`/`track` → parse `"Artist - Title"` out of the raw title (T-006 split)."""
    info = {"id": "v", "title": "Fleetwood Mac - Dreams", "uploader": "SomeVEVO"}
    sig = SourceSignals.from_info(info)
    assert sig.yt_artist == "Fleetwood Mac"
    assert sig.yt_title == "Dreams"
    assert sig.channel_is_topic is False


def test_topic_uploader_fallback_when_title_has_no_dash():
    """No structured field and a title with no `Artist -` split → recover the artist from
    the `"Artist - Topic"` uploader; the title stays the raw title."""
    info = {"id": "v", "title": "Dreams", "uploader": "Fleetwood Mac - Topic"}
    sig = SourceSignals.from_info(info)
    assert sig.yt_artist == "Fleetwood Mac"
    assert sig.yt_title == "Dreams"
    assert sig.channel_is_topic is True


def test_bare_title_yields_no_artist():
    """A plain title, a non-Topic uploader, no structured fields → `yt_artist=None`
    (T-205 then treats `yt` as supporting no candidate → conservative park); `yt_title`
    still falls back to the raw title, never None."""
    info = {"id": "v", "title": "Dreams", "uploader": "Some Fan Channel"}
    sig = SourceSignals.from_info(info)
    assert sig.yt_artist is None
    assert sig.yt_title == "Dreams"


def test_yt_album_and_release_year_are_carried_but_judgment_only():
    """`yt_album`/`yt_release_year` ride in the blob for the AI to read but are
    JUDGMENT-ONLY (spec §2/§5): never a written fact, never in T-205's 2-of-3 vote.
    This asserts only that they are *carried* — the "not voted / not written" half is
    enforced by T-205 (the vote uses `yt_artist`/`yt_title` alone) and by the writers
    (facts come from MusicBrainz/ISRC)."""
    sig = SourceSignals.from_info(_TOPIC_INFO)
    assert sig.yt_album == "Send Them to Coventry"
    assert sig.yt_release_year == 2021


def test_description_head_is_bounded():
    """The description is carried as a bounded prefix, not the whole blob."""
    sig = SourceSignals.from_info(_TOPIC_INFO)
    assert len(sig.description_head) <= 500
    assert sig.description_head.startswith("Provided to YouTube")


def test_every_field_present_on_a_sparse_info():
    """Every field is populated (empty/`None`/`[]` where yt-dlp was silent) — a consumer
    never hits a missing key, whatever was in `info`."""
    sig = SourceSignals.from_info({})
    # No field is absent; all are set to a documented default.
    for f in fields(SourceSignals):
        assert hasattr(sig, f.name)
    assert sig.title == ""
    assert sig.uploader == ""
    assert sig.channel_is_topic is False
    assert sig.description_head == ""
    assert sig.tags == []
    assert sig.duration is None
    assert sig.video_id == ""
    assert sig.yt_artist is None
    assert sig.yt_title == ""  # raw title fallback of an empty title
    assert sig.yt_album is None
    assert sig.yt_release_year is None


def test_structured_artist_wins_over_a_dashed_title():
    """When both a structured `artist` and a dash-splittable title exist, the structured
    field wins (it is cleaner than the split)."""
    info = {
        "id": "v",
        "title": "DJ Tag - Real Song Name",
        "artist": "The Actual Artist",
        "track": "Real Song Name",
    }
    sig = SourceSignals.from_info(info)
    assert sig.yt_artist == "The Actual Artist"
    assert sig.yt_title == "Real Song Name"


def test_non_topic_channel_with_topic_uploader_still_topic():
    """`channel_is_topic` is True if EITHER uploader or channel is a Topic channel."""
    info = {"id": "v", "title": "X", "uploader": "Artist - Topic", "channel": "Artist"}
    assert SourceSignals.from_info(info).channel_is_topic is True
