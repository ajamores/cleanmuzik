"""SourceSignals — sense 1: the YouTube claim, lifted from yt-dlp's `info` dict (R1.5, T-201).

The download stage (`download.py`) already asks yt-dlp to `extract_info`, then throws
the `info` dict away once it has the file path. R1.5 needs that dict: it is the
**first of three senses** the reconcile call weighs (spec §2), the textual evidence a
human would read off the YouTube page — the title, who uploaded it, the description, the
tags — plus whatever *structured* music metadata YouTube attached.

This module defines the shape **once** (`SourceSignals`) and the pure mapping from a raw
`info` dict to it (`SourceSignals.from_info`). It is deliberately plumbing: it derives no
match and writes no tag. It only surfaces what YouTube said so a later stage (T-204's
reconcile seam) can hand it to the LLM and (T-205's gate) can vote with it.

## Two fields feed the code vote; two ride only for judgment

`yt_artist` / `yt_title` are the **voting** fields — T-205 normalized-matches them against
each candidate. They prefer YouTube's *structured* music fields (`info["artist"]` /
`info["track"]`), which official and `"- Topic"` uploads carry clean, and fall back to
parsing the raw title, then to the Topic uploader, then to nothing (`yt_artist=None` ⇒
`yt` supports no candidate, so T-205 parks conservatively).

`yt_album` / `yt_release_year` are **JUDGMENT-ONLY** (spec §2, spec §5): they travel in the
blob so the LLM can *read* them, but are **never** a written fact and **never** in T-205's
2-of-3 code vote. YouTube's `release_year` is the *upload* year and its `album` is often a
`"- Topic"` auto-album — so the written facts still come only from a real MusicBrainz/ISRC
lookup. See the field comments below; do not promote either into the vote.
"""

from __future__ import annotations

from dataclasses import dataclass

from app import normalize

# How much of the description to carry. The full blob is a promo essay — links,
# tracklists, "subscribe" boilerplate — none of which helps identity and all of which
# bloats the prompt. A bounded prefix keeps the useful lede (often "Artist · Title",
# release notes) without shipping the rest. Characters, not lines.
_DESCRIPTION_HEAD_CHARS = 500

# YouTube's auto-generated music channels are named "<Artist> - Topic". Matching that
# suffix is how we (a) know the uploader is a Topic channel and (b) recover the artist
# from it when no structured field or title split gave one.
_TOPIC_SUFFIX = "- Topic"


@dataclass(frozen=True)
class SourceSignals:
    """The yt-dlp sense for one track — every field always present (empty/`None`, never missing).

    Frozen and always fully populated: a consumer (T-204's reconcile evidence, T-205's
    vote) reads any field without a `.get` or a missing-key guard. Built only via
    `from_info`, which fills every field from the `info` dict or a documented default.
    """

    # --- textual evidence (for the LLM to read; not the code vote) ---------------
    title: str            # raw video title, as YouTube gave it
    uploader: str         # channel/uploader name ("Artist - Topic", a label, a person)
    channel_is_topic: bool  # True iff the uploader/channel is an auto-generated "- Topic"
    description_head: str  # bounded prefix of the description (not the whole blob)
    tags: list[str]       # YouTube video tags (often genre-ish / artist-ish hints)
    duration: float | None  # seconds, or None if yt-dlp was silent
    video_id: str         # the YouTube id

    # --- voting fields (T-205's code vote normalized-matches these) --------------
    yt_artist: str | None  # structured `artist` → title-split → Topic uploader → None
    yt_title: str          # structured `track` → title-split → raw title (always a string)

    # --- JUDGMENT-ONLY: for the AI to weigh, NEVER a written fact, NEVER voted ----
    # YouTube's `release_year` is the *upload* year and its `album` is often a
    # "- Topic" auto-album. These ride in the reconcile evidence so the LLM can pick
    # the right candidate, but T-205 must not put them in the 2-of-3 vote and no stage
    # writes them as tags — written facts come only from MusicBrainz/ISRC (spec §5).
    yt_album: str | None
    yt_release_year: int | None

    @classmethod
    def from_info(cls, info: dict) -> "SourceSignals":
        """Map a raw yt-dlp `info` dict to `SourceSignals` — pure, no I/O.

        Prefers YouTube's structured music fields for the voting pair and falls back,
        in order, to the Topic channel name then a blind title parse (`yt_artist`) /
        the raw title (`yt_title`). Every field is set explicitly, so the result never
        carries a missing key regardless of how sparse `info` was.
        """
        title = _clean_str(info.get("title"))
        uploader = _clean_str(info.get("uploader"))
        channel = _clean_str(info.get("channel"))

        channel_is_topic = _is_topic(uploader) or _is_topic(channel)

        parsed_artist, parsed_title = normalize.split_leading_artist(title)

        # yt_artist: structured field → reliable "- Topic" channel → blind title
        # split (last resort) → None. The Topic channel name is a trustworthy
        # artist source; the title split is a guess (normalize.py:24-28), so it
        # runs only after the reliable signals are exhausted.
        structured_artist = _clean_str(info.get("artist")) or None
        yt_artist = (
            structured_artist
            or _topic_artist(uploader)
            or _topic_artist(channel)
            or parsed_artist
        )

        # yt_title: structured field → title split → raw title (never None).
        structured_track = _clean_str(info.get("track")) or None
        yt_title = structured_track or parsed_title or title

        description = _clean_str(info.get("description"))
        tags = info.get("tags") or []

        return cls(
            title=title,
            uploader=uploader,
            channel_is_topic=channel_is_topic,
            description_head=description[:_DESCRIPTION_HEAD_CHARS],
            tags=list(tags),
            duration=info.get("duration"),
            video_id=_clean_str(info.get("id")),
            yt_artist=yt_artist,
            yt_title=yt_title,
            yt_album=_clean_str(info.get("album")) or None,
            yt_release_year=info.get("release_year"),
        )


def _clean_str(value) -> str:
    """A trimmed string for a field yt-dlp may return as None or non-str."""
    if value is None:
        return ""
    return str(value).strip()


def _is_topic(name: str) -> bool:
    """True when a channel/uploader name is an auto-generated `"… - Topic"`."""
    return name.strip().endswith(_TOPIC_SUFFIX)


def _topic_artist(name: str) -> str | None:
    """Recover `"Artist"` from a `"Artist - Topic"` uploader, else `None`."""
    stripped = name.strip()
    if not stripped.endswith(_TOPIC_SUFFIX):
        return None
    artist = stripped[: -len(_TOPIC_SUFFIX)].rstrip(" -–—")
    return artist or None
