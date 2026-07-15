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

import logging

import requests

from app.config import Settings, get_settings

logger = logging.getLogger("cleanmuzik")

# Jellyfin's "scan all libraries" endpoint. A full refresh (not a per-library
# one, which would need the library's item id) is the simplest correct call for a
# single small library, and it's what the spec means by "the Jellyfin scan API".
# Returns 204 No Content on success.
_REFRESH_PATH = "/Library/Refresh"
_SCAN_TIMEOUT = 10


class JellyfinScanError(Exception):
    """A genuine scan-stage failure — config was present but the call failed.

    Distinct from a *degraded* skip (missing config → `trigger_scan` returns False,
    no exception). See the module docstring for the full degrade-vs-raise contract;
    the caller turns this into a `track.error` with `stage="scan"`.
    """


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
