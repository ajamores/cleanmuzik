"""Jellyfin library-scan trigger — the last stage of a land (T-010, spec §5/§6).

beets copies the tagged MP3 into the watched folder (ADR-008), but Jellyfin only
notices new files on a library scan. Its default scan interval is long, so without
a nudge a freshly-landed track wouldn't appear for the owner until much later. This
module is that nudge: after a track lands, POST the Jellyfin *scan* API so the file
shows up within seconds — no manual "Scan Library" click.

## The two failure modes are NOT the same

- **Config absent** — no `JELLYFIN_API_KEY` (or `JELLYFIN_URL`). This is the
  "absent is not a failure" contract (spec §6): the track already landed on disk,
  so we log a warning and return `False`. It is emphatically NOT a `track.error`;
  the owner just triggers a scan themselves, or Jellyfin picks it up on its own
  schedule.
- **Config present but the call fails** — a network error, a 401 from a stale key,
  a 5xx. That IS a genuine `scan`-stage failure: `trigger_scan` raises
  `JellyfinScanError` so the caller (T-012) can emit `track.error` with
  `stage="scan"` (spec §6 event catalogue). The track still landed — the scan just
  didn't fire — but unlike a missing key this is a misconfiguration worth surfacing.

`http` is injectable so tests exercise both paths without a live Jellyfin.
"""

import enum
import logging
from dataclasses import dataclass

import requests

from app.config import Settings, get_settings

logger = logging.getLogger("cleanmuzik")

# Jellyfin's "scan all libraries" endpoint. A full refresh (not a per-library
# one, which would need the library's item id) is the simplest correct call for a
# single small library, and it's what the spec means by "the Jellyfin scan API".
# Returns 204 No Content on success.
_REFRESH_PATH = "/Library/Refresh"
_SCAN_TIMEOUT = 10

# Jellyfin's create-playlist endpoint (R2, T-302). `POST /Playlists` with a
# `CreatePlaylistDto` body returns `{ "Id": "<playlist id>" }`. We create it empty
# (`Ids: []`) at batch expansion and append the landed items later (T-304). MediaType
# "Audio" scopes it to the music library. Bounded like the scan.
_PLAYLISTS_PATH = "/Playlists"
_CREATE_TIMEOUT = 10

# Item lookup + playlist append (R2, T-304). Jellyfin references a track by an internal
# item id it assigns only *after* it indexes the landed file (async), so `resolve_item_id`
# finds that id by the file's canonical path and `append_to_playlist` adds it. Both are
# bounded like the scan/create. The `Path` filter on `/Items` is the one live-Jellyfin
# detail T-311 verifies against a real server; the seam is a single function so that
# verification touches nothing else.
_ITEMS_PATH = "/Items"
_RESOLVE_TIMEOUT = 10
_APPEND_TIMEOUT = 10

# Jellyfin user lookup (R2, T-311). Playlists belong to a user account, so create / append /
# read-back all require a `userId` — and this single-user tool ships without one configured.
# Rather than add a setting the owner must fill in, we discover it: GET /Users with the API
# key, take the admin (else first) user. Proven against the live server: every playlist op
# 400s without it and 200/204s with it (T-311 spike, 2026-08-17).
_USERS_PATH = "/Users"
_USERS_TIMEOUT = 10
# Pre-check GET of a playlist's current members (R2, T-313's idempotent append). Reading
# `GET /Playlists/{id}/Items` before every POST closes the crash-between-POST-and-stamp
# window: append only an item the playlist doesn't already hold. Bounded like the rest.
_PRECHECK_TIMEOUT = 10


class JellyfinAppendError(Exception):
    """A present-but-failed Jellyfin playlist append (network error, 401, 5xx).

    Distinct from a degraded skip (config absent → `append_to_playlist` returns False).
    The reconcile pass catches this *per member* and leaves the row pending for a later
    retry, so one failed append never stops the batch (ADR-003).
    """


class JellyfinScanError(Exception):
    """A genuine scan-stage failure — config was present but the call failed.

    Distinct from a *degraded* skip (missing config → `trigger_scan` returns False,
    no exception). See the module docstring for the full degrade-vs-raise contract;
    the caller turns this into a `track.error` with `stage="scan"`.
    """


class ResolveStatus(enum.Enum):
    """The three outcomes of resolving a landed file to its Jellyfin item (T-313).

    T-304 collapsed all of these into a bare `None`, which is the root of two of its three
    shipped bugs: "not indexed yet" (wait, keep retrying) and "Jellyfin is unreachable"
    (an outage — do NOT spend any give-up budget, defer untouched) are *different* and must
    be told apart. The reconcile pass branches on this:
      - RESOLVED     — a real item id; append it.
      - NOT_INDEXED  — Jellyfin answered, but the file isn't in its index yet. Keep the row
                       pending; flag it stuck once it has waited past the wall-clock ceiling.
      - UNREACHABLE  — Jellyfin errored, was absent, or returned a malformed body. Defer with
                       no state change and no stuck flag — an outage must strand nothing.
    """

    RESOLVED = "resolved"
    NOT_INDEXED = "not_indexed"
    UNREACHABLE = "unreachable"


@dataclass(frozen=True)
class ResolveResult:
    """The outcome of `resolve_item_id`: a status and, iff RESOLVED, a non-empty item id.

    The invariant is load-bearing (T-313, repair 2): `item_id` is a non-empty `str` **iff**
    `status is RESOLVED`. `__post_init__` enforces it, so a `ResolveResult(RESOLVED, None)` is
    unconstructible — a malformed 2xx (a 200 with no usable Id) can never masquerade as a
    resolved item, POST `Ids=None`, 400, and re-enter the retry burn that was T-304's bug 3.
    """

    status: ResolveStatus
    item_id: str | None = None

    def __post_init__(self) -> None:
        resolved = self.status is ResolveStatus.RESOLVED
        has_id = isinstance(self.item_id, str) and bool(self.item_id)
        if resolved != has_id:
            raise ValueError(
                f"ResolveResult invariant violated: status={self.status} item_id={self.item_id!r} "
                "(a non-empty item_id iff RESOLVED)"
            )


def trigger_scan(
    *,
    settings: Settings | None = None,
    timeout: int = _SCAN_TIMEOUT,
    http=requests,
) -> bool:
    """Ask Jellyfin to scan its libraries so a just-landed track appears at once.

    Returns True if the scan was requested, False if it was skipped because the
    Jellyfin config is absent (the "absent is not a failure" contract — the track
    still landed). Raises `JellyfinScanError` if the config was present but the
    call failed, so the caller can name the `scan` stage in a `track.error`.
    """
    s = settings or get_settings()
    # strip() so a whitespace-only value in .env (a stray space, a blank line the
    # owner didn't notice) counts as absent → degrade, rather than a "present"
    # config that POSTs a bogus token and 401s on every landed track.
    url = s.jellyfin_url.strip().rstrip("/")
    key = s.jellyfin_api_key.strip()

    if not (url and key):
        # Missing URL or key: degrade, don't fail (spec §6). The track has already
        # landed; Jellyfin will find it on its own schedule or a manual scan. Name
        # every unset var — with both absent, reporting only one sends the owner on
        # a second round of confusion after they fix the first.
        missing = ", ".join(
            name
            for name, value in (("JELLYFIN_URL", url), ("JELLYFIN_API_KEY", key))
            if not value
        )
        logger.warning(
            "Jellyfin scan skipped — %s not set; track landed on disk, "
            "it will appear on Jellyfin's next scan",
            missing,
        )
        return False

    endpoint = f"{url}{_REFRESH_PATH}"
    try:
        # X-Emby-Token is Jellyfin's simple API-key auth header (equivalent to the
        # MediaBrowser Authorization scheme, no client fields required).
        resp = http.post(
            endpoint,
            headers={"X-Emby-Token": key},
            timeout=timeout,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        # Network down, timeout, or a non-2xx (bad/expired key → 401). A present
        # config that can't complete IS a scan-stage failure — surface it.
        raise JellyfinScanError(f"Jellyfin scan request to {endpoint} failed: {exc}") from exc

    logger.info("Jellyfin library scan triggered (%s)", endpoint)
    return True


# Cache of the resolved user id, keyed by (url, key), so a batch's N appends don't each
# re-hit GET /Users. The id is stable for the life of the server config; the cache is process-
# scoped and cleared explicitly by tests (`_clear_user_id_cache`). A single-user tool never
# invalidates it in production.
_user_id_cache: dict[tuple[str, str], str] = {}


def _clear_user_id_cache() -> None:
    """Drop the memoised user id — for tests, so each exercises a fresh lookup."""
    _user_id_cache.clear()


def resolve_user_id(
    *,
    settings: Settings | None = None,
    timeout: int = _USERS_TIMEOUT,
    http=requests,
) -> str | None:
    """The Jellyfin user id every playlist op must be scoped to, or `None` if unavailable (T-311).

    Jellyfin playlists belong to a user account, so create / append / read-back all require a
    `userId` — and this tool ships without one configured (single-user). Rather than add a
    setting the owner must fill in (owner-chosen 2026-08-17), we discover it: `GET /Users` with
    the API key, take the **admin** user (else the first) with a non-empty string `Id`. Cached
    per (url, key) so a batch's many appends don't each re-hit `/Users`.

    Degrades to `None` — never raises — on absent config or any failure (network, non-2xx,
    non-JSON, empty/odd body), exactly like the other seams. The caller treats `None` as "can't
    scope the op" and degrades/defers accordingly (create → NULL id; append → left pending;
    pre-check → defer the playlist). The ADR-027 seam-1 amendment poll contract is unchanged.
    """
    s = settings or get_settings()
    url = s.jellyfin_url.strip().rstrip("/")
    key = s.jellyfin_api_key.strip()
    if not (url and key):
        return None
    cache_key = (url, key)
    cached = _user_id_cache.get(cache_key)
    if cached:
        return cached
    try:
        resp = http.get(
            f"{url}{_USERS_PATH}", headers={"X-Emby-Token": key}, timeout=timeout
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Jellyfin user lookup failed (%s%s): %s", url, _USERS_PATH, exc)
        return None
    if not isinstance(data, list) or not data:
        return None
    users = [u for u in data if isinstance(u, dict)]
    admins = [u for u in users if (u.get("Policy") or {}).get("IsAdministrator")]
    for u in admins + users:  # prefer an admin, fall back to the first valid user
        uid = u.get("Id")
        if isinstance(uid, str) and uid:
            _user_id_cache[cache_key] = uid
            return uid
    return None


def create_playlist(
    name: str,
    *,
    settings: Settings | None = None,
    timeout: int = _CREATE_TIMEOUT,
    http=requests,
) -> str | None:
    """Create an empty Jellyfin playlist by `name`; return its id, or `None` if it couldn't.

    Called at batch expansion (create-at-queued, ADR-027 seam 3), off the sequential
    worker, so an all-parked batch still gets a `jellyfin_playlist_id` for T-306 to
    backfill against.

    **Degrades to `None` — never raises — on BOTH failure modes** (owner-settled
    2026-08-16, ADR-027 seam-3 addendum), *deliberately unlike* `trigger_scan`:

    - **Config absent** — no `JELLYFIN_URL`/`JELLYFIN_API_KEY`. Same "absent is not a
      failure" contract as the scan.
    - **Config present but the POST fails** — a network error, a 401, a 5xx, or a body
      with no `Id`. `trigger_scan` *raises* here because a scan failure is a nameable
      *per-track* `scan` stage; a create failure instead gates **all N enqueues** of the
      batch, and refusing a 50-track paste over one transient Jellyfin blip is
      disproportionate. So we warn and return `None`: the batch still upserts, expands,
      enqueues, and lands canonically on disk; `jellyfin_playlist_id` stays NULL and the
      T-306 create-if-missing guard backfills it.

    The warning is load-bearing — a NULL id must never be silent (a Jellyfin-less or
    -flaky run should be visible in the log, not a mystery empty playlist later).
    """
    s = settings or get_settings()
    url = s.jellyfin_url.strip().rstrip("/")
    key = s.jellyfin_api_key.strip()

    if not (url and key):
        missing = ", ".join(
            varname
            for varname, value in (("JELLYFIN_URL", url), ("JELLYFIN_API_KEY", key))
            if not value
        )
        logger.warning(
            "Jellyfin playlist create skipped — %s not set; the batch still expands and "
            "lands, with a NULL jellyfin_playlist_id (backfilled on a later scan)",
            missing,
        )
        return None

    # A playlist belongs to a user (T-311): POST /Playlists 400s without a UserId. Resolve it
    # (cached); if we can't, degrade to None like any other create failure — the batch still
    # expands and lands, jellyfin_playlist_id stays NULL, and T-306 backfills on a later pass.
    user_id = resolve_user_id(settings=s, http=http)
    if not user_id:
        logger.warning(
            "Jellyfin playlist create skipped — could not resolve a user id (GET /Users) to "
            "own the playlist; NULL jellyfin_playlist_id (backfilled on a later scan)",
        )
        return None

    endpoint = f"{url}{_PLAYLISTS_PATH}"
    try:
        resp = http.post(
            endpoint,
            headers={"X-Emby-Token": key},
            json={"Name": name, "Ids": [], "MediaType": "Audio", "UserId": user_id},
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        # ValueError covers a 2xx with a non-JSON body (requests' JSONDecodeError is a
        # ValueError). Degrade, don't raise — see the docstring's whole-batch rationale.
        logger.warning(
            "Jellyfin playlist create failed (%s): %s — the batch still expands and "
            "lands, with a NULL jellyfin_playlist_id (backfilled on a later scan)",
            endpoint,
            exc,
        )
        return None

    # Guard the body shape too: a proxy or odd Jellyfin build can answer 2xx with a JSON
    # *list* (or null), on which `.get` would AttributeError — an uncaught raise that would
    # abort all N enqueues, the one thing this function's contract forbids. Anything not a
    # dict-with-an-Id is treated as a failed create → degrade to None.
    playlist_id = data.get("Id") if isinstance(data, dict) else None
    if not playlist_id:
        logger.warning(
            "Jellyfin playlist create returned no Id (%s) — NULL jellyfin_playlist_id "
            "(backfilled on a later scan)",
            endpoint,
        )
        return None

    logger.info("Jellyfin playlist created: %r (%s)", name, playlist_id)
    return playlist_id


def resolve_item_id(
    path: str,
    *,
    settings: Settings | None = None,
    timeout: int = _RESOLVE_TIMEOUT,
    http=requests,
) -> ResolveResult:
    """Resolve a landed file's canonical `path` to its Jellyfin item, as a 3-state result.

    A **single, non-blocking attempt** — never a poll-until-timeout loop. The retry is the
    reconcile pass calling this again on a later tick (ADR-027 seam-1 amendment, T-304): a
    just-landed file's own index is the least-settled thing in the system, so we never sit
    and wait for it on the worker; we defer and let a *later* pass resolve it once Jellyfin
    has indexed it.

    Returns a `ResolveResult` distinguishing the three outcomes T-304 wrongly collapsed to
    `None` (T-313, repair 2 — this split is what kills the outage-strands-everything bug on
    the resolve path):
      - RESOLVED(id)  — the one audio item whose `Path` equals this file's path.
      - NOT_INDEXED   — Jellyfin answered cleanly but has no audio item at this path yet (or
                        config absent → nothing to resolve against). Keep waiting.
      - UNREACHABLE   — a network error / non-2xx / non-JSON / malformed body (a match whose
                        `Id` isn't a usable string). An outage or a broken edge: the caller
                        defers with no state change and spends no budget.

    **Exact-path match, client-side (T-311).** The live Jellyfin **ignores** the `Items?Path=`
    filter — it returns the whole recursive library, so T-304's `items[0]` was the library-root
    *folder*, not the track (proven wrong on first live contact, T-311 spike). So we list the
    audio items with their `Path` and match exactly ourselves. A landed file maps to one audio
    item; the library is single-user and small, so the full listing is cheap (a future
    optimisation could cache it per reconcile pass). A malformed 2xx must **never** become
    RESOLVED(None) — `ResolveResult`'s invariant makes that unconstructible.
    """
    s = settings or get_settings()
    url = s.jellyfin_url.strip().rstrip("/")
    key = s.jellyfin_api_key.strip()
    if not (url and key):
        # Absent config → nothing to resolve against, but this is not an *outage*: there is
        # no Jellyfin to be down. Treat it as NOT_INDEXED (the pass-level pre-check GET, which
        # also returns UNREACHABLE on absent config, defers the whole playlist before we ever
        # reach here). Quiet — the create already warned once for this batch.
        return ResolveResult(ResolveStatus.NOT_INDEXED)

    endpoint = f"{url}{_ITEMS_PATH}"
    try:
        resp = http.get(
            endpoint,
            headers={"X-Emby-Token": key},
            params={"IncludeItemTypes": "Audio", "Recursive": "true", "Fields": "Path"},
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        # Jellyfin was configured but did not answer cleanly — an outage or a stale key, NOT
        # "not indexed yet". UNREACHABLE so the caller defers without spending give-up budget.
        logger.warning("Jellyfin item resolve failed (%s) for %s: %s", endpoint, path, exc)
        return ResolveResult(ResolveStatus.UNREACHABLE)

    if not isinstance(data, dict):
        # A 2xx with a non-dict body is a broken edge, not an empty index → UNREACHABLE.
        return ResolveResult(ResolveStatus.UNREACHABLE)
    items = data.get("Items")
    if not isinstance(items, list):
        return ResolveResult(ResolveStatus.UNREACHABLE)  # malformed 2xx, not an empty index
    match = next(
        (it for it in items if isinstance(it, dict) and it.get("Path") == path), None
    )
    if match is None:
        return ResolveResult(ResolveStatus.NOT_INDEXED)  # answered, no audio item at this path yet
    item_id = match.get("Id")
    if not (isinstance(item_id, str) and item_id):
        # Matched the path but the Id is missing/non-string: a malformed 2xx. Never a resolved
        # item (RESOLVED(None) would POST Ids=None → 400 → re-burn) → UNREACHABLE.
        return ResolveResult(ResolveStatus.UNREACHABLE)
    return ResolveResult(ResolveStatus.RESOLVED, item_id)


def get_playlist_item_ids(
    playlist_id: str,
    *,
    settings: Settings | None = None,
    timeout: int = _PRECHECK_TIMEOUT,
    http=requests,
) -> set[str] | None:
    """The library item ids currently in a Jellyfin playlist, or `None` if unreadable (T-313).

    The pre-check half of the idempotent append (repair 3): the reconcile pass reads a
    playlist's current members **once per pass** and appends a resolved item only if it is
    absent from this set — closing the crash-between-POST-and-stamp window that let T-304
    double-add a track on the next pass.

    `GET /Playlists/{id}/Items?userId=<uid>` returns `{ "Items": [ { "Id": ... }, ... ] }`; we
    collect the **library item id** (`Id`), NOT the per-entry `PlaylistItemId` — the append
    POSTs library ids, so a set keyed on anything else would miss every time and defeat the
    check. The `userId` is required (T-311): without it the live server returns an empty/odd
    body, which read back as a bogus empty set and would let a duplicate append through.

    Returns:
      - a `set[str]` of item ids on success — **an empty set is a valid answer** (an empty
        playlist), distinct from a failure;
      - `None` on config absent, an unresolvable user id, a network error, a non-2xx, non-JSON,
        or a malformed body. The caller treats `None` as UNREACHABLE and defers the whole
        playlist this pass — it must **never** blind-append when it cannot first read what's
        already there.
    """
    s = settings or get_settings()
    url = s.jellyfin_url.strip().rstrip("/")
    key = s.jellyfin_api_key.strip()
    if not (url and key):
        return None  # absent config → can't read membership → defer (never blind-append)

    user_id = resolve_user_id(settings=s, http=http)
    if not user_id:
        return None  # can't scope the read → treat as unreadable → defer (never blind-append)

    endpoint = f"{url}{_PLAYLISTS_PATH}/{playlist_id}{_ITEMS_PATH}"
    try:
        resp = http.get(
            endpoint,
            headers={"X-Emby-Token": key},
            params={"userId": user_id},
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning(
            "Jellyfin playlist pre-check failed (%s) for playlist %s: %s",
            endpoint, playlist_id, exc,
        )
        return None

    if not isinstance(data, dict):
        return None
    items = data.get("Items")
    if items is None:
        return None  # a well-formed response always carries an Items array; its absence is broken
    if not isinstance(items, list):
        return None
    return {
        it["Id"]
        for it in items
        if isinstance(it, dict) and isinstance(it.get("Id"), str) and it["Id"]
    }


def append_to_playlist(
    playlist_id: str,
    item_id: str,
    *,
    settings: Settings | None = None,
    timeout: int = _APPEND_TIMEOUT,
    http=requests,
) -> bool:
    """Append one resolved item to a Jellyfin playlist. Returns True on success.

    `POST /Playlists/{playlistId}/Items?Ids=<itemId>&userId=<uid>` (204 No Content). The
    `userId` is required (T-311): the live server 400s the append without it. Returns False if
    the Jellyfin config is absent (degrade, not fail — the durable membership row already
    records the intent and the reconcile pass retries when Jellyfin returns). Raises
    `JellyfinAppendError` if the config was present but the call failed — INCLUDING an
    unresolvable user id (a `/Users` lookup that fails is a present-but-broken Jellyfin) — so
    the reconcile pass leaves the row pending, no penalty, and retries next pass (T-313).

    Idempotency is the caller's guarantee, not this call's: the reconcile pass pre-checks the
    playlist's current item ids (`get_playlist_item_ids`) and appends only an item that is
    absent, so a given (playlist, item) is POSTed exactly once even across a crash between the
    POST and its stamp (T-313, repair 3) — Jellyfin's own endpoint would happily double-add.
    """
    s = settings or get_settings()
    url = s.jellyfin_url.strip().rstrip("/")
    key = s.jellyfin_api_key.strip()
    if not (url and key):
        return False

    user_id = resolve_user_id(settings=s, http=http)
    if not user_id:
        # Config present but no user id → we can't scope the append. This is a
        # present-but-broken Jellyfin (the /Users lookup failed), not an absent one: raise so
        # the reconcile pass leaves the row pending and retries, rather than degrading to a
        # silent False that would look like "absent config" and never retry differently.
        raise JellyfinAppendError(
            f"Jellyfin append of {item_id} to playlist {playlist_id} failed: "
            "could not resolve a user id (GET /Users)"
        )

    endpoint = f"{url}{_PLAYLISTS_PATH}/{playlist_id}{_ITEMS_PATH}"
    try:
        resp = http.post(
            endpoint,
            headers={"X-Emby-Token": key},
            params={"Ids": item_id, "userId": user_id},
            timeout=timeout,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise JellyfinAppendError(
            f"Jellyfin append of {item_id} to playlist {playlist_id} failed: {exc}"
        ) from exc

    logger.info("Jellyfin playlist %s gained item %s", playlist_id, item_id)
    return True
