"""Cover art for singleton lands (T-007, Door B).

beets' `fetchart` plugin only decorates *albums* — its `fetch_art` opens with
`if task.is_album:` and returns for anything else. Every YouTube song imports as a
singleton (ADR-006), so fetchart never runs for us and a landed file has no cover.
This module fills that one gap: fetch the front cover from an official source using
the identity the fingerprint already earned. It only *fetches* the bytes — the mutagen
writer (`app/tagwriter.py`, T-223/ADR-033) embeds them as the APIC frame. (Until then
this module also embedded via beets' `embedart` helper; that path is retired with the
tag-writing plugins in T-224.)

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

import requests

from app import normalize
from app.config import MUSICBRAINZ_USER_AGENT

logger = logging.getLogger("cleanmuzik")

_CAA_FRONT = "https://coverartarchive.org/release/{mbid}/front"
_ITUNES_SEARCH = "https://itunes.apple.com/search"
# A descriptive UA — CAA and iTunes both prefer a real identifier over a bare
# python-requests default, and MusicBrainz etiquette asks for one. From its single
# home in config so this and `app.isrc` never drift.
_UA = {"User-Agent": MUSICBRAINZ_USER_AGENT}
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
# A recording can appear on dozens of releases. Each is a blocking GET on the
# synchronous (ADR-001) import thread, and CAA 307-redirects `/front` to archive.org
# backends that occasionally hang — live profiling (T-216) clocked one track's art at
# ~36s under a 10s-per-release timeout. The tail is bounded by the `timeout` below, NOT
# by this cap: a release with no cover 404s fast, so keeping a few preserves art
# *recall* (release #1 may lack a front cover where #2 has it) at ~no typical cost.
_MAX_CAA_RELEASES = 3


def _artist_matches(candidate: str, wanted: str) -> bool:
    """True if two artist names plausibly refer to the same act.

    Delegates to `normalize.loose_match` — the one loose alnum-fold containment shared
    with the T-205 sense gate, so "same artist" means the same thing to the cover-art
    gate and the identity gate (and both gain the case/diacritic fold: "a-ha" ≈ "A-Ha",
    "Beyonce" ≈ "Beyoncé"). Loose by design — enough to reject an iTunes text-search hit
    for the wrong artist without over-rejecting real ones.
    """
    return normalize.loose_match(candidate, wanted)


def _looks_like_image(data: bytes) -> bool:
    """True when `data` starts with a known cover-image magic signature.

    Guards the plain-URL fetch (`fetch_url_image`): a Shazam `art_url` or a YouTube
    thumbnail can 200 with an HTML soft-404 body, which must not be embedded as a cover.
    JPEG / PNG / GIF / WebP cover the formats these sources actually serve.
    """
    return (
        data[:2] == b"\xff\xd8"  # JPEG
        or data[:8] == _PNG_MAGIC  # PNG
        or data[:4] == b"GIF8"  # GIF
        or (data[:4] == b"RIFF" and data[8:12] == b"WEBP")  # WebP
    )


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
    timeout: int = 5,  # T-216: the tail-bound. requests applies this to connect AND
    # each read, and `allow_redirects` means a CAA→archive.org hang costs it per hop —
    # 5s caps the stall well under the old 10s while leaving the iTunes fallback (and
    # its 1200x1200 image GET) comfortable headroom for a real, slow-but-live response.
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


def fetch_url_image(
    url: str | None,
    *,
    timeout: int = 5,
    http=requests,
) -> bytes | None:
    """Return image bytes from a plain cover URL, or None — the T-222 art source.

    ADR-033 makes Shazam's `art_url` (the `coverarthq` we already fetch every track)
    the cover of record for a Shazam-corroborated land, with the YouTube thumbnail as
    the fallback. Both are plain image URLs — no CAA release-picking, which is the
    wrong-cover class this replaces — so this is a single validated GET. Best-effort,
    like `fetch_cover_art`: any network/parse failure logs and returns None (art is
    decorative; a hiccup must never un-land a track). `http` is injectable for tests.
    """
    if not url:
        return None
    try:
        resp = http.get(url, headers=_UA, timeout=timeout, allow_redirects=True)
    except requests.RequestException as exc:
        logger.debug("cover URL fetch failed (%s): %s", url, exc)
        return None
    if resp.status_code == 200 and resp.content:
        if not _looks_like_image(resp.content):
            # A 200 that isn't an image — a soft-404 HTML body, an expired-URL page.
            # Never embed it as a cover; treat it as no art.
            logger.debug("cover URL returned a non-image body (%s) — ignoring", url)
            return None
        logger.info("cover art from URL (%s)", url)
        return resp.content
    logger.debug("cover URL returned no image (%s, status %s)", url, resp.status_code)
    return None


def crop_to_square(image_bytes: bytes) -> bytes:
    """Centre-crop `image_bytes` to a square — the YouTube-thumbnail fallback (T-223).

    Shazam's `art_url` is already square album art, but the YouTube thumbnail fallback
    (`hqdefault.jpg`, 4:3) lands letterboxed in a square library grid. Centre-crop it to
    the largest centred square so the cover reads like real album art. Best-effort: any
    decode/encode failure (or an already-square image) returns the original bytes
    unchanged — a non-square cover is better than none, and never un-lands a track.
    """
    try:
        from io import BytesIO

        from PIL import Image

        img = Image.open(BytesIO(image_bytes))
        width, height = img.size
        if width == height:
            return image_bytes
        side = min(width, height)
        left = (width - side) // 2
        top = (height - side) // 2
        cropped = img.crop((left, top, left + side, top + side))
        fmt = img.format or "JPEG"
        if fmt == "JPEG" and cropped.mode not in ("RGB", "L"):
            cropped = cropped.convert("RGB")
        buf = BytesIO()
        cropped.save(buf, format=fmt)
        return buf.getvalue()
    except Exception as exc:  # noqa: BLE001 — a crop failure falls back to the raw image
        logger.debug("thumbnail crop failed (%s) — using the uncropped image", exc)
        return image_bytes
