"""Unit tests for the playlist classifier (T-004).

The classifier is a **pure function** — no network, no yt-dlp — so it is fully
testable here. The actual `download_song` needs the network and a live YouTube
URL; it is verified by hand at integration, not in this suite.

Run from the `server/` directory: `./.venv/bin/pytest tests/test_download.py -v`
"""

import pytest

from app.download import (
    PlaylistURLError,
    is_playlist_url,
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
