"""T-223 tests — the mutagen ID3/MP3-320 writer round-trips real tags + art.

The writer replaces beets' tag-write on the land path (ADR-033), so its Done-when is
a disk assertion: synthesize a real MP3 with ffmpeg, write with `write_tags`, and read
the frames back with the same MediaFile/ID3 the app and Jellyfin read with.
"""

import shutil
import subprocess
from pathlib import Path

import pytest
from mediafile import MediaFile
from mutagen.id3 import ID3

from app.tagwriter import write_tags

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None,
    reason="ffmpeg required to synthesize a real MP3 to tag",
)

# A 1x1 JPEG (valid enough for an APIC round-trip) and PNG, base-16 inlined so the
# test needs no image fixture on disk.
_JPEG = bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000ffdb00430008060607060508070707"
    "09090810131f1112111318170f1a1b1a181e2224221d24191a1e" + "20" * 90 + "ffd9"
)
_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000d49444154789c6360000002000154a24f8d000000"
    "0049454e44ae426082"
)


def _mp3_with_junk(path: Path) -> Path:
    """A real 1s MP3 pre-tagged with yt-dlp-style junk, to prove the clean slate."""
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    media = MediaFile(str(path))
    media.title = "Some YouTube Rip (Official Video)"
    media.artist = "SomeChannelVEVO"
    media.genre = "Entertainment"
    media.save()
    return path


def test_write_tags_round_trips_every_frame(tmp_path):
    path = _mp3_with_junk(tmp_path / "song.mp3")

    art = write_tags(
        path,
        artist="Pa Salieu",
        album="Send Them to Coventry",
        title="Frontline",
        year=2020,
        genre="Hip-Hop/Rap",
        lyrics="line one\nline two",
        isrc="GBXYZ2000001",
        image=_JPEG,
    )

    assert art is True
    media = MediaFile(str(path))
    assert media.artist == "Pa Salieu"
    assert media.albumartist == "Pa Salieu"  # defaults to artist on a singleton
    assert media.album == "Send Them to Coventry"
    assert media.title == "Frontline"
    assert media.year == 2020
    assert media.genre == "Hip-Hop/Rap"
    assert media.lyrics == "line one\nline two"
    assert media.isrc == "GBXYZ2000001"
    apic = ID3(str(path)).getall("APIC")
    assert len(apic) == 1 and apic[0].data == _JPEG and apic[0].mime == "image/jpeg"


def test_write_tags_clears_pre_existing_junk(tmp_path):
    # ADR-013: a field the identity doesn't supply must land BLANK, not keep yt-dlp's.
    path = _mp3_with_junk(tmp_path / "song.mp3")

    write_tags(path, artist="Real Artist", title="Real Title")

    media = MediaFile(str(path))
    assert media.artist == "Real Artist"
    assert media.title == "Real Title"
    assert not media.genre  # the junk "Entertainment" is gone, not kept
    assert not media.album


def test_write_tags_no_image_reports_no_art(tmp_path):
    path = _mp3_with_junk(tmp_path / "song.mp3")

    assert write_tags(path, artist="A", title="T", image=None) is False
    assert ID3(str(path)).getall("APIC") == []


def test_write_tags_embeds_png_with_correct_mime(tmp_path):
    path = _mp3_with_junk(tmp_path / "song.mp3")

    assert write_tags(path, title="T", image=_PNG) is True
    apic = ID3(str(path)).getall("APIC")
    assert apic[0].mime == "image/png"


def test_write_tags_on_headerless_mp3(tmp_path):
    # A transcode can emit an MP3 with NO ID3 header at all — the writer must tag it,
    # not raise (a raise would be swallowed by the seam, silently landing yt-dlp junk).
    path = tmp_path / "bare.mp3"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
         "-write_id3v2", "0", "-id3v2_version", "0", str(path)],
        capture_output=True, text=True, check=True,
    )
    from mutagen.id3 import ID3NoHeaderError

    with pytest.raises(ID3NoHeaderError):
        ID3(str(path))  # precondition: genuinely headerless

    assert write_tags(path, artist="Real Artist", title="Real Title", image=_JPEG) is True
    media = MediaFile(str(path))
    assert media.artist == "Real Artist"
    assert media.title == "Real Title"
    assert ID3(str(path)).getall("APIC")[0].data == _JPEG


def test_write_tags_on_missing_file_raises(tmp_path):
    # A genuine I/O failure surfaces (the seam keeps the track landed, reports degraded
    # tags) — it is NOT swallowed as a silent success.
    with pytest.raises(Exception):
        write_tags(tmp_path / "does-not-exist.mp3", title="T")
