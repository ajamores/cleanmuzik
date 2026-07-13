"""Transcode stage — staged bestaudio → MP3 320 CBR (R1, T-005).

The second pipeline stage (spec §4). T-004 lands a tagged bestaudio file in its
native container (`.webm`/`.m4a`); this stage re-encodes it to **MP3 320 kbps
CBR and nothing else** (ADR-002) so every file that reaches beets — and Jellyfin
— is one uniform format.

Two things the encode must hold onto:

  1. **The embedded metadata.** T-004's `--embed-metadata` wrote the source
     title/artist into the file so beets has a non-empty query and a tag fallback
     (learnings). `-map_metadata 0` carries those tags into the MP3; losing them
     would send beets an empty MusicBrainz query → HTTP 400.
  2. **Constant bitrate.** libmp3lame emits CBR when driven by `-b:a` alone (a
     `-q:a` would flip it to VBR), so a plain `-b:a 320k` is the whole contract.

There is no cover art to preserve here: T-004 embeds text metadata only (no
thumbnail postprocessor), so art is beets' job downstream (`fetchart`/`embedart`,
T-003). This stage is text-tags-and-audio.

Sync and blocking on purpose — the pipeline runs one track at a time on a worker
thread (ADR-001; T-007/T-012), never the asyncio loop, so there is nothing to
await. Staging cleanup on failure is T-012's job.
"""

import shutil
import subprocess
from pathlib import Path

MP3_BITRATE = "320k"  # ADR-002 — MP3 320 CBR, the only output format.

# A single-song transcode is seconds of work; anything past this means ffmpeg has
# hung on a truncated/corrupt source. The pipeline is sequential and blocking
# (ADR-001), so without a bound one bad file would wedge the whole worker thread.
TRANSCODE_TIMEOUT_S = 300


class TranscodeError(RuntimeError):
    """Raised when ffmpeg fails to produce the MP3 320 output.

    Typed so T-012 can mark the transcode stage as the failing one (spec §7
    forced-failure names the stage) distinctly from a download or match error.
    """


def transcode_to_mp3_320(source: Path, dest: Path | None = None) -> Path:
    """Re-encode `source` to MP3 320 CBR, tags preserved; return the output path.

    `dest` defaults to `source` with a `.mp3` suffix (alongside it in staging).
    Whatever the source, `dest` must not resolve to the input file: ffmpeg `-y`
    would open the same path for read and write and truncate the source mid-decode.
    That collision is refused up front — it covers both the default (`.mp3` source)
    and an explicit `dest` that aliases the source (case/relative variants included).
    The pipeline always transcodes from a native container, so this only bites a
    misuse; we fail loudly rather than destroy the input.

    `dest`'s parent directory is created if absent (matching the download stage).

    Raises `TranscodeError` if ffmpeg is missing, times out, or exits non-zero.
    """
    source = Path(source)
    if not source.is_file():
        raise TranscodeError(f"Transcode source does not exist: {source}")

    dest = source.with_suffix(".mp3") if dest is None else Path(dest)
    if dest.resolve() == source.resolve():
        raise TranscodeError(
            f"Transcode dest resolves to the source; pass a distinct path: {source}"
        )
    dest.parent.mkdir(parents=True, exist_ok=True)

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise TranscodeError("ffmpeg not found on PATH")

    cmd = [
        ffmpeg,
        "-y",  # overwrite dest if a prior partial run left one
        "-i", str(source),
        "-map_metadata", "0",  # carry the source's embedded tags (job #1)
        "-vn",  # drop any video/thumbnail stream; audio only
        "-c:a", "libmp3lame",
        "-b:a", MP3_BITRATE,  # CBR (no -q:a); ADR-002
        "-id3v2_version", "3",  # ID3v2.3 — the widely-read tag version
        str(dest),
    ]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=TRANSCODE_TIMEOUT_S
        )
    except subprocess.TimeoutExpired as exc:
        raise TranscodeError(
            f"ffmpeg timed out after {TRANSCODE_TIMEOUT_S}s on {source}"
        ) from exc
    if result.returncode != 0:
        # ffmpeg's diagnosis lives on the last few stderr lines; surface them.
        tail = "\n".join(result.stderr.strip().splitlines()[-5:])
        raise TranscodeError(f"ffmpeg failed ({result.returncode}) on {source}:\n{tail}")

    if not dest.is_file():
        raise TranscodeError(f"ffmpeg reported success but {dest} is missing")

    return dest
