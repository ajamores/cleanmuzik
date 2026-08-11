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
  `{shazam_artist, shazam_title, isrc, art_url, lyrics, matched, error}`.
- **Exit:** always `0` once a record is printed, *including* the no-match / error
  case (which prints `{"matched": false, "error": ...}`). The parent trusts the
  stdout JSON, not the exit code; a non-zero exit means this script itself failed
  to run (e.g. `shazamio` missing) and the parent maps that to a non-vote.

`art_url` / `lyrics` are captured into the record for the record's sake only —
R1.5 writes neither (spec §3; art/lyrics land via the existing beets path). They
are never a written tag on Shazam's authority.
"""

import asyncio
import json
import sys


def _empty_record() -> dict:
    """The full §6 shape, all keys present — the contract the parent parses."""
    return {
        "shazam_artist": None,
        "shazam_title": None,
        "isrc": None,
        "art_url": None,
        "lyrics": None,
        "matched": False,
        "error": None,
    }


def _art_url(track: dict):
    """Best-effort cover-art URL — captured only, never written (spec §3)."""
    images = track.get("images") or {}
    return images.get("coverarthq") or images.get("coverart") or None


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
