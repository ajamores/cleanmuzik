"""The library-scan dedup (T-226 step B, `app/library_scan.py`).

The filesystem replacement for beets' `MatchQuery("mb_trackid", …)`: walk the library for
the recording-id frame the writer stamps. Uses real MP3s (ffmpeg-synthesized, tagged with
the real writer) so the frame the scan reads is the exact one landing writes — the same
end-to-end discipline as `test_import_seam.py`'s on-disk seam tests.
"""

import shutil
import subprocess

import pytest

from app import library_scan
from app.tagwriter import write_tags

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None,
    reason="ffmpeg required to synthesize a real MP3 to tag + scan",
)


def _landed_mp3(path, recording_id, *, artist="Artist", title="Title"):
    """A real 1s MP3 at `path`, tagged by the real writer with `recording_id` (or none)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    write_tags(str(path), artist=artist, title=title, recording_id=recording_id)
    return path


def test_finds_a_landed_file_by_recording_id(tmp_path):
    lib = tmp_path / "lib"
    _landed_mp3(lib / "Artist" / "Title.mp3", "rec-A")

    found = library_scan.scan_for_recording("rec-A", str(lib))

    assert [i.mb_trackid for i in found] == ["rec-A"]
    assert found[0].id.endswith("Artist/Title.mp3")
    assert found[0].bitrate > 0  # read off the real audio header


def test_carries_title_artist_album_for_the_keep_which_payload(tmp_path):
    # `_duplicate_detail` renders the existing copy's title/artist/album — the scan must
    # carry them off the file, not just the recording id + bitrate.
    lib = tmp_path / "lib"
    _landed_mp3(lib / "Nas" / "N.Y. State of Mind.mp3", "rec-A", artist="Nas", title="N.Y. State of Mind")

    item = library_scan.scan_for_recording("rec-A", str(lib))[0]

    assert item.artist == "Nas"
    assert item.title == "N.Y. State of Mind"


def test_ignores_a_different_recording(tmp_path):
    lib = tmp_path / "lib"
    _landed_mp3(lib / "A" / "One.mp3", "rec-A")
    _landed_mp3(lib / "B" / "Two.mp3", "rec-B")

    assert [i.id for i in library_scan.scan_for_recording("rec-B", str(lib))] == [
        str(lib / "B" / "Two.mp3")
    ]


def test_file_without_the_frame_is_invisible(tmp_path):
    # The backfill caveat (ADR-009 / T-226): a file landed before the writer stamped the id
    # carries no frame and cannot be deduped — it is migrate input, not a dedup match.
    lib = tmp_path / "lib"
    _landed_mp3(lib / "Legacy" / "Old.mp3", None)  # no recording id written

    assert library_scan.scan_for_recording("rec-A", str(lib)) == []


def test_multiple_copies_of_one_recording_all_returned(tmp_path):
    # The keep_both state: two files share a recording id. Both come back (the caller's
    # ambiguity guard decides what to do with them).
    lib = tmp_path / "lib"
    _landed_mp3(lib / "A" / "Song.mp3", "rec-A")
    _landed_mp3(lib / "A" / "Song.1.mp3", "rec-A")

    assert len(library_scan.scan_for_recording("rec-A", str(lib))) == 2


def test_empty_id_or_missing_dir_returns_empty(tmp_path):
    assert library_scan.scan_for_recording(None, str(tmp_path)) == []
    assert library_scan.scan_for_recording("", str(tmp_path)) == []
    assert library_scan.scan_for_recording("rec-A", str(tmp_path / "nope")) == []


def test_non_mp3_files_are_skipped(tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "cover.jpg").write_bytes(b"not audio")
    (lib / "notes.txt").write_text("hello")

    assert library_scan.scan_for_recording("rec-A", str(lib)) == []
