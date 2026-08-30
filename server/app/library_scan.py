"""Library-scan dedup — the recording-memory, minus the beets DB (T-226 step B).

Until T-226 "is this recording already in the library?" was one `MatchQuery("mb_trackid",
…)` against beets' own SQLite catalogue (`beets_library.db`), which the import pipeline
populated as a side effect of `session.run()`. Removing beets removes that catalogue, so
the question is now answered by **scanning the library files themselves**: every landed
track carries the MusicBrainz recording id in a UFID frame (`tagwriter.write_tags`), and
this module walks `library_dir`, reads that frame, and returns the matches.

Scan-on-demand, not a maintained index: at single-user scale the walk is cheap enough, and
it is self-healing — a file the owner moves, re-tags, or drops in by hand is seen on the
next scan with no catalogue to fall out of sync (the migrate/clean flow, R2.5, leans on
that). The trade-off (ADR-009 note, T-226): a file landed *before* the writer stamped the
frame carries no recording id and is invisible to dedup — the same "untagged legacy is
migrate input" case the seam already lived with.

`LibraryItem` mirrors the handful of beets `Item` attributes the dedup callers read —
`.path` (bytes), `.mb_trackid`, `.bitrate`, and `.id` — so `_replace_existing`,
`_park_duplicate`, and the review payload keep working unchanged. `.id` is **path
identity** (the decoded path), replacing beets' DB row id.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from mutagen.id3 import ID3, ID3NoHeaderError

logger = logging.getLogger("cleanmuzik")

# The UFID owner the writer stamps the recording id under (see tagwriter._MB_UFID_OWNER).
_MB_UFID_OWNER = "http://musicbrainz.org"


@dataclass(frozen=True)
class LibraryItem:
    """A library file that matched a recording id — the beets-`Item` stand-in for dedup.

    Carries what the dedup callers read off a duplicate: `path` (bytes, as beets' `Item.path`
    was, so the `os.fsdecode(item.path)` sites are unchanged), the matched `mb_trackid`,
    `bitrate` (the quality axis compared at acquire time, T-009), and `title`/`artist`/`album`
    (the "keep which?" review payload, `reviews._duplicate_detail`).
    """

    path: bytes
    mb_trackid: str
    bitrate: int
    title: str | None = None
    artist: str | None = None
    album: str | None = None

    @property
    def id(self) -> str:
        """Path identity — replaces beets' DB row id for the before/after set-diff in
        `_replace_existing` (a file is uniquely its path)."""
        return os.fsdecode(self.path)


def _recording_id(path: str) -> str | None:
    """The MusicBrainz recording id in the file's UFID frame, or None.

    Reads only the ID3 tag (not the audio stream) so the common no-duplicate scan stays
    cheap — bitrate is read separately, and only for a file that actually matches.
    """
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        return None
    except Exception as exc:  # noqa: BLE001 — an unreadable/corrupt tag is not a dedup match
        logger.debug("library scan: could not read tags at %s (%s)", path, exc)
        return None
    for frame in tags.getall("UFID"):
        if getattr(frame, "owner", None) == _MB_UFID_OWNER:
            data = getattr(frame, "data", b"") or b""
            return data.decode("utf-8", "ignore") or None
    return None


def _media_fields(path: str) -> dict:
    """Bitrate + title/artist/album for a matched file, read via mediafile (the same tag
    library the app reads everywhere). Only called for a matched file, so the audio-header
    parse it costs is off the common scan path; an unreadable file still counts as a match
    with blank fields."""
    try:
        from mediafile import MediaFile

        media = MediaFile(path)
        return {
            "bitrate": int(getattr(media, "bitrate", 0) or 0),
            "title": getattr(media, "title", None),
            "artist": getattr(media, "artist", None),
            "album": getattr(media, "album", None),
        }
    except Exception as exc:  # noqa: BLE001 — a match with an unreadable header still counts
        logger.debug("library scan: could not read media fields at %s (%s)", path, exc)
        return {"bitrate": 0, "title": None, "artist": None, "album": None}


def scan_for_recording(recording_id: str | None, library_dir: str | None) -> list[LibraryItem]:
    """Library files whose MusicBrainz recording id is `recording_id` (or []).

    The replacement for beets' `items_for_recording` DB query: walk `library_dir` for
    `.mp3` files carrying the matching recording-id frame. An empty id or missing directory
    returns [] (nothing can match), matching the old query's guard.
    """
    if not recording_id or not library_dir or not os.path.isdir(library_dir):
        return []
    matches: list[LibraryItem] = []
    for dirpath, _dirs, files in os.walk(library_dir):
        for name in files:
            if not name.lower().endswith(".mp3"):
                continue
            path = os.path.join(dirpath, name)
            if _recording_id(path) == recording_id:
                matches.append(
                    LibraryItem(os.fsencode(path), recording_id, **_media_fields(path))
                )
    return matches
