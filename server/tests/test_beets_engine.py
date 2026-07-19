"""Regression tests for the beets config in `beets_engine.configure_beets()`.

Focused on **ADR-012** (`ftintitle`). Nothing in the suite asserted on tagging
config before this file, which is exactly how ADR-011 stayed green while being
inert — a config option was set, no test read the field it claimed to change,
and the suite supplied no signal. These tests read the field.

They drive the real `FtInTitlePlugin` against a real `beets.library.Item`, not a
stub, because the failure mode being guarded is "the plugin loads and silently
does nothing" — which a stub cannot reproduce.
"""

from beets import library, plugins

from app.beets_engine import PLUGINS, configure_beets

# The exact values observed on the file that motivated ADR-012:
# /mnt/c/.../CleanMuzik/Nines feat. Tiggs da Author/NIC.mp3
OBSERVED_ARTIST = "Nines feat. Tiggs da Author"
OBSERVED_TITLE = "NIC"


def _ftintitle():
    """The loaded ftintitle plugin instance, configured as configure_beets left it."""
    configure_beets()
    for plugin in plugins.find_plugins():
        if plugin.name == "ftintitle":
            return plugin
    raise AssertionError("ftintitle is not loaded; ADR-012 says it must be")


def _item(**fields) -> library.Item:
    base = {"artist": OBSERVED_ARTIST, "albumartist": "", "title": OBSERVED_TITLE}
    return library.Item(**{**base, **fields})


def test_ftintitle_is_loaded():
    """ADR-012: the one plugin outside the spec §2 set."""
    configure_beets()
    loaded = {p.name for p in plugins.find_plugins()}
    assert "ftintitle" in PLUGINS
    assert set(PLUGINS) <= loaded, f"not loaded: {set(PLUGINS) - loaded}"


def test_feat_moves_from_artist_to_title():
    """The whole point: `$artist/$title` must not name a folder after a collab.

    Locks the *observed* values, not a synthetic pair — this is the case that
    produced `Nines feat. Tiggs da Author/NIC.mp3` in the first browser session.
    """
    item = _item()
    assert _ftintitle().ft_in_title(item) is True
    assert item.artist == "Nines"
    assert item.title == "NIC (feat. Tiggs da Author)"


def test_featured_credit_is_preserved_not_dropped():
    """`drop: no` — the credit moves, it is never discarded (owner requirement)."""
    item = _item()
    _ftintitle().ft_in_title(item)
    assert "Tiggs da Author" in item.title


def test_fires_even_when_albumartist_equals_artist():
    """The load-bearing one: `preserve_album_artist: no`, asserted by behaviour.

    `ft_in_title()` bails on `artist == albumartist` when this option is left at
    its default of yes. Today that never trips only because `TrackInfo` carries
    no albumartist, so `TPE2` is whatever yt-dlp left — currently *absent*, hence
    falsy, hence short-circuited before the comparison ever happens.

    That is an accident of a third-party tool's output, not a guarantee. If a
    future yt-dlp starts writing `TPE2`, the default would turn the plugin into a
    silent no-op. This test fails the moment someone "tidies up" the explicit
    setting in `configure_beets()`.
    """
    item = _item(albumartist=OBSERVED_ARTIST)
    assert _ftintitle().ft_in_title(item) is True
    assert item.artist == "Nines"


def test_title_that_already_credits_is_left_alone():
    """`contains_feat` guard: no doubling up when the title already says it."""
    item = _item(title="NIC (feat. Tiggs da Author)")
    _ftintitle().ft_in_title(item)
    assert item.artist == "Nines"
    assert item.title == "NIC (feat. Tiggs da Author)"


def test_plain_artist_is_untouched():
    """No feat., no change — the common case must not be disturbed."""
    item = _item(artist="Alicia Keys", title="You Don't Know My Name")
    assert _ftintitle().ft_in_title(item) is False
    assert item.artist == "Alicia Keys"
    assert item.title == "You Don't Know My Name"
