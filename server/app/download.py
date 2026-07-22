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

# The classifier below keys off URL *shape* (path + query). Host matters in
# exactly one place: `youtu.be/<id>` carries the video id in the **path**, where
# every other YouTube host carries it in `?v=`. Both forms name one song, so both
# have to be recognised — see `_names_one_song`.
#
# What it does NOT do is refuse a song merely for carrying a `list=`. YouTube
# appends `&list=RD…` on its own when you play from Liked Videos or a search
# result, so the owner's everyday URL is `watch?v=SONG&list=RD…` — a URL that
# names exactly one song. Refusing those blocked the primary flow outright
# (first browser session, 2026-07-18) while protecting nothing: `download_song`
# passes `noplaylist=True`, so yt-dlp fetches the single named song regardless.
# Verified live against a radio URL — one line out, the named track. Spec §3 asks
# us not to *expand* a playlist into many songs; that guarantee lives in
# `noplaylist`, not here.


class PlaylistURLError(ValueError):
    """Raised when a playlist/collection reaches a stage that accepts one song.

    Typed so callers can distinguish "this is a playlist, refuse it" from any
    other bad input. Two detection points raise it:
    - `reject_playlist_url` — pre-network, from the URL's *shape* (a `list=` with
      no song, a `/playlist` path). At the route, T-012 catches this and returns
      HTTP 422 (spec §6/§7).
    - `download_song` — post-resolution, belt-and-braces: if `extract_info` ever
      comes back *playlist-shaped* despite the route's `names_one_song` gate, this
      becomes an honest **download**-stage failure rather than a bogus path (T-027).
    """


# Path segments that introduce a single video id: `/shorts/<id>`, `/embed/<id>`,
# `/live/<id>`, legacy `/v/<id>`. On youtu.be the id is the first segment itself.
_VIDEO_PATH_PREFIXES = frozenset({"shorts", "embed", "live", "v"})

# Words that occupy an id's position without being one. `videoseries` is
# YouTube's own short/embed spelling of a playlist (`youtu.be/videoseries?list=`),
# so it must NOT be mistaken for a video id.
_NOT_A_VIDEO_ID = frozenset({"videoseries", "playlist"})


def normalize_url(url: str) -> str:
    """Return `url` stripped and carrying a scheme — the form everything downstream wants.

    A plain-text or mobile copy arrives scheme-less (`youtu.be/<id>?list=…`).
    Two separate things break on that, which is why this returns a *string* the
    caller passes on rather than only feeding the classifier:

    - `urlparse` puts the host in `path` and leaves `hostname` None, so the URL
      reads as "no song named" and gets refused.
    - yt-dlp matches its extractors on the raw string: none of the YouTube
      `_VALID_URL` patterns match without a scheme, so a scheme-less URL falls
      through to the **generic** extractor — which is not YoutubeIE and does not
      honour `noplaylist`. Verified 2026-07-19; this is why the normalised value
      must travel with the request instead of being discarded after the check.

    Callers must classify, store, and download the *returned* string.
    """
    stripped = url.strip()
    if urlparse(stripped).scheme:
        return stripped
    return "https://" + stripped.lstrip("/")


def _parse(url: str):
    """urlparse a URL that may have arrived scheme-less."""
    return urlparse(normalize_url(url))


def _names_one_song(parts, query: dict) -> bool:
    """True when the URL identifies exactly one video, whatever else it carries.

    Every spelling YouTube uses for a single video:
    - `?v=<id>` — the youtube.com hosts (www, m, music).
    - `youtu.be/<id>` — the short domain puts the id in the path.
    - `/shorts/<id>`, `/embed/<id>`, `/live/<id>`, `/v/<id>` — path forms.
    """
    if query.get("v"):
        return True

    segments = [s for s in parts.path.split("/") if s]
    if not segments:
        return False

    host = (parts.hostname or "").lower().removeprefix("www.")
    if host == "youtu.be":
        return segments[0].lower() not in _NOT_A_VIDEO_ID

    if len(segments) >= 2 and segments[0].lower() in _VIDEO_PATH_PREFIXES:
        return segments[1].lower() not in _NOT_A_VIDEO_ID

    return False


def is_playlist_url(url: str) -> bool:
    """Return True when `url` denotes a YouTube playlist rather than one song.

    Pure and network-free — decided from the URL's shape alone, so it is fully
    unit-testable and cheap enough to run on every `POST /api/jobs`. Rules:

    - a `/playlist` path (e.g. `youtube.com/playlist?list=Y`) → playlist.
    - no `list=` at all → song.
    - a `list=` **and** a named song (`?v=X`, or `youtu.be/X`) → song. The
      `list=` is YouTube's own autoplay/radio seed, not a request to batch;
      `noplaylist=True` in `download_song` holds the one-song line.
    - a `list=` and **no** song named → playlist; there is nothing to single out.

    We do **not** expand a playlist into its songs — that is R2 (spec §3).
    """
    parts = _parse(url)
    path = parts.path.rstrip("/").lower()

    # A `/playlist` endpoint is unambiguous regardless of query.
    if path.endswith("/playlist"):
        return True

    # No `list=` → nothing to disambiguate. parse_qs drops empty values by
    # default, so a stray `list=` with no id doesn't trip the gate.
    query = parse_qs(parts.query)
    if not query.get("list"):
        return False

    # A `list=` is present: it's a playlist only if no single song is named.
    return not _names_one_song(parts, query)


# The two list-id prefixes worth a note — an **allowlist**, deliberately, not an
# "everything but `RD`" denylist. YouTube auto-appends a `list=` for many playback
# contexts the owner did not curate: `RD…` radio/mix seeds, `LL` (Liked), `WL` (Watch
# Later), `UU`/`UC…` (a channel's uploads), `FL` (favourites). Noting any of those
# nags on routine playback. Only two ids mean "the owner opened a real collection":
# `PL…`, a user/creator playlist (his monthly lists), and `OLAK5uy_…`, YouTube's
# auto-generated *album*. Album is checked first — an `OLAK5uy_…` never starts `PL`,
# so the order is for clarity, not correctness.
_ALBUM_LIST_PREFIX = "OLAK5uy_"
_PLAYLIST_LIST_PREFIX = "PL"


def curated_list_kind(url: str) -> str | None:
    """Which kind of curated list a song URL rode in on, for T-026's note.

    - ``"album"``    — the song carried an `OLAK5uy_…` album playlist.
    - ``"playlist"`` — the song carried a `PL…` user/creator playlist.
    - ``None``       — everything else: a bare song, a playlist-only URL (no song to
      single out — refused upstream anyway), or a `list=` the owner did not curate
      (`RD…` radio, `LL`/`WL`/`UU`/`FL` auto-collections). Flagging those would nag on
      routine playback and break the owner's primary flow.

    The signal is *which word the card shows*: the pasted link named one song but also
    referenced a whole album/playlist, and only the one track was taken. Pure and
    network-free, like `is_playlist_url`. A wrong guess is only ever a cosmetic
    mis/absent note — never a blocked download — which is why an id-prefix check is
    safe here where a *refusal* on it would not be (T-026 decision).
    """
    parts = _parse(url)
    query = parse_qs(parts.query)
    list_ids = query.get("list")
    if not list_ids or not _names_one_song(parts, query):
        return None
    list_id = list_ids[0]
    if list_id.startswith(_ALBUM_LIST_PREFIX):
        return "album"
    if list_id.startswith(_PLAYLIST_LIST_PREFIX):
        return "playlist"
    return None


# The hosts CleanMuzik accepts — a YouTube-only tool (PRD "YouTube → Jellyfin").
# `endswith(".youtube.com")` covers www./m./music. and any subdomain without
# matching a look-alike like `evil-youtube.com` (the char before `youtube` there is
# `-`, not `.`); the bare apex and `youtu.be` are listed explicitly.
def _is_youtube_host(hostname: str | None) -> bool:
    host = (hostname or "").lower()
    return host in ("youtube.com", "youtu.be") or host.endswith(".youtube.com")


def names_one_song(url: str) -> bool:
    """True when `url` is a YouTube link naming exactly one song — the only shape
    the pipeline takes.

    The positive complement to `is_playlist_url`, and the route's admission gate:
    `create_job` rejects `not names_one_song(url)` with 422 so a non-song never
    starts a job. Two ways a URL fails it:

    - **Not YouTube.** R1 is a YouTube tool (PRD "YouTube → Jellyfin"), so a
      non-YouTube host is refused outright. This also closes the one hole a
      shape-only check left: a non-YouTube `?v=` URL reads as "one song" by shape
      but could expand to a collection inside yt-dlp — rejecting the host stops it
      at the door rather than after `extract_info(download=True)` has already pulled
      the whole thing (T-027).
    - **YouTube, but not one song.** A channel, an `@handle`, a search or a bare
      domain names no single video and carries no `list=`/`/playlist` for
      `is_playlist_url` to catch, so this is what refuses it.

    Network-free — decided from the URL's shape alone, like `is_playlist_url`.
    """
    parts = _parse(url)
    if not _is_youtube_host(parts.hostname):
        return False
    return _names_one_song(parts, parse_qs(parts.query))


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
    a tag fallback (learnings).

    **`noplaylist=True` is LOAD-BEARING — do not remove it as redundant.** It was
    once a second guard behind a classifier that refused every `list=` URL. Since
    2026-07-18 the classifier deliberately *accepts* a song that carries a
    `list=` (YouTube appends one on its own; refusing blocked the owner's primary
    flow), so this option is now the **sole** guarantee that a URL naming a song
    inside a playlist yields one file rather than the whole list.

    No transcode to MP3 happens here (that is T-005 / ADR-002): the returned file
    keeps its native container (typically `.webm`/`.m4a`), tags embedded.

    `staging_dir` is created if not supplied; the caller (T-012) owns cleanup.
    """
    # Normalise first, and download the normalised string: a scheme-less paste
    # never matches YoutubeIE's `_VALID_URL` and would silently fall through to
    # the generic extractor, where `noplaylist` below means nothing.
    url = normalize_url(url)
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
        # LOAD-BEARING, not a backup — see this function's docstring. Since the
        # classifier accepts a song carrying a `list=`, this is the ONLY thing
        # keeping such a URL to one file. Do not drop it as redundant.
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }

    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)

    # Belt-and-braces: a URL that resolves to a *collection* comes back
    # playlist-shaped — `_type` "playlist"/"multi_video", or a non-empty `entries` —
    # and carries no top-level `requested_downloads`. The route's `names_one_song`
    # gate now refuses every non-YouTube host and every non-single-song YouTube
    # shape, so nothing collection-shaped *should* reach here (T-027, C). If one
    # ever does, fail on the DOWNLOAD stage with a clear reason rather than fall
    # through to `prepare_filename` below, which returns a path for a file that was
    # never written and would surface two stages later as a mis-attributed transcode
    # `FileNotFoundError`. Test `entries` by truthiness, not key presence: a single
    # video can carry an empty `entries` and must not be mistaken for a collection.
    if info.get("_type") in ("playlist", "multi_video") or info.get("entries"):
        raise PlaylistURLError(
            f"URL resolved to a collection of tracks, not one song: {url}"
        )

    # After postprocessing, the authoritative final path is on each entry of
    # `requested_downloads`; `prepare_filename` is only the pre-postprocess guess.
    downloads = info.get("requested_downloads")
    if downloads:
        return Path(downloads[0]["filepath"])
    return Path(ydl.prepare_filename(info))
