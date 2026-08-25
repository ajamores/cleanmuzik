"""T-208 tests — thin MusicBrainz/chroma candidates, offline.

Three things the fan-out collapse rests on, none of which touch the network:

1. A thin candidate's scored fields (`title`/`artist`/`length`) match what full
   hydration would produce — built with the plugin's own helpers, with a guarded
   fallback for the lighter fields a search row can omit.
2. The forked `acoustid_match` stays byte-faithful to stock beets (drift guard): a
   beets upgrade that changes it must trip this test, not silently diverge.
3. Both patched `item_candidates` yield `cm_thin`-marked rows and make zero per-id
   lookups.
"""

import hashlib
import inspect
from types import SimpleNamespace

import pytest

import app.mb_thin as mt
from app.beets_engine import configure_beets


@pytest.fixture(scope="module")
def mb_plugin():
    from beets import metadata_plugins

    configure_beets()
    plugin = metadata_plugins.get_metadata_source("musicbrainz")
    assert plugin is not None
    return plugin


# --- parity: a thin row scores like a full one -------------------------------


def test_thin_track_info_carries_scored_fields_and_marker(mb_plugin):
    row = {
        "id": "rec-1",
        "title": "Frontline",
        "length": 190000,  # ms → 190.0 s
        "artist_credit": [
            {
                "name": "Pa Salieu",
                "joinphrase": "",
                "artist": {
                    "id": "a1",
                    "name": "Pa Salieu",
                    "sort_name": "Pa Salieu",
                    "aliases": [],
                },
            }
        ],
    }
    info = mt.thin_track_info(mb_plugin, row)

    assert info.track_id == "rec-1"
    assert info.title == "Frontline"
    assert info.artist == "Pa Salieu"
    assert info.length == 190.0
    assert info.data_source == "musicbrainz"
    assert getattr(info, "cm_thin", False) is True


def test_thin_track_info_falls_back_when_credit_is_light(mb_plugin):
    # A search row whose artist_credit lacks sort_name/id: _parse_artist_credits raises,
    # and the hand join preserves the feat. structure rather than collapsing it.
    row = {
        "id": "rec-2",
        "title": "Nines",
        "length": None,
        "artist_credit": [
            {"name": "Nines", "joinphrase": " feat. "},
            {"name": "J. Stone", "joinphrase": ""},
        ],
    }
    info = mt.thin_track_info(mb_plugin, row)

    assert info.artist == "Nines feat. J. Stone"
    assert info.length is None  # a missing length stays None, never 0.0


def test_thin_track_info_needs_an_id(mb_plugin):
    assert mt.thin_track_info(mb_plugin, {"title": "x"}) is None


def test_acoustid_artist_joins_name_and_joinphrase():
    rec = {"artists": [{"name": "A", "joinphrase": " & "}, {"name": "B"}]}
    assert mt._acoustid_artist(rec) == "A & B"


# --- the MB item_candidates patch: thin, de-duped, no per-id lookup ----------


def test_thin_mb_item_candidates_are_thin_and_deduped(mb_plugin, monkeypatch):
    rows = [
        {"id": "r1", "title": "T1", "artist_credit": []},
        {"id": "r1", "title": "T1", "artist_credit": []},  # duped in the response
        {"id": "r2", "title": "T2", "artist_credit": []},
    ]
    monkeypatch.setattr(mb_plugin, "_get_candidates", lambda *a, **k: rows)
    # tracks_for_ids/track_for_id must never be reached on this path.
    monkeypatch.setattr(
        mb_plugin,
        "track_for_id",
        lambda *a, **k: pytest.fail("thin path must not hydrate by id"),
    )
    item = SimpleNamespace(path=b"/x.mp3")

    out = list(mt._thin_mb_item_candidates(mb_plugin)(item, "artist", "title"))

    assert [i.track_id for i in out] == ["r1", "r2"]  # de-duped by id
    assert all(getattr(i, "cm_thin", False) for i in out)


# --- the chroma patch: thin candidates from the captured side table ----------


def test_thin_chroma_candidates_from_side_table(monkeypatch):
    import beetsplug.chroma as chroma

    path = b"/staging/song.mp3"
    monkeypatch.setitem(chroma._matches, path, (["rec-A", "rec-B"], []))
    monkeypatch.setitem(
        mt._chroma_recording_meta,
        path,
        {
            "rec-A": {"title": "A", "artist": "Artist A", "length": 200.0},
            "rec-B": {"title": "B", "artist": "Artist B", "length": None},
        },
    )
    # A plugin whose `mb` is present (the stock guard) but whose track_for_id would fail
    # loudly if the thin path ever called it.
    plugin = SimpleNamespace(
        mb=object(),
        track_for_id=lambda *a, **k: pytest.fail("chroma thin path must not hydrate"),
    )
    item = SimpleNamespace(path=path)

    out = list(mt._thin_chroma_item_candidates(plugin)(item, "artist", "title"))

    assert [i.track_id for i in out] == ["rec-A", "rec-B"]
    assert [i.title for i in out] == ["A", "B"]
    assert out[0].length == 200.0 and out[1].length is None
    assert all(getattr(i, "cm_thin", False) for i in out)
    assert all(i.data_source == "musicbrainz" for i in out)


# --- drift guard: the fork mirrors stock beets -------------------------------


def test_forked_acoustid_match_mirrors_stock_beets():
    """If a beets upgrade changes chroma.acoustid_match, review the fork against it.

    `install_thin_chroma` stashes the stock function before swapping, so this holds
    whether or not the patch has been installed this session.
    """
    import beetsplug.chroma as chroma
    from app.mb_thin import install_thin_chroma

    install_thin_chroma()
    stock = getattr(chroma, "_cm_original_acoustid_match", chroma.acoustid_match)
    digest = hashlib.sha256(inspect.getsource(stock).encode()).hexdigest()

    assert digest == mt.STOCK_ACOUSTID_MATCH_SHA256, (
        "beets chroma.acoustid_match changed upstream — re-review "
        "app.mb_thin._acoustid_match_with_meta against the new source, then update "
        "STOCK_ACOUSTID_MATCH_SHA256."
    )
