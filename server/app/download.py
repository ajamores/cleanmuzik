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

import logging
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from yt_dlp import YoutubeDL
from yt_dlp.utils import YoutubeDLError

from app.source_signals import SourceSignals

logger = logging.getLogger("cleanmuzik")

# A 403 at the media-fetch step is almost always transient (T-213): YouTube handed
# back a stale/throttled stream URL baked into THIS extraction's player response, and
# yt-dlp's own HTTP retries reuse that same poisoned response — so only a *fresh*
# `extract_info` (a new player response, new stream URLs) recovers it. Seen twice in
# one single-user session; both self-healed on a manual re-paste, which is exactly the
# fresh extraction this now does automatically. Scoped to 403 so a genuine dead link
# (private/removed/geo) still fails fast per the one-failure rule (ADR-002).
_MAX_403_RETRIES = 2  # up to 3 attempts total
_403_BACKOFF_S = 1.5

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


def expandable_playlist_id(url: str) -> str | None:
    """The **curated** YouTube playlist/album id this URL can expand into, or `None` (R2, T-302).

    Curated means the same allowlist `curated_list_kind` trusts — a `PL…` user/creator
    playlist or an `OLAK5uy_…` auto-album. Both a `watch?v=X&list=PL…` and a bare
    `/playlist?list=PL…` yield the id (the `list=` param, wherever the song sits). Every
    other `list=` yields `None`:

    - an auto-appended `RD…`/`LL`/`WL`/`UU…`/`FL` radio/mix/library seed — expanding one
      is unbounded (a radio never ends) and is never what "expand the playlist" means;
    - a non-YouTube host — this is a YouTube-only tool (PRD), and only a YouTube list is
      ours to expand.

    Pure and network-free, like `is_playlist_url`. It is the single predicate the accept
    path (T-302) asks "can this be expanded, and into which playlist id?" — distinct from
    `is_playlist_url` (shape-only: would R1 have refused it) so the explicit-intent dial
    (ADR-029) can expand a `watch?v=X&list=PL…` that `is_playlist_url` calls one song.
    """
    parts = _parse(url)
    if not _is_youtube_host(parts.hostname):
        return None
    list_ids = parse_qs(parts.query).get("list")
    if not list_ids:
        return None
    list_id = list_ids[0]
    if list_id.startswith(_ALBUM_LIST_PREFIX) or list_id.startswith(_PLAYLIST_LIST_PREFIX):
        return list_id
    return None


@dataclass(frozen=True)
class PlaylistEntry:
    """One track in an expanded playlist — the fields T-302 enqueues a job from."""

    video_id: str  # the YouTube id, the batch dedup key recorded on the job (T-303)
    url: str        # a clean single-song `watch?v=<id>` URL the R1 pipeline downloads
    title: str      # the entry title (best-effort; "" if yt-dlp was silent)


@dataclass(frozen=True)
class ExpandedPlaylist:
    """A playlist flattened into its entries — the result of `expand_playlist` (T-302)."""

    youtube_playlist_id: str  # the create-or-reuse key for the `playlists` row (ADR-027)
    title: str                # derived from the YouTube playlist title (no user naming)
    entries: list[PlaylistEntry]


def expand_playlist(url: str) -> ExpandedPlaylist:
    """Flatten a curated YouTube playlist URL into its entries (R2, T-302). Network I/O.

    Uses yt-dlp's **flat** extraction (`extract_flat="in_playlist"`, `download=False`) —
    one metadata pull for the whole list, no per-entry resolution — so expanding a
    50-track playlist is a single cheap call, not 50. The heavy per-song download stays
    in `download_song`, driven off each enqueued job.

    Expands the **canonical** `/playlist?list=<id>` URL built from the curated id, not the
    pasted string: a `watch?v=X&list=PL…` paste would otherwise extract just video X, and
    the whole point of an explicit Playlist intent (ADR-029) is to take the list. Refuses
    a URL with no expandable (curated) list up front — the caller gates on
    `expandable_playlist_id` first, so this raise is a guard, not the routine path.

    Entries with no id (a deleted/private placeholder yt-dlp yields as `None` or an
    id-less dict) are dropped: they can't become a downloadable single-song URL and would
    only enqueue a job doomed to fail the download stage.
    """
    playlist_id = expandable_playlist_id(url)
    if playlist_id is None:
        raise PlaylistURLError(f"URL carries no expandable playlist: {url}")

    canonical = f"https://www.youtube.com/playlist?list={playlist_id}"
    ydl_opts = {
        "extract_flat": "in_playlist",
        "quiet": True,
        "no_warnings": True,
    }
    # Convert yt-dlp's failure (a private/deleted/region-blocked list, or a transient
    # network blip) into this module's typed PlaylistURLError, so the accept route can
    # answer with a clean error instead of a 500 (this call is synchronous in the request
    # path, unlike download_song which runs on the worker with per-job error handling).
    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(canonical, download=False)
    except YoutubeDLError as exc:
        raise PlaylistURLError(
            f"Could not expand playlist {playlist_id}: {exc}"
        ) from exc

    entries: list[PlaylistEntry] = []
    for raw in info.get("entries") or []:
        if not raw:
            continue
        video_id = str(raw.get("id") or "").strip()
        if not video_id:
            continue
        entries.append(
            PlaylistEntry(
                video_id=video_id,
                url=f"https://www.youtube.com/watch?v={video_id}",
                title=str(raw.get("title") or "").strip(),
            )
        )

    # Fall back to the id if yt-dlp gave no title, so the `playlists` row is never
    # named "" (the title is what the Jellyfin playlist and the batch card show).
    title = str(info.get("title") or "").strip() or playlist_id
    return ExpandedPlaylist(
        youtube_playlist_id=playlist_id, title=title, entries=entries
    )


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

    **Only the ad-hoc caller reaches this.** `run_pipeline` always passes its own
    staging dir, rooted at `Store.staging_root` — a job's audio must not land in the
    system temp, because a park keeps it there for days and the OS reaps it (T-106).
    """
    return Path(tempfile.mkdtemp(prefix="cleanmuzik-"))


def _is_transient_403(exc: BaseException) -> bool:
    """True when a yt-dlp error is the retryable HTTP-403 (T-213).

    yt-dlp gives no typed 403 — the status only reaches us inside the wrapped error
    string (`"unable to download video data: HTTP Error 403: Forbidden"`), so we match on
    it. Match the **HTTP-403 signature**, not a bare `"403"`: an 11-char YouTube id can
    contain those digits (`ERROR: [youtube] aB403cdEfGh: Video unavailable`), and matching
    that would retry a genuinely dead link — the opposite of the fail-fast a private /
    removed / geo-blocked video must get (ADR-002)."""
    low = str(exc).lower()
    return "http error 403" in low or "403: forbidden" in low or "403 forbidden" in low


def _clear_dir(directory: Path) -> None:
    """Remove leftover files in a staging dir before a re-download (T-213).

    A 403'd attempt can leave a `.part` (or a stale file); yt-dlp would otherwise resume
    or skip against it on the retry, defeating the fresh re-extraction. The dir holds only
    this one job's download (per-job staging), so clearing it flat is safe. Best-effort —
    a file we can't unlink is not worth failing an otherwise-recoverable download over."""
    for path in directory.glob("*"):
        try:
            if path.is_file():
                path.unlink()
        except OSError as exc:  # noqa: PERF203 — a rare, per-file best-effort cleanup
            logger.debug("could not clear %s before retry (%s)", path, exc)


def download_song(
    url: str, staging_dir: Path | None = None
) -> tuple[Path, SourceSignals]:
    """Download one YouTube **song** as bestaudio into staging; return `(path, signals)`.

    Refuses a playlist URL up front (`PlaylistURLError`). Downloads bestaudio and
    embeds the source metadata via the `FFmpegMetadata` postprocessor — the API
    equivalent of the CLI `--embed-metadata` — so beets has a non-empty query and
    a tag fallback (learnings).

    **Returns the yt-dlp `info` as `SourceSignals` alongside the path (R1.5, T-201).**
    That dict used to be discarded here; it is now sense 1 of the reconcile call — the
    YouTube claim — so `run_pipeline` threads the signals through to the import seam.
    Building them is pure and cannot fail the download (the file is already on disk).

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

    # A fresh YoutubeDL per attempt: retrying `extract_info` on the *same* client would
    # replay the poisoned player response, so each retry re-extracts from scratch (T-213).
    # `ydl` is used after the loop for `prepare_filename`, so it must outlive the `with` —
    # the successful attempt's client stays bound, as the original code already relied on.
    # We catch the base `YoutubeDLError` (a 403 can surface as `DownloadError` at media
    # fetch OR `ExtractorError` during extraction) but retry ONLY a transient 403; every
    # other error — a real dead/private/geo link — propagates on the first hit (ADR-002).
    info = None
    for attempt in range(_MAX_403_RETRIES + 1):
        # On a retry make the re-extraction genuinely fresh: bypass yt-dlp's on-disk
        # cache (stale extraction state) and clear any partial file the failed attempt
        # left, so the new player response's stream isn't resumed against an old `.part`.
        attempt_opts = ydl_opts
        if attempt > 0:
            attempt_opts = {**ydl_opts, "cachedir": False}
            _clear_dir(staging_dir)
        with YoutubeDL(attempt_opts) as ydl:
            try:
                info = ydl.extract_info(url, download=True)
                break
            except YoutubeDLError as exc:
                if attempt < _MAX_403_RETRIES and _is_transient_403(exc):
                    logger.warning(
                        "download 403 for %s (attempt %d/%d) — re-extracting after %.1fs: %s",
                        url,
                        attempt + 1,
                        _MAX_403_RETRIES + 1,
                        _403_BACKOFF_S,
                        exc,
                    )
                    time.sleep(_403_BACKOFF_S)
                    continue
                raise

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

    # Sense 1 (spec §2): the yt-dlp claim, surfaced from the same `info` dict rather
    # than discarded. Pure; built here (not in run_pipeline) so the signals ride the
    # authoritative post-`extract_info` dict, next to the path they describe.
    signals = SourceSignals.from_info(info)

    # After postprocessing, the authoritative final path is on each entry of
    # `requested_downloads`; `prepare_filename` is only the pre-postprocess guess.
    downloads = info.get("requested_downloads")
    if downloads:
        return Path(downloads[0]["filepath"]), signals
    return Path(ydl.prepare_filename(info)), signals
