"""T-309 acceptance — `track.done` reports the genre actually on the landed file.

The bug (T-037 defect 2, sharpened by the T-103 verify): `lastgenre` writes a
genre to the file, but the in-memory `item.genre` the seam snapshots for the
receipt still reads `None` — so `track.done` claimed "no genre" on a file that
had one. The fix reads the tag back OFF THE LANDED FILE for the payload.

These tests reproduce that exact discrepancy: an item whose in-memory `genre`
is `None` pointing at a real file whose genre tag on disk is set. The Done-when
is a disk-vs-event assertion, so the file is synthesized for real (ffmpeg) and
the tag written with the same `MediaFile` the app reads with.
"""

import shutil
from types import SimpleNamespace

import pytest

from app.import_seam import _genre_on_disk, _landed_tags

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None,
    reason="ffmpeg required to synthesize a tagged audio file",
)


def _mp3_with_genre(path, genre: str | None):
    """A real 1-second MP3 at `path`, with `genre` written by MediaFile (or none)."""
    import subprocess

    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    # Write (or explicitly clear) the genre with the same MediaFile the app reads
    # with, so the "bare" precondition is deterministic rather than relying on the
    # ffmpeg build leaving no default TCON frame.
    from mediafile import MediaFile

    media = MediaFile(str(path))
    media.genre = genre
    media.save()
    return path


def _landed_item(path, *, genre_in_memory):
    """An item as the seam holds it post-run: real landed `path`, plus the possibly
    stale in-memory `genre` snapshot (None in the T-103 case)."""
    return SimpleNamespace(
        path=str(path).encode(),  # beets item paths are bytes
        title="Strawberry Swing",
        artist="Frank Ocean",
        album=None,
        year=2011,
        genre=genre_in_memory,
        lyrics=None,
    )


def test_track_done_carries_the_genre_on_disk_not_the_stale_snapshot(tmp_path):
    # The exact T-103 discrepancy: disk 'Soul', in-memory None.
    path = _mp3_with_genre(tmp_path / "song.mp3", "Soul")
    item = _landed_item(path, genre_in_memory=None)

    tags = _landed_tags(item, has_art=False)

    assert tags["genre"] == "Soul"  # read off disk, not the None snapshot


def test_bare_genre_stays_bare(tmp_path):
    # A file with genuinely no genre (real per-recording Last.fm gap, spec §6) still
    # reports null — the fix must not fabricate a genre, only report the true one.
    path = _mp3_with_genre(tmp_path / "song.mp3", None)
    item = _landed_item(path, genre_in_memory=None)

    assert _landed_tags(item, has_art=False)["genre"] is None


def test_bare_disk_tag_does_not_shadow_a_present_in_memory_genre(tmp_path):
    # Finding 3 inverse of the T-103 case: the file landed with a bare genre tag but
    # the in-memory snapshot carries one. Report the genre either source has — a bare
    # disk tag must not overwrite a present in-memory value with null.
    path = _mp3_with_genre(tmp_path / "song.mp3", None)
    item = _landed_item(path, genre_in_memory="Soul")

    assert _landed_tags(item, has_art=False)["genre"] == "Soul"


def test_unreadable_path_degrades_to_the_in_memory_field(tmp_path):
    # Best-effort: if the file can't be read, fall back to the in-memory value
    # rather than raising — a missing tag must never un-land or crash a receipt.
    item = _landed_item(tmp_path / "does-not-exist.mp3", genre_in_memory="Soul")

    assert _genre_on_disk(item) == "Soul"
