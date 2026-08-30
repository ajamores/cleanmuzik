"""Unit tests for the plain-Python mover (T-226 step A, `app/pathing.py`).

These lock the behaviour that used to be inherited silently from beets' `Item.destination`
+ `util.sanitize_path`/`legalize_path`/`unique_path` — verified byte-faithful against beets
2.12 at build time. Standalone (no beets import) so they survive beets' removal in step D.
"""

import os

import pytest

from app import pathing


class TestSanitization:
    """The six-rule NTFS/WSL replacement map, per component."""

    @pytest.mark.parametrize(
        "artist,title,expected",
        [
            # Windows-forbidden set <>:"/\|?* → _
            ('Some<Artist>:With"Bad|Chars?*', "ti/tle", "Some_Artist__With_Bad_Chars__/ti_tle"),
            # a forward slash inside the artist folder name is replaced, not a new dir
            ("AC/DC", "Back in Black", "AC_DC/Back in Black"),
            # leading dot and trailing dot both replaced
            (".leadingdot", "trailing.", "_leadingdot/trailing_"),
            # surrounding whitespace stripped (not replaced) on each component
            ("  spaced  ", "  song  ", "spaced/song"),
            # a leading dash is replaced
            ("-dashy", "song", "_dashy/song"),
        ],
    )
    def test_component_sanitized(self, artist, title, expected):
        assert pathing.relative_destination(artist, title) == expected + ".mp3"

    def test_control_chars_replaced(self):
        rel = pathing.relative_destination("ar\x01tist", "ti\x1ftle")
        assert rel == "ar_tist/ti_tle.mp3"


class TestNormalization:
    def test_nfc_applied(self):
        # An NFD-composed "é" (e + combining acute) normalizes to the single NFC codepoint —
        # the /mnt/c filename must match the byte form Jellyfin's scan expects (NOT_INDEXED trap).
        nfd = "Beyoncé"  # e + U+0301
        rel = pathing.relative_destination(nfd, "Cuff It")
        assert rel == "Beyoncé/Cuff It.mp3"  # single-codepoint é
        assert "́" not in rel


class TestTruncation:
    def test_component_truncated_to_200_bytes(self):
        rel = pathing.relative_destination("A" * 260, "B" * 260)
        artist_comp, filename = rel.split("/")
        assert len(artist_comp.encode()) == 200
        # the filename keeps room for the extension
        assert len(filename.encode()) == 200
        assert filename.endswith(".mp3")

    def test_multibyte_truncation_drops_half_char(self):
        # 100 × "🎹" (4 bytes each) = 400 bytes; truncating to 200 bytes lands on a boundary
        # (50 chars) with no half-cut codepoint left behind.
        rel = pathing.relative_destination("🎹" * 100, "song")
        artist_comp = rel.split("/")[0]
        assert len(artist_comp.encode()) <= 200
        assert "�" not in artist_comp  # no mojibake from a severed codepoint


class TestUniquePath:
    def test_no_collision_returns_path_unchanged(self):
        assert pathing.unique_path("/lib/A/Song.mp3", exists=lambda p: False) == "/lib/A/Song.mp3"

    def test_first_collision_appends_dot_one(self):
        taken = {"/lib/A/Song.mp3"}
        assert pathing.unique_path("/lib/A/Song.mp3", exists=lambda p: p in taken) == "/lib/A/Song.1.mp3"

    def test_walks_up_until_free(self):
        taken = {"/lib/A/Song.mp3", "/lib/A/Song.1.mp3", "/lib/A/Song.2.mp3"}
        assert pathing.unique_path("/lib/A/Song.mp3", exists=lambda p: p in taken) == "/lib/A/Song.3.mp3"

    def test_existing_numbered_path_reuniquifies_from_its_own_number(self):
        taken = {"/lib/A/Song.1.mp3"}
        assert pathing.unique_path("/lib/A/Song.1.mp3", exists=lambda p: p in taken) == "/lib/A/Song.2.mp3"


class TestDestination:
    def test_absolute_path_under_library_root(self):
        dest = pathing.destination(
            "Artist", "Title", library_dir="/lib", exists=lambda p: False
        )
        assert dest == "/lib/Artist/Title.mp3"

    def test_defaults_to_library_directory(self):
        dest = pathing.destination("Artist", "Title", exists=lambda p: False)
        assert dest == os.path.join(pathing.LIBRARY_DIRECTORY, "Artist", "Title.mp3")

    def test_collision_suffixes_the_absolute_path(self):
        taken = {"/lib/Artist/Title.mp3"}
        dest = pathing.destination(
            "Artist", "Title", library_dir="/lib", exists=lambda p: p in taken
        )
        assert dest == "/lib/Artist/Title.1.mp3"
