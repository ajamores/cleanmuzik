"""T-007 Door B tests — cover art fetch.

`fetch_cover_art` is tested against a fake HTTP client (no network): the source
order (Cover Art Archive first, iTunes fallback) and the "found nothing" path.
Cover *embedding* moved to the mutagen writer (T-223) — its round-trip lives in
`test_tagwriter.py`; beets' `embedart` helper (`embed_cover`) was retired in T-224.
"""

from app.artwork import (
    _MAX_CAA_RELEASES,
    crop_to_square,
    fetch_cover_art,
    fetch_url_image,
)


def _jpeg(width: int, height: int) -> bytes:
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (width, height), (10, 20, 30)).save(buf, format="JPEG")
    return buf.getvalue()


def test_crop_to_square_centre_crops_a_wide_thumbnail():
    from io import BytesIO

    from PIL import Image

    out = crop_to_square(_jpeg(480, 360))  # the 4:3 hqdefault shape
    assert Image.open(BytesIO(out)).size == (360, 360)


def test_crop_to_square_leaves_a_square_image_untouched():
    src = _jpeg(300, 300)
    assert crop_to_square(src) == src  # already square — returned byte-for-byte


def test_crop_to_square_falls_back_to_original_on_undecodable_bytes():
    junk = b"\xff\xd8not-a-real-jpeg"
    assert crop_to_square(junk) == junk  # never raises, never drops the cover


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
