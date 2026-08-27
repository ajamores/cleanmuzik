"""Direct mutagen ID3/MP3-320 tag + art writer (T-223, ADR-033).

The land tail's writer. Until this ticket beets wrote a landed track's tags (its
`write` import stage) and `embedart` its cover; ADR-033 retires beets from
tag-writing (matching already left it for the senses), so the file that beets
copies into the library is now tagged **here**, in-process, with mutagen — no beets
write on the path.

Adapts muziktest's `real/tagwriter.py` pattern, but muziktest writes MP4 atoms
(`Mp4TagWriter`); cleanmuzik's output is MP3-320 (ADR-002), so this is a genuine
ID3 re-implementation, not a copy. One function, `write_tags`, writes the
authoritative frames + an APIC cover and returns whether the cover actually landed.

**Clean slate (ADR-013).** beets copies the staging file with `write` off, so the
bytes on disk still carry whatever yt-dlp embedded (channel name, upload date,
category as "genre"). We strip the existing tag and write only the fields the
accepted identity supplies — a field left `None` lands blank, never keeping the
YouTube value, exactly as `from_scratch` did for the beets path.
"""

import logging
import os

from mutagen.id3 import (
    APIC,
    ID3,
    TALB,
    TCON,
    TDRC,
    TIT2,
    TPE1,
    TPE2,
    TSRC,
    USLT,
    ID3NoHeaderError,
)

logger = logging.getLogger("cleanmuzik")

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _apic_mime(image: bytes) -> str:
    """The MIME type for an APIC frame — PNG magic, else JPEG (what our sources serve)."""
    return "image/png" if image[:8] == _PNG_MAGIC else "image/jpeg"


def write_tags(
    path: str | bytes,
    *,
    artist: str | None = None,
    albumartist: str | None = None,
    album: str | None = None,
    title: str | None = None,
    year: int | None = None,
    genre: str | None = None,
    lyrics: str | None = None,
    isrc: str | None = None,
    image: bytes | None = None,
) -> bool:
    """Write authoritative ID3 frames (+ an APIC cover) onto the MP3 at `path`.

    Returns whether a cover was embedded (`image` present and the APIC frame added) —
    the seam carries this up as `Outcome.art_embedded`. Every text field is optional:
    a `None`/empty value writes no frame (a blank tag, per ADR-013), never a stale one.

    Raises on a genuine file I/O failure (an unreadable/unwritable path) so the caller
    can keep the track landed but report degraded tags; an unusable `image` is caught
    here (the cover is decorative) — the text frames still land and it returns False.
    """
    fspath = os.fsdecode(path)
    try:
        tags = ID3(fspath)
    except ID3NoHeaderError:
        tags = ID3()
    # ADR-013 clean slate: drop every existing frame (yt-dlp junk included) before
    # writing ours, so a field the identity doesn't supply lands blank, not stale.
    # `clear()`, NOT `delete()`: a headerless MP3 (a transcode that embedded no ID3)
    # builds a filename-less ID3() above, and `delete()` on it raises TypeError —
    # which `_write_landed_tags` would swallow, silently landing the yt-dlp junk. The
    # fresh `save(fspath)` below rewrites the file's tag from these frames alone.
    tags.clear()

    if title:
        tags.add(TIT2(encoding=3, text=title))
    if artist:
        tags.add(TPE1(encoding=3, text=artist))
    # $artist/$title is the singleton path, so albumartist == artist keeps Jellyfin's
    # album-artist grouping coherent with the folder when no explicit one is supplied.
    album_artist = albumartist or artist
    if album_artist:
        tags.add(TPE2(encoding=3, text=album_artist))
    if album:
        tags.add(TALB(encoding=3, text=album))
    if year:
        tags.add(TDRC(encoding=3, text=str(year)))
    if genre:
        tags.add(TCON(encoding=3, text=genre))
    if isrc:
        tags.add(TSRC(encoding=3, text=isrc))
    if lyrics:
        tags.add(USLT(encoding=3, lang="eng", desc="", text=lyrics))

    art_embedded = False
    if image:
        try:
            tags.add(
                APIC(
                    encoding=3,
                    mime=_apic_mime(image),
                    type=3,  # front cover
                    desc="",
                    data=image,
                )
            )
            art_embedded = True
        except Exception as exc:  # noqa: BLE001 — a bad cover must not fail the tag write
            logger.warning("could not build APIC for %s (%s) — no cover", fspath, exc)

    tags.save(fspath)
    return art_embedded
