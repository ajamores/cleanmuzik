"""Unit tests for the playlist classifier (T-004).

The classifier is a **pure function** — no network, no yt-dlp — so it is fully
testable here. The actual `download_song` needs the network and a live YouTube
URL; it is verified by hand at integration, not in this suite.

Run from the `server/` directory: `./.venv/bin/pytest tests/test_download.py -v`
"""

from pathlib import Path

import pytest

from app.download import (
    PlaylistURLError,
    curated_list_kind,
    download_song,
    is_playlist_url,
    names_one_song,
    normalize_url,
    reject_playlist_url,
)

# (url, expected_is_playlist) — the acceptance matrix from the ticket, plus the
# host variants the classifier must handle (youtu.be, music.youtube.com).
CASES = [
    # Bare watch URL → song.
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", False),
    ("https://youtube.com/watch?v=dQw4w9WgXcQ", False),
    ("https://m.youtube.com/watch?v=dQw4w9WgXcQ", False),
    # watch?v=X&list=Y → SONG. `v=` names one track; the `list=` is YouTube's
    # own autoplay seed. Order of the params must not matter.
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL123", False),
    ("https://www.youtube.com/watch?list=PL123&v=dQw4w9WgXcQ", False),
    # /playlist?list=Y → playlist.
    ("https://www.youtube.com/playlist?list=PL123", True),
    ("https://music.youtube.com/playlist?list=OLAK5uy_abc", True),
    # youtu.be short link, bare → song.
    ("https://youtu.be/dQw4w9WgXcQ", False),
    # youtu.be carrying a list → SONG: the id is in the path, so one is named.
    ("https://youtu.be/dQw4w9WgXcQ?list=PL123", False),
    # music.youtube.com watch, bare → song; with a radio seed → still song.
    ("https://music.youtube.com/watch?v=dQw4w9WgXcQ", False),
    ("https://music.youtube.com/watch?v=dQw4w9WgXcQ&list=RDAMVM123", False),
    # Trailing slash on /playlist still classifies.
    ("https://www.youtube.com/playlist/?list=PL123", True),
    # Stray empty `list=` (no id) is not a playlist.
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=", False),
    # A `list=` with NO song named is a playlist — nothing to single out.
    ("https://www.youtube.com/watch?list=PL123", True),
    # --- Regressions from the first browser session (2026-07-18) ------------
    # Liked Videos / search-result radio URL: refused before the fix, and it is
    # the owner's primary way of getting a link. yt-dlp --no-playlist was
    # verified live to return only the named track for this exact URL.
    ("https://www.youtube.com/watch?v=Gkr8WH5cAtg&list=RDGkr8WH5cAtg&start_radio=1", False),
    # Share-sheet link with a tracking param — worked before, must keep working.
    ("https://youtu.be/Gkr8WH5cAtg?si=0aFi_UILiE7FA4Y6", False),
    # --- Path-form single-video URLs (code review, 2026-07-19) --------------
    # The id lives in the PATH, not `?v=`. Each names one song, so a `list=`
    # alongside it must not turn it into a playlist.
    ("https://www.youtube.com/shorts/dQw4w9WgXcQ", False),
    ("https://www.youtube.com/shorts/dQw4w9WgXcQ?list=RDdQw4w9WgXcQ", False),
    ("https://www.youtube.com/embed/dQw4w9WgXcQ?list=PL123", False),
    ("https://www.youtube.com/live/dQw4w9WgXcQ?list=PL123", False),
    ("https://www.youtube.com/v/dQw4w9WgXcQ?list=PL123", False),
    # `videoseries` sits where an id would but IS a playlist — YouTube's own
    # short spelling for one. Must stay refused.
    ("https://youtu.be/videoseries?list=PL123", True),
    ("https://www.youtube.com/embed/videoseries?list=PL123", True),
    # A bare path prefix with no id after it names nothing.
    ("https://www.youtube.com/shorts?list=PL123", True),
    # --- Scheme-less pastes (code review, 2026-07-19) -----------------------
    # urlparse puts the host in `path` and leaves `hostname` None without a
    # scheme, so these read as "no song named" until normalised.
    ("youtu.be/dQw4w9WgXcQ?list=RDdQw4w9WgXcQ", False),
    ("www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL123", False),
    ("youtube.com/playlist?list=PL123", True),
]


@pytest.mark.parametrize("url, expected", CASES)
def test_is_playlist_url(url: str, expected: bool) -> None:
    assert is_playlist_url(url) is expected


def test_reject_playlist_url_raises_on_playlist() -> None:
    with pytest.raises(PlaylistURLError):
        reject_playlist_url("https://www.youtube.com/playlist?list=PL123")


def test_reject_playlist_url_passes_a_song_carrying_a_list() -> None:
    # A song that merely sits in a playlist/radio is accepted: one track is
    # named, and noplaylist=True keeps the download to that track. This is the
    # owner's everyday URL shape (first browser session, 2026-07-18).
    assert reject_playlist_url("https://youtu.be/dQw4w9WgXcQ?list=PL123") is None
    assert reject_playlist_url("https://www.youtube.com/watch?v=abc&list=RDabc") is None


def test_reject_playlist_url_raises_when_no_song_is_named() -> None:
    # A `list=` with no `v=` has nothing to single out — still refused.
    with pytest.raises(PlaylistURLError):
        reject_playlist_url("https://www.youtube.com/watch?list=PL123")


def test_reject_playlist_url_passes_a_song() -> None:
    # Returns None (no raise) for a bare song URL.
    assert reject_playlist_url("https://youtu.be/dQw4w9WgXcQ") is None


def test_playlist_error_is_a_valueerror() -> None:
    # T-012 relies on the typed exception; keep the ValueError lineage stable.
    assert issubclass(PlaylistURLError, ValueError)


# --- T-026: the "your link was part of an album/playlist" note signal --------
# (url, expected_kind) — a kind is returned ONLY when the URL names ONE song AND
# rides an allowlisted curated id: `PL…` → "playlist", `OLAK5uy_…` → "album".
# Everything else is None: a bare song, a playlist-only URL (nothing to single out),
# and every auto-appended `list=` the owner didn't curate (`RD…` radio, `LL` Liked,
# `WL` Watch-Later, `UU` uploads, `FL` favourites).
_LIST_KIND_CASES = [
    # `PL…` user/creator playlist carrying a named song → "playlist".
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL123", "playlist"),
    ("https://www.youtube.com/watch?list=PL123&v=dQw4w9WgXcQ", "playlist"),  # order-independent
    ("https://youtu.be/dQw4w9WgXcQ?list=PLmonthlyJuly", "playlist"),  # song id in the path
    ("www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL123", "playlist"),  # scheme-less paste
    # `OLAK5uy_…` album playlist → "album".
    ("https://music.youtube.com/watch?v=TRACK1&list=OLAK5uy_album", "album"),
    # Auto-appended contexts the owner didn't curate → None (finding: no nag).
    ("https://music.youtube.com/watch?v=dQw4w9WgXcQ&list=RDAMVM123", None),  # radio
    ("https://www.youtube.com/watch?v=Gkr8WH5cAtg&list=RDGkr8WH5cAtg&start_radio=1", None),
    ("https://www.youtube.com/watch?v=abc&list=RDCLAK5uy_albumradio", None),  # album *radio* is RD*
    ("https://www.youtube.com/watch?v=abc&list=LLliked", None),  # Liked videos
    ("https://www.youtube.com/watch?v=abc&list=WL", None),  # Watch Later
    ("https://www.youtube.com/watch?v=abc&list=UUchannelUploads", None),  # channel uploads
    ("https://www.youtube.com/watch?v=abc&list=FLfavourites", None),  # favourites
    # No `list=` → bare song.
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", None),
    ("https://youtu.be/dQw4w9WgXcQ", None),
    # Empty `list=` (no id) → None.
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=", None),
    # Playlist-only URL (no song singled out) → refused upstream, no note here.
    ("https://www.youtube.com/watch?list=PL123", None),
    ("https://www.youtube.com/playlist?list=PL123", None),
    ("https://music.youtube.com/playlist?list=OLAK5uy_abc", None),
]


@pytest.mark.parametrize("url, expected", _LIST_KIND_CASES)
def test_curated_list_kind(url: str, expected: str | None) -> None:
    assert curated_list_kind(url) == expected


# --- Scheme-less pastes reach yt-dlp intact (re-review, 2026-07-19) ----------
# `_parse` normalised scheme-less URLs for the *classifier* and threw the result
# away, so the raw string still went to yt-dlp. These assert the string that is
# classified is the string that gets downloaded.

NORMALIZE_CASES = [
    # Scheme-less pastes gain one.
    ("youtu.be/dQw4w9WgXcQ?list=PL1", "https://youtu.be/dQw4w9WgXcQ?list=PL1"),
    ("www.youtube.com/watch?v=abc", "https://www.youtube.com/watch?v=abc"),
    # An existing scheme is left alone — including http, which we must not upgrade
    # silently (that would change what the user asked for).
    ("https://youtu.be/abc", "https://youtu.be/abc"),
    ("http://youtu.be/abc", "http://youtu.be/abc"),
    # Surrounding whitespace and a leading slash from a sloppy copy.
    ("  youtu.be/abc  ", "https://youtu.be/abc"),
    ("//youtu.be/abc", "https://youtu.be/abc"),
]


@pytest.mark.parametrize("raw,expected", NORMALIZE_CASES)
def test_normalize_url(raw: str, expected: str) -> None:
    assert normalize_url(raw) == expected


# --- T-027 (C): the front-door gate — a URL must name exactly one song --------
# `names_one_song` is the positive complement to `is_playlist_url`; the route
# rejects `not names_one_song(url)` so a channel/@handle/search URL never starts a
# job (else download_song would expand + download the whole collection). Every
# shape the owner actually pastes names one song; the non-single shapes do not.
_NAMES_ONE_SONG_CASES = [
    # Single-song shapes the owner pastes — all True (admitted).
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", True),
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL123", True),
    ("https://youtu.be/dQw4w9WgXcQ", True),
    ("https://youtu.be/dQw4w9WgXcQ?list=RDx", True),
    ("https://music.youtube.com/watch?v=dQw4w9WgXcQ", True),
    ("https://www.youtube.com/shorts/dQw4w9WgXcQ", True),
    ("https://www.youtube.com/embed/dQw4w9WgXcQ", True),
    ("www.youtube.com/watch?v=dQw4w9WgXcQ", True),  # scheme-less paste
    # Not one song — the new hole T-027 (C) closes. All False (refused).
    ("https://www.youtube.com/@someartist", False),  # channel handle
    ("https://www.youtube.com/channel/UCabcdefghijklmnopqrstuv", False),
    ("https://www.youtube.com/c/SomeArtist", False),
    ("https://www.youtube.com/user/SomeArtist", False),
    ("https://www.youtube.com/results?search_query=nines", False),
    ("https://www.youtube.com/", False),  # bare domain
    # Playlist-shaped too (is_playlist_url already refuses these, belt-and-braces).
    ("https://www.youtube.com/playlist?list=PL123", False),
    ("https://youtu.be/videoseries?list=PL123", False),
    # Non-YouTube hosts are refused outright — R1 is YouTube-only. This also closes
    # the `?v=`-on-any-host hole: a non-YouTube `?v=` reads as one song by shape but
    # could expand to a collection inside yt-dlp, so it must not be admitted.
    ("https://vimeo.com/watch?v=12345", False),
    ("https://soundcloud.com/artist/some-track", False),
    ("https://example.com/gallery?v=abc", False),
    # A look-alike host must NOT be mistaken for YouTube (the char before `youtube`
    # is `-`, not `.`, so it fails the `.youtube.com` suffix test).
    ("https://evil-youtube.com/watch?v=dQw4w9WgXcQ", False),
]


@pytest.mark.parametrize("url, expected", _NAMES_ONE_SONG_CASES)
def test_names_one_song(url: str, expected: bool) -> None:
    assert names_one_song(url) is expected


# --- T-027: download_song guards a playlist-shaped extract_info result --------
# `reject_playlist_url` + `noplaylist=True` make the shape unreachable for every
# YouTube `list=` URL (proven live, 2026-07-21). But a channel/`@handle` URL
# carries no `list=` and names no single video, so the classifier admits it and
# `extract_info` returns `_type: "playlist"` with `entries` and no
# `requested_downloads`. Without the guard, download_song falls to
# `prepare_filename(info)` — a path for a file never written — and the failure
# surfaces two stages later as a mis-attributed transcode `FileNotFoundError`.


class _FakeYDL:
    """Stands in for `YoutubeDL` so download_song's post-extract branch is testable
    without the network. Returns whatever `info` the test seeds."""

    _info: dict = {}

    def __init__(self, opts):  # opts unused; download_song builds them
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download):
        return self._info

    def prepare_filename(self, info):
        # The bogus fallback path the old code would have returned for a playlist.
        return f"{info.get('id', 'NA')}.NA"


def _fake_ydl_returning(info: dict):
    return type("_Seeded", (_FakeYDL,), {"_info": info})


def test_download_song_rejects_a_playlist_shaped_result(tmp_path, monkeypatch) -> None:
    # A channel URL is admitted by the classifier (no list=, no /playlist path)…
    channel = "https://www.youtube.com/@someartist"
    assert is_playlist_url(channel) is False
    # …and extract_info comes back playlist-shaped. Guard raises on DOWNLOAD.
    playlist_info = {"_type": "playlist", "id": "chan", "entries": [{"id": "a"}, {"id": "b"}]}
    monkeypatch.setattr("app.download.YoutubeDL", _fake_ydl_returning(playlist_info))
    with pytest.raises(PlaylistURLError):
        download_song(channel, tmp_path)


def test_download_song_allows_single_video_with_empty_entries(tmp_path, monkeypatch) -> None:
    # Review finding (T-027): the guard tests `entries` by TRUTHINESS, not key
    # presence — a real single video can carry an empty/None `entries` and must not
    # be failed as a collection.
    dest = tmp_path / "vid.webm"
    video_info = {
        "_type": "video",
        "id": "vid",
        "entries": None,  # present-but-empty — must NOT trip the collection guard
        "requested_downloads": [{"filepath": str(dest)}],
    }
    monkeypatch.setattr("app.download.YoutubeDL", _fake_ydl_returning(video_info))
    out, _signals = download_song("https://www.youtube.com/watch?v=dQw4w9WgXcQ", tmp_path)
    assert out == Path(dest)


def test_download_song_returns_path_for_a_single_video(tmp_path, monkeypatch) -> None:
    # The happy path must be untouched: a real single-video result still returns
    # its `requested_downloads` filepath, no raise. R1.5 (T-201) widened the return
    # to `(path, SourceSignals)`; the path half is unchanged.
    dest = tmp_path / "vid.webm"
    video_info = {
        "_type": "video",
        "id": "vid",
        "title": "Fleetwood Mac - Dreams",
        "requested_downloads": [{"filepath": str(dest)}],
    }
    monkeypatch.setattr("app.download.YoutubeDL", _fake_ydl_returning(video_info))
    out, signals = download_song("https://www.youtube.com/watch?v=dQw4w9WgXcQ", tmp_path)
    assert out == Path(dest)
    # The discarded `info` is now surfaced as sense 1 alongside the path.
    assert signals.video_id == "vid"
    assert (signals.yt_artist, signals.yt_title) == ("Fleetwood Mac", "Dreams")


def _claiming_extractors(url: str) -> list[str]:
    """IE_NAMEs that would claim `url`, in yt-dlp's own precedence order.

    Pure regex matching against each extractor's `_VALID_URL` — no network.
    """
    from yt_dlp import YoutubeDL

    with YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
        return [ie.IE_NAME for ie in ydl._ies.values() if ie.suitable(url)]


# Ids must be a real 11-character YouTube id: `_VALID_URL` enforces the length,
# so a short placeholder like `abc123` matches nothing and would make these
# tests pass for the wrong reason.
@pytest.mark.parametrize(
    "raw",
    [
        "youtu.be/dQw4w9WgXcQ?list=RDdQw4w9WgXcQ",
        "www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL123",
        "www.youtube.com/shorts/dQw4w9WgXcQ",
        "youtu.be/dQw4w9WgXcQ",
    ],
)
def test_normalized_url_reaches_a_youtube_extractor(raw: str) -> None:
    """The defect this whole block exists for.

    yt-dlp picks its extractor by regex over the raw string, and no YouTube
    `_VALID_URL` matches without a scheme — so before normalisation every
    scheme-less paste fell through to **generic**, which is not a YouTube
    extractor and does not honour `noplaylist`, the sole one-song guarantee.

    Which YouTube extractor claims it depends on shape (`youtube`,
    `youtube:tab` for a `watch?v=…&list=`, `YoutubeYtBe` for the short domain),
    so this asserts the family, not one class.
    """
    assert _claiming_extractors(raw) == ["generic"], (
        "test case is not scheme-less; it proves nothing"
    )

    claimed = _claiming_extractors(normalize_url(raw))
    assert any(ie.lower().startswith("youtube") for ie in claimed), claimed


# --- T-213: transient-403 re-extract retry -----------------------------------
# A 403 at the media-fetch step is a stale stream URL; retrying the SAME client
# replays it, so download_song re-extracts from a fresh YoutubeDL. Each attempt
# constructs a new client (matching the real fresh-extraction fix), so the fakes
# below count calls in a shared dict, not on the instance. `time.sleep` is stubbed
# so the backoff never actually delays the suite.
from yt_dlp.utils import DownloadError, ExtractorError  # noqa: E402 — beside their tests


def _counting_ydl(behaviour):
    """A YoutubeDL stand-in whose `extract_info` calls `behaviour(n)` on the nth
    (1-based) call across ALL instances — so a fresh client per retry is observable."""
    calls = {"n": 0}

    class _YDL:
        def __init__(self, opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def extract_info(self, url, download):
            calls["n"] += 1
            return behaviour(calls["n"])

        def prepare_filename(self, info):
            return f"{info.get('id', 'NA')}.NA"

    return _YDL, calls


def _ok_info(dest: Path) -> dict:
    return {
        "_type": "video",
        "id": "vid",
        "title": "Pa Salieu - Frontline",
        "requested_downloads": [{"filepath": str(dest)}],
    }


def test_download_song_retries_a_transient_403_then_succeeds(tmp_path, monkeypatch) -> None:
    # The T-213 case seen live twice: first extraction 403s, a fresh one succeeds.
    dest = tmp_path / "vid.webm"
    ok = _ok_info(dest)

    def behaviour(n):
        if n == 1:
            raise DownloadError("unable to download video data: HTTP Error 403: Forbidden")
        return ok

    ydl, calls = _counting_ydl(behaviour)
    monkeypatch.setattr("app.download.YoutubeDL", ydl)
    monkeypatch.setattr("app.download.time.sleep", lambda _s: None)  # no real backoff

    out, signals = download_song("https://youtu.be/IaQjlagBnG0", tmp_path)
    assert out == Path(dest)
    assert calls["n"] == 2  # failed once, re-extracted once, then succeeded
    assert signals.video_id == "vid"


def test_download_song_does_not_retry_a_non_403_error(tmp_path, monkeypatch) -> None:
    # A private/removed/geo link raises its own message — it must fail FAST, not spend
    # the retry budget re-extracting a link that will never resolve (ADR-002).
    def behaviour(_n):
        raise DownloadError("ERROR: Private video. Sign in if you've been granted access")

    ydl, calls = _counting_ydl(behaviour)
    monkeypatch.setattr("app.download.YoutubeDL", ydl)
    slept: list[float] = []
    monkeypatch.setattr("app.download.time.sleep", lambda s: slept.append(s))

    with pytest.raises(DownloadError):
        download_song("https://youtu.be/private1234", tmp_path)
    assert calls["n"] == 1  # one attempt, no retry
    assert slept == []  # never backed off


def test_download_song_gives_up_after_max_403_retries(tmp_path, monkeypatch) -> None:
    # A 403 that never clears must terminate — bounded retries, then propagate.
    def behaviour(_n):
        raise DownloadError("HTTP Error 403: Forbidden")

    ydl, calls = _counting_ydl(behaviour)
    monkeypatch.setattr("app.download.YoutubeDL", ydl)
    monkeypatch.setattr("app.download.time.sleep", lambda _s: None)

    with pytest.raises(DownloadError):
        download_song("https://youtu.be/flaky123456", tmp_path)
    assert calls["n"] == 3  # 1 initial + _MAX_403_RETRIES (2)


def test_download_song_does_not_retry_on_a_403_shaped_video_id(tmp_path, monkeypatch) -> None:
    # Match the HTTP-403 SIGNATURE, not a bare "403": an 11-char id can carry those
    # digits, and a dead-link message that merely contains them must still fail fast.
    def behaviour(_n):
        raise DownloadError("ERROR: [youtube] aB403cdEfGh: Video unavailable")

    ydl, calls = _counting_ydl(behaviour)
    monkeypatch.setattr("app.download.YoutubeDL", ydl)
    slept: list[float] = []
    monkeypatch.setattr("app.download.time.sleep", lambda s: slept.append(s))

    with pytest.raises(DownloadError):
        download_song("https://youtu.be/aB403cdEfGh", tmp_path)
    assert calls["n"] == 1  # not retried — the id's "403" is not an HTTP 403
    assert slept == []


def test_download_song_retries_a_403_raised_as_extractor_error(tmp_path, monkeypatch) -> None:
    # A 403 during EXTRACTION surfaces as ExtractorError, not DownloadError — both are
    # YoutubeDLError, and both must be recovered (T-213 review, finding #2).
    dest = tmp_path / "vid.webm"
    ok = _ok_info(dest)

    def behaviour(n):
        if n == 1:
            raise ExtractorError("unable to extract player response: HTTP Error 403: Forbidden")
        return ok

    ydl, calls = _counting_ydl(behaviour)
    monkeypatch.setattr("app.download.YoutubeDL", ydl)
    monkeypatch.setattr("app.download.time.sleep", lambda _s: None)

    out, _signals = download_song("https://youtu.be/IaQjlagBnG0", tmp_path)
    assert out == Path(dest)
    assert calls["n"] == 2  # ExtractorError 403 was retried, then succeeded
