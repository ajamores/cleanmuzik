"""Shazam recognition runner — executed by the isolated 3.12 venv, NOT imported.

This file is the *other side* of the subprocess boundary owned by `app/shazam.py`
(T-202). The app runs on Python 3.14, which has no `shazamio-core` wheel; the
`shazamio` recognition therefore runs in `server/.venv-shazam` (3.12) and is
reached only by spawning **this script as a file** with that interpreter. It is
deliberately standalone — it imports `shazamio` + stdlib and **nothing from
`app`** — because the 3.12 interpreter does not have the app package on its path
(and must not need it). See ADR-024 for why the boundary is a process, not an
import.

## Subprocess contract (owned here + in `shazam.py`)

- **In:**  `sys.argv[1]` — an absolute audio file path.
- **Out:** exactly one JSON object on **stdout** — the spec §6 Shazam record
  `{shazam_artist, shazam_title, isrc, art_url, lyrics, album, year, genre,
  matched, error}`.
- **Exit:** always `0` once a record is printed, *including* the no-match / error
  case (which prints `{"matched": false, "error": ...}`). The parent trusts the
  stdout JSON, not the exit code; a non-zero exit means this script itself failed
  to run (e.g. `shazamio` missing) and the parent maps that to a non-vote.

`art_url` / `lyrics` are captured into the record for the record's sake only —
R1.5 writes neither (spec §3; art/lyrics land via the existing beets path). They
are never a written tag on Shazam's authority.

`album` / `year` / `genre` (T-221) are the tag payload the T-220 reshape will
*write* from the accepted identity (T-222/T-223). This ticket only captures them
into the record — all three are already present in the `recognize` `track` dict
(the SONG section's metadata rows + `genres.primary`), so this is capture, not a
new network call.
"""

import asyncio
import json
import re
import sys


def _empty_record() -> dict:
    """The full §6 shape, all keys present — the contract the parent parses."""
    return {
        "shazam_artist": None,
        "shazam_title": None,
        "isrc": None,
        "art_url": None,
        "lyrics": None,
        "album": None,
        "year": None,
        "genre": None,
        "matched": False,
        "error": None,
    }


def _art_url(track: dict):
    """Best-effort cover-art URL — captured only, never written (spec §3)."""
    images = track.get("images") or {}
    return images.get("coverarthq") or images.get("coverart") or None


def _labelled(track: dict, label: str):
    """A labelled value (Album, Released, ...) from the SONG section's metadata rows.

    Shazam exposes album + release date only as `{title, text}` rows inside the
    SONG section's `metadata` — never as named track fields — so match by label,
    mirroring the untyped-dict walk `_lyrics` already does over `sections`.

    Caveat (accepted): the row *titles* are Shazam's display strings, returned in
    the recognition locale. Under `.venv-shazam`'s default (English) they are
    "Album"/"Released"; a non-English locale would title them otherwise and this
    match would miss (album/year → None, fail-soft). There is no structured album
    field in the response to key off instead, so the label match stands.
    """
    label = label.lower()
    for section in track.get("sections") or []:
        if section.get("type") != "SONG":
            continue
        for meta in section.get("metadata") or []:
            if (meta.get("title") or "").lower() == label:
                return meta.get("text") or None
    return None


def _year(track: dict):
    """Release year (int) from Shazam's 'Released' row.

    Shazam's 'Released' text is usually 'YYYY' but can be a full date
    ('September 25, 2020'); the field is named `year` and downstream writes it to
    an integer tag, so extract the first 4-digit year rather than pass the raw
    string on. No 4-digit run ⇒ None (a non-year string would poison a year tag).
    """
    text = _labelled(track, "Released")
    if not text:
        return None
    match = re.search(r"\d{4}", text)
    return int(match.group()) if match else None


def _genre(track: dict):
    """Primary genre — `genres.primary` on the track dict."""
    genres = track.get("genres") or {}
    return genres.get("primary") or None


def _lyrics(track: dict):
    """Best-effort synced/plain lyrics text — captured only, never written."""
    for section in track.get("sections") or []:
        if section.get("type") == "LYRICS":
            lines = section.get("text") or []
            if lines:
                return "\n".join(lines)
    return None


async def _recognize(path: str) -> dict:
    from shazamio import Shazam

    out = await Shazam().recognize(path)
    track = (out or {}).get("track") or {}
    rec = _empty_record()
    if not track:
        return rec  # no match — matched stays False, error stays None
    rec.update(
        shazam_artist=track.get("subtitle"),
        shazam_title=track.get("title"),
        isrc=track.get("isrc"),
        art_url=_art_url(track),
        lyrics=_lyrics(track),
        album=_labelled(track, "Album"),
        year=_year(track),
        genre=_genre(track),
        matched=True,
    )
    return rec


def main() -> int:
    if len(sys.argv) < 2:
        rec = _empty_record()
        rec["error"] = "no audio path argument"
        print(json.dumps(rec))
        return 0
    try:
        rec = asyncio.run(_recognize(sys.argv[1]))
    except Exception as exc:  # noqa: BLE001 — fail-soft: any failure is a non-vote, never a crash
        rec = _empty_record()
        rec["error"] = f"{type(exc).__name__}: {exc}"
    print(json.dumps(rec))
    return 0


if __name__ == "__main__":
    sys.exit(main())
