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
    # watch?v=X&list=Y → playlist (a song *in* a playlist; R1 refuses it).
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL123", True),
    ("https://www.youtube.com/watch?list=PL123&v=dQw4w9WgXcQ", True),
    # /playlist?list=Y → playlist.
    ("https://www.youtube.com/playlist?list=PL123", True),
    ("https://music.youtube.com/playlist?list=OLAK5uy_abc", True),
    # youtu.be short link, bare → song.
    ("https://youtu.be/dQw4w9WgXcQ", False),
    # youtu.be short link carrying a list → playlist.
    ("https://youtu.be/dQw4w9WgXcQ?list=PL123", True),
    # music.youtube.com watch, bare → song; with list → playlist.
    ("https://music.youtube.com/watch?v=dQw4w9WgXcQ", False),
    ("https://music.youtube.com/watch?v=dQw4w9WgXcQ&list=RDAMVM123", True),
    # Trailing slash on /playlist still classifies.
    ("https://www.youtube.com/playlist/?list=PL123", True),
    # Stray empty `list=` (no id) is not a playlist.
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=", False),
]


@pytest.mark.parametrize("url, expected", CASES)
def test_is_playlist_url(url: str, expected: bool) -> None:
    assert is_playlist_url(url) is expected


def test_reject_playlist_url_raises_on_playlist() -> None:
    with pytest.raises(PlaylistURLError):
        reject_playlist_url("https://www.youtube.com/playlist?list=PL123")


def test_reject_playlist_url_raises_on_song_in_playlist() -> None:
    with pytest.raises(PlaylistURLError):
        reject_playlist_url("https://youtu.be/dQw4w9WgXcQ?list=PL123")


def test_reject_playlist_url_passes_a_song() -> None:
    # Returns None (no raise) for a bare song URL.
    assert reject_playlist_url("https://youtu.be/dQw4w9WgXcQ") is None


def test_playlist_error_is_a_valueerror() -> None:
    # T-012 relies on the typed exception; keep the ValueError lineage stable.
    assert issubclass(PlaylistURLError, ValueError)
