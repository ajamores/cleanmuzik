"""T-007 Door B tests — cover art fetch + embed.

`fetch_cover_art` is tested against a fake HTTP client (no network): the source
order (Cover Art Archive first, iTunes fallback) and the "found nothing" path.
`embed_cover` is a real round-trip — synthesize a tiny MP3 and JPEG with ffmpeg,
embed, then read the APIC frame back — so it proves the actual side effect the
done-when needs (a cover on the file), not just that the code ran.
"""

import logging
import shutil
import subprocess
from pathlib import Path

import pytest

from app.artwork import (
    _MAX_CAA_RELEASES,
    _image_suffix,
    embed_cover,
    fetch_cover_art,
    fetch_url_image,
)


def test_image_suffix_detects_png_vs_jpeg():
    assert _image_suffix(b"\x89PNG\r\n\x1a\n" + b"...") == ".png"
    assert _image_suffix(b"\xff\xd8\xff\xe0jpegheader") == ".jpg"
    assert _image_suffix(b"") == ".jpg"  # unknown -> assume jpeg


class _Resp:
    def __init__(self, status=200, content=b"", json_data=None):
        self.status_code = status
        self.content = content
        self._json = json_data

    def json(self):
        if self._json is None:
            raise ValueError("no json body")
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(str(self.status_code))


class _FakeHTTP:
    """Routes GETs through a handler(url, kwargs) -> _Resp; records calls."""

    def __init__(self, handler):
        self.handler = handler
        self.urls = []

    def get(self, url, **kwargs):
        self.urls.append(url)
        return self.handler(url, kwargs)


def test_fetch_url_image_returns_bytes_on_200():
    # T-222: the Shazam art_url / thumbnail source is a single validated GET.
    http = _FakeHTTP(lambda url, kw: _Resp(200, b"\xff\xd8SHAZAM-JPEG"))
    assert fetch_url_image("https://shz/cover.jpg", http=http) == b"\xff\xd8SHAZAM-JPEG"
    assert http.urls == ["https://shz/cover.jpg"]


def test_fetch_url_image_none_url_makes_no_request():
    http = _FakeHTTP(lambda url, kw: _Resp(200, b"x"))
    assert fetch_url_image(None, http=http) is None
    assert http.urls == []  # a missing art_url never hits the network


def test_fetch_url_image_returns_none_on_error_status():
    http = _FakeHTTP(lambda url, kw: _Resp(404, b""))
    assert fetch_url_image("https://shz/missing.jpg", http=http) is None


def test_fetch_url_image_rejects_a_200_non_image_body():
    # A soft-404: HTTP 200 whose body is HTML, not an image — must not be embedded.
    http = _FakeHTTP(lambda url, kw: _Resp(200, b"<!doctype html><html>not found</html>"))
    assert fetch_url_image("https://shz/soft404.jpg", http=http) is None


def test_fetch_url_image_swallows_network_error():
    import requests

    def boom(url, kw):
        raise requests.ConnectionError("down")

    assert fetch_url_image("https://shz/x.jpg", http=_FakeHTTP(boom)) is None


def test_fetch_prefers_cover_art_archive():
    def handler(url, kw):
        if "coverartarchive.org" in url:
            return _Resp(200, b"\xff\xd8CAA-JPEG")
        raise AssertionError("should not fall through to iTunes when CAA has art")

    img = fetch_cover_art(
        artist="a-ha", title="Take On Me", release_ids=("rel-1",), http=_FakeHTTP(handler)
    )
    assert img == b"\xff\xd8CAA-JPEG"


def _itunes_hit(artist="a-ha"):
    return {"artistName": artist, "artworkUrl100": "https://x/a/100x100bb.jpg"}


def test_fetch_falls_back_to_itunes_when_caa_misses():
    def handler(url, kw):
        if "coverartarchive.org" in url:
            return _Resp(404, b"")
        if "itunes.apple.com/search" in url:
            return _Resp(200, json_data={"results": [_itunes_hit()]})
        if "1200x1200bb" in url:  # the upscaled artwork URL
            return _Resp(200, b"\xff\xd8ITUNES-JPEG")
        raise AssertionError(f"unexpected url {url}")

    http = _FakeHTTP(handler)
    img = fetch_cover_art(
        artist="a-ha", title="Take On Me", release_ids=("rel-1",), http=http
    )
    assert img == b"\xff\xd8ITUNES-JPEG"
    assert any("1200x1200bb" in u for u in http.urls)  # asked for the big one


def test_fetch_itunes_without_release_ids():
    # The common singleton case: no release MBID, so CAA is skipped entirely.
    def handler(url, kw):
        assert "coverartarchive" not in url
        if "search" in url:
            return _Resp(200, json_data={"results": [_itunes_hit()]})
        return _Resp(200, b"\xff\xd8ART")

    img = fetch_cover_art(artist="a-ha", title="Take On Me", http=_FakeHTTP(handler))
    assert img == b"\xff\xd8ART"


def test_fetch_skips_itunes_hit_for_wrong_artist():
    # A generic title can surface the wrong artist first; that cover must not be
    # used. Here the only hit is a different act -> no cover, not a wrong one.
    def handler(url, kw):
        if "coverartarchive" in url:
            return _Resp(404, b"")
        if "search" in url:
            return _Resp(200, json_data={"results": [_itunes_hit(artist="Coldplay")]})
        raise AssertionError("must not fetch art for a mismatched artist")

    img = fetch_cover_art(
        artist="a-ha", title="Take On Me", release_ids=("rel-1",), http=_FakeHTTP(handler)
    )
    assert img is None


def test_fetch_uses_next_hit_when_first_artist_mismatches():
    def handler(url, kw):
        if "coverartarchive" in url:
            return _Resp(404, b"")
        if "search" in url:
            return _Resp(200, json_data={"results": [
                _itunes_hit(artist="Someone Else"),
                _itunes_hit(artist="a-ha"),
            ]})
        return _Resp(200, b"\xff\xd8RIGHT-ART")

    img = fetch_cover_art(artist="a-ha", title="Take On Me", http=_FakeHTTP(handler))
    assert img == b"\xff\xd8RIGHT-ART"


def test_fetch_falls_back_to_thumbnail_when_upscale_fails():
    # If the 1200px variant won't fetch, use the original 100px URL rather than
    # coming away with nothing.
    def handler(url, kw):
        if "coverartarchive" in url:
            return _Resp(404, b"")
        if "search" in url:
            return _Resp(200, json_data={"results": [_itunes_hit()]})
        if "1200x1200bb" in url:
            return _Resp(500, b"")  # big variant fails
        return _Resp(200, b"\xff\xd8SMALL-ART")  # original 100px still serves

    img = fetch_cover_art(artist="a-ha", title="Take On Me", http=_FakeHTTP(handler))
    assert img == b"\xff\xd8SMALL-ART"


def test_fetch_caps_number_of_releases_tried():
    tried = []

    def handler(url, kw):
        if "coverartarchive" in url:
            tried.append(url)
            return _Resp(404, b"")
        if "search" in url:
            return _Resp(200, json_data={"results": []})
        return _Resp(404, b"")

    fetch_cover_art(
        artist="x", title="y",
        release_ids=tuple(f"rel-{i}" for i in range(20)),
        http=_FakeHTTP(handler),
    )
    # A few blocking GETs, not 20 — the cap preserves art recall (a later release may
    # carry the cover the first lacks) while stopping CAA from hammering the synchronous
    # import thread; the per-release timeout (T-216) bounds the slow tail, not this cap.
    assert len(tried) == _MAX_CAA_RELEASES


def test_fetch_bounds_the_per_read_timeout():
    # T-216: the default per-read timeout is the bounded value, so a slow CAA →
    # archive.org redirect can't stall the synchronous import thread for 10s/hop.
    seen = {}

    def handler(url, kw):
        seen["timeout"] = kw.get("timeout")
        return _Resp(404, b"")  # force the fetch to fall through; we only inspect the call

    fetch_cover_art(
        artist="x", title="y", release_ids=("rel-1",), http=_FakeHTTP(handler)
    )
    assert seen["timeout"] == 5


def test_fetch_returns_none_when_nothing_found():
    def handler(url, kw):
        if "coverartarchive" in url:
            return _Resp(404, b"")
        if "search" in url:
            return _Resp(200, json_data={"results": []})
        return _Resp(404, b"")

    img = fetch_cover_art(
        artist="x", title="y", release_ids=("rel-1",), http=_FakeHTTP(handler)
    )
    assert img is None


ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="ffmpeg required to synthesize test media"
)


@ffmpeg
def test_embed_cover_writes_apic_frame(tmp_path: Path):
    from beets import library
    from mutagen.id3 import ID3

    mp3 = tmp_path / "song.mp3"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
         "-b:a", "320k", str(mp3)],
        capture_output=True, check=True,
    )
    jpg = tmp_path / "cover.jpg"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=red:s=16x16:d=1",
         "-frames:v", "1", str(jpg)],
        capture_output=True, check=True,
    )

    item = library.Item.from_path(str(mp3))
    assert embed_cover(item, jpg.read_bytes(), log=logging.getLogger("test")) is True

    tags = ID3(str(mp3))
    assert any(k.startswith("APIC") for k in tags.keys())  # cover is on the file


@ffmpeg
def test_embed_cover_reports_false_for_invalid_image(tmp_path: Path):
    # beets silently declines unreadable/unsupported bytes — the receipt must not
    # claim a cover was written when none was.
    from beets import library
    from mutagen.id3 import ID3

    mp3 = tmp_path / "song.mp3"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
         "-b:a", "320k", str(mp3)],
        capture_output=True, check=True,
    )

    item = library.Item.from_path(str(mp3))
    assert embed_cover(item, b"not a real image", log=logging.getLogger("test")) is False
    assert not any(k.startswith("APIC") for k in ID3(str(mp3)).keys())
