"""Download stage — YouTube song → tagged bestaudio in staging (R1, T-004).

The first stage of the pipeline (spec §4). Two jobs:

1. `reject_playlist_url` / `is_playlist_url` — a **pure**, network-free classifier
   that says whether a URL is a playlist (many songs) or a single song. R1 takes
   exactly one song per run (spec §2/§3); a playlist is refused here, and T-012
   turns this same signal into the `POST /api/jobs` 422 (spec §6/§7).
2. `download_song` — pull **bestaudio** for one song URL into a staging dir with
   `--embed-metadata`, so the file carries the video's title/artist tags. A bare
   `-x` rip strips tags → beets runs an empty MusicBrainz query → HTTP 400
   (learnings). We do **not** transcode to MP3 here — that is T-005 / ADR-002.
   This stage only lands a tagged bestaudio file and returns its path for T-005.

Staging cleanup on failure is T-012's job; this module only creates the dir.
"""

import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from yt_dlp import YoutubeDL

# The classifier below keys off URL *shape* (path + query), not host: YouTube's
# playlist grammar (`/playlist`, `list=`) is identical across youtube.com,
# music.youtube.com, and the youtu.be short domain, so the host adds no signal.
# R1's input is a YouTube song URL by contract (spec §3), which makes shape alone
# a sufficient — and honest — test.


class PlaylistURLError(ValueError):
    """Raised when a playlist URL reaches a stage that only accepts one song.

    Typed so callers can distinguish "this is a playlist, refuse it" from any
    other bad input. T-012 catches this and returns HTTP 422 (spec §6/§7).
    """


def is_playlist_url(url: str) -> bool:
    """Return True when `url` denotes a YouTube playlist rather than one song.

    Pure and network-free — decided from the URL's shape alone, so it is fully
    unit-testable and cheap enough to run on every `POST /api/jobs`. Rules:

    - a `/playlist` path (e.g. `youtube.com/playlist?list=Y`) → playlist.
    - **any** `list=` query parameter → playlist. This is deliberately broad:
      `watch?v=X&list=Y` and `youtu.be/X?list=Y` are "a song *in* a playlist",
      and R1 refuses them rather than guess which one track was meant.
    - a bare `watch?v=X` / `youtu.be/X` (no `list=`) → song.

    We do **not** expand a playlist into its songs — that is R2 (spec §3).
    """
    parts = urlparse(url)
    path = parts.path.rstrip("/").lower()

    # A `/playlist` endpoint is unambiguous regardless of query.
    if path.endswith("/playlist"):
        return True

    # Otherwise the tell is a `list=` parameter with a non-empty value. Using
    # parse_qs (which drops empty values by default) means a stray `list=` with
    # no id doesn't trip the gate.
    query = parse_qs(parts.query)
    return bool(query.get("list"))


def reject_playlist_url(url: str) -> None:
    """Raise `PlaylistURLError` if `url` is a playlist; return None otherwise.

    The guard the download stage runs before touching the network, and the exact
    check T-012 will reuse to reject a playlist `POST /api/jobs` with 422.
    """
    if is_playlist_url(url):
        raise PlaylistURLError(
            f"Playlist URLs are not supported in R1 (one song per run): {url}"
        )


def _make_staging_dir() -> Path:
    """Create and return a fresh, isolated staging directory.

    One unique dir per download keeps concurrent-safe naming trivial and gives
    T-012 a single directory to remove on cleanup. Lives under the system temp
    root, prefixed so it's identifiable.
    """
    return Path(tempfile.mkdtemp(prefix="cleanmuzik-"))


def download_song(url: str, staging_dir: Path | None = None) -> Path:
    """Download one YouTube **song** as bestaudio into staging; return the path.

    Refuses a playlist URL up front (`PlaylistURLError`). Downloads bestaudio and
    embeds the source metadata via the `FFmpegMetadata` postprocessor — the API
    equivalent of the CLI `--embed-metadata` — so beets has a non-empty query and
    a tag fallback (learnings). `noplaylist=True` is a second belt-and-braces
    guard so a URL that slipped past the classifier still yields a single file.

    No transcode to MP3 happens here (that is T-005 / ADR-002): the returned file
    keeps its native container (typically `.webm`/`.m4a`), tags embedded.

    `staging_dir` is created if not supplied; the caller (T-012) owns cleanup.
    """
    reject_playlist_url(url)

    if staging_dir is None:
        staging_dir = _make_staging_dir()
    else:
        staging_dir.mkdir(parents=True, exist_ok=True)

    ydl_opts = {
        "format": "bestaudio/best",
        # `%(id)s` gives a stable, filesystem-safe name; the ext is filled by the
        # chosen stream so we don't have to guess the container.
        "outtmpl": str(staging_dir / "%(id)s.%(ext)s"),
        # --embed-metadata: write the source title/artist/etc. into the file so a
        # weak/absent MusicBrainz match still has tags to fall back on (learnings).
        "postprocessors": [{"key": "FFmpegMetadata", "add_metadata": True}],
        # Never expand a playlist even if one reaches here — R1 is one song.
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }

    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)

    # After postprocessing, the authoritative final path is on each entry of
    # `requested_downloads`; `prepare_filename` is only the pre-postprocess guess.
    downloads = info.get("requested_downloads")
    if downloads:
        return Path(downloads[0]["filepath"])
    return Path(ydl.prepare_filename(info))
