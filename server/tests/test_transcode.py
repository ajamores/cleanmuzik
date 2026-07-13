"""T-005 tests — the transcode stage produces MP3 320 CBR with tags intact.

These are real encode/probe round-trips, not mocks: we synthesize a tagged source
with ffmpeg (no network), run `transcode_to_mp3_320`, then read the output back
with ffprobe. That directly exercises the ticket's Done-when — "output probes as
MP3 320 kbps CBR with tags intact" (ADR-002) — rather than asserting on the code.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.transcode import TranscodeError, transcode_to_mp3_320

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe required for transcode round-trip tests",
)


def _make_source(path: Path, *, title: str, artist: str) -> Path:
    """Encode a short tagged tone into `path` as a stand-in for a bestaudio rip.

    Uses a native container (`.webm`/`.m4a`, what T-004 actually lands) with the
    same embedded-metadata shape it leaves behind, so the transcode faces a
    realistic input.
    """
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-metadata", f"title={title}",
            "-metadata", f"artist={artist}",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return path


def _probe(path: Path) -> dict:
    """Return the ffprobe JSON (format + streams) for `path`."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-print_format", "json",
            "-show_format", "-show_streams",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def test_output_is_mp3_320(tmp_path: Path):
    src = _make_source(tmp_path / "song.m4a", title="Test Song", artist="Test Artist")

    out = transcode_to_mp3_320(src)

    assert out == tmp_path / "song.mp3"
    assert out.is_file()

    info = _probe(out)
    audio = next(s for s in info["streams"] if s["codec_type"] == "audio")
    assert audio["codec_name"] == "mp3"
    # 320 kbps CBR — the bitrate should sit right at 320000, allowing for ffmpeg's
    # frame-level rounding. Some builds omit the stream-level bit_rate, so fall
    # back to the format-level value rather than KeyError on a correct encode.
    bit_rate = audio.get("bit_rate") or info["format"].get("bit_rate")
    assert bit_rate is not None, "neither stream nor format reported a bit_rate"
    assert abs(int(bit_rate) - 320_000) < 2_000


def test_tags_are_preserved(tmp_path: Path):
    src = _make_source(tmp_path / "song.webm", title="Keep Me", artist="Tagged")

    out = transcode_to_mp3_320(src)

    tags = {k.lower(): v for k, v in _probe(out)["format"].get("tags", {}).items()}
    assert tags.get("title") == "Keep Me"
    assert tags.get("artist") == "Tagged"


def test_explicit_dest_creates_missing_parent(tmp_path: Path):
    # The stage must create dest's parent (like the download stage), not lean on
    # the caller having made it — so this deliberately does not pre-create it.
    src = _make_source(tmp_path / "in.m4a", title="A", artist="B")
    dest = tmp_path / "custom" / "out.mp3"

    out = transcode_to_mp3_320(src, dest)

    assert out == dest
    assert dest.is_file()


def test_missing_source_raises(tmp_path: Path):
    with pytest.raises(TranscodeError, match="does not exist"):
        transcode_to_mp3_320(tmp_path / "nope.m4a")


def test_dest_aliasing_source_refuses(tmp_path: Path):
    # dest resolving to the source would make ffmpeg -y truncate the input while
    # decoding it; refuse both the default `.mp3`-source collision and an explicit
    # dest that is the source path.
    mp3_src = _make_source(tmp_path / "already.mp3", title="X", artist="Y")
    with pytest.raises(TranscodeError, match="resolves to the source"):
        transcode_to_mp3_320(mp3_src)  # default dest == source

    webm_src = _make_source(tmp_path / "song.webm", title="X", artist="Y")
    with pytest.raises(TranscodeError, match="resolves to the source"):
        transcode_to_mp3_320(webm_src, webm_src)  # explicit dest == source


def test_ffmpeg_nonzero_exit_raises(tmp_path: Path):
    # Garbage that ffmpeg cannot decode drives the primary error surface: a
    # non-zero exit must surface as TranscodeError, not a silent bad output.
    junk = tmp_path / "notaudio.webm"
    junk.write_bytes(b"this is not a media file" * 8)
    with pytest.raises(TranscodeError, match="ffmpeg failed"):
        transcode_to_mp3_320(junk)
