"""Unit tests for the playlist classifier (T-004).

The classifier is a **pure function** — no network, no yt-dlp — so it is fully
testable here. The actual `download_song` needs the network and a live YouTube
URL; it is verified by hand at integration, not in this suite.

Run from the `server/` directory: `./.venv/bin/pytest tests/test_download.py -v`
"""

import pytest

from app.download import PlaylistURLError, is_playlist_url, reject_playlist_url

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
