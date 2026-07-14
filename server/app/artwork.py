"""Cover art for singleton lands (T-007, Door B).

beets' `fetchart` plugin only decorates *albums* — its `fetch_art` opens with
`if task.is_album:` and returns for anything else. Every YouTube song imports as a
singleton (ADR-006), so fetchart never runs for us and a landed file has no cover.
This module fills that one gap: fetch the front cover from an official source using
the identity the fingerprint already earned, and embed it with beets' own art
helper (so we don't hand-roll tag writing — ADR-005).

Two sources, best-quality first:

  1. **Cover Art Archive** — MusicBrainz's official artwork vault, keyed by a
     *release* MBID (which the AcoustID lookup hands back alongside the recording).
     Full-resolution original scans.
  2. **iTunes Search** — by artist + title, upscaled. Covers the common case where
     our singleton resolved to no specific release (no MBID for CAA to use). The
     hit's artist is verified before use — a wrong cover is worse than none.

Art is *best-effort*: a fetch/embed hiccup must never un-land a correctly tagged
song, so the caller treats a False return as "no art", not a failure.
"""

import logging
import os
import re
import tempfile

import requests
from beetsplug._utils import art

logger = logging.getLogger("cleanmuzik")

_CAA_FRONT = "https://coverartarchive.org/release/{mbid}/front"
_ITUNES_SEARCH = "https://itunes.apple.com/search"
# A descriptive UA — CAA and iTunes both prefer a real identifier over a bare
# python-requests default, and MusicBrainz etiquette asks for one.
_UA = {"User-Agent": "CleanMuzik/0.1 (personal music library; +https://github.com/)"}
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
# A recording can appear on dozens of releases; the front cover is near-identical
# across them, so trying more than a few just risks stalling the (synchronous,
# ADR-001) import thread on a slow CAA. Cap it.
_MAX_CAA_RELEASES = 3


def _norm(value: str) -> str:
    """Lowercase alphanumerics only — for loose artist-name comparison."""
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def _artist_matches(candidate: str, wanted: str) -> bool:
    """True if two artist names plausibly refer to the same act.

    Deliberately loose (substring either way, punctuation/case-insensitive) so
    "a-ha" matches "A-Ha" but a different act's name doesn't — enough to reject an
    iTunes text-search hit for the wrong artist without over-rejecting real ones.
    """
    a, b = _norm(candidate), _norm(wanted)
    return bool(a and b and (a in b or b in a))


def _image_suffix(image_bytes: bytes) -> str:
    """`.png` for PNG magic bytes, else `.jpg` (CAA/iTunes serve one or the other)."""
    return ".png" if image_bytes[:8] == _PNG_MAGIC else ".jpg"


def _itunes_url_candidates(url100: str) -> list[str]:
    """High-res-first URL list from an `artworkUrl100`.

    The 100px thumbnail URL serves far larger by swapping the size token — the
    well-known iTunes trick. If the token isn't where we expect (Apple has varied
    it), the swap is a no-op; we still fall back to the original 100px URL rather
    than come away with nothing.
    """
    big = url100.replace("100x100bb", "1200x1200bb")
    return [big] if big == url100 else [big, url100]


def fetch_cover_art(
    *,
    artist: str,
    title: str,
    release_ids: tuple[str, ...] = (),
    timeout: int = 10,
    http=requests,
) -> bytes | None:
    """Return front-cover image bytes for a track, or None if none is found.

    Tries Cover Art Archive by release MBID (best quality, capped at a few), then
    iTunes by artist+title with the hit's artist verified. `http` is injectable for
    tests. Never raises for a network/parse failure — art is decorative; it logs
    and returns None.
    """
    if len(release_ids) > _MAX_CAA_RELEASES:
        logger.debug(
            "checking %d of %d releases on Cover Art Archive",
            _MAX_CAA_RELEASES,
            len(release_ids),
        )
    for mbid in release_ids[:_MAX_CAA_RELEASES]:
        try:
            resp = http.get(
                _CAA_FRONT.format(mbid=mbid),
                headers=_UA,
                timeout=timeout,
                allow_redirects=True,
            )
        except requests.RequestException as exc:
            logger.debug("Cover Art Archive fetch failed for release %s: %s", mbid, exc)
            continue
        if resp.status_code == 200 and resp.content:
            logger.info("cover art from Cover Art Archive (release %s)", mbid)
            return resp.content

    if artist and title:
        try:
            resp = http.get(
                _ITUNES_SEARCH,
                # limit>1 so a wrong-artist top hit doesn't cost us the real one.
                params={"term": f"{artist} {title}", "entity": "song", "limit": 5},
                headers=_UA,
                timeout=timeout,
            )
            resp.raise_for_status()
            results = resp.json().get("results") or []
        except (requests.RequestException, ValueError) as exc:
            logger.debug("iTunes search failed for %s — %s: %s", artist, title, exc)
            results = []

        for hit in results:
            if not _artist_matches(hit.get("artistName", ""), artist):
                continue
            url100 = hit.get("artworkUrl100") or ""
            if not url100:
                continue
            for url in _itunes_url_candidates(url100):
                try:
                    img = http.get(url, headers=_UA, timeout=timeout)
                except requests.RequestException as exc:
                    logger.debug("iTunes art fetch failed (%s): %s", url, exc)
                    continue
                if img.status_code == 200 and img.content:
                    if "1200x1200" not in url:
                        logger.info(
                            "cover art from iTunes at reduced size (%s — %s)",
                            artist,
                            title,
                        )
                    else:
                        logger.info("cover art from iTunes (%s — %s)", artist, title)
                    return img.content
            break  # right artist, but its art wouldn't fetch — don't try other hits

    logger.info("no cover art found for %s — %s", artist, title)
    return None


def embed_cover(item, image_bytes: bytes, *, log: logging.Logger = logger) -> bool:
    """Embed `image_bytes` into a landed beets Item's file via beets' art helper.

    Writes the bytes to a temp file (embed_item takes a path), then delegates to
    `beetsplug._utils.art.embed_item` — the same writer the `embedart` plugin uses
    — so tag handling stays beets-native. `ifempty=True` so we never clobber art
    that is somehow already present.

    Returns whether the file actually carries a cover afterwards: `embed_item` is
    silent when it declines (unreadable or unsupported image bytes), so we confirm
    from disk rather than report a cover that was never written.
    """
    suffix = _image_suffix(image_bytes)
    fd, tmp = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(image_bytes)
        art.embed_item(log, item, tmp, ifempty=True)
    finally:
        os.unlink(tmp)
    return bool(art.get_art(log, item))
