"""Direct-HTTP MusicBrainz client + the one shared rate limiter (T-226 step C).

Until T-226 the backend reached MusicBrainz two ways with two separate 1-req/s throttles:
beets' `mb_api` (its `LimiterTimeoutSession`, governing candidate hydration + the year
lookup + re-search) and `app/isrc.py`'s own monotonic gate (the ISRC lookup). Nothing
coordinated them, so within one track a beets call and the ISRC call could put two requests
to `musicbrainz.org` inside a second — the deferred T-210 correctness half.

This module is the direct-HTTP MusicBrainz surface (extending `isrc.py`'s proven
`requests`-based pattern) **and** the single home for the 1-req/s limiter both it and
`isrc.py` now share. beets' own limiter still governs whatever candidate hydration still
rides beets until that is retired (step D), at which point every MusicBrainz request in the
process funnels through `respect_rate_limit` here.

Honest accounting of the gate, mid-migration: there are still TWO uncoordinated gates (this
shared one + beets'), so a collision window remains — it has only MOVED. The year lookup
(`fetch_original_date`) used to ride beets' `mb_api`, coordinated 1/sec with the winner
hydration (`track_for_id`) but not with the ISRC lookup; it now rides THIS gate, coordinated
with the ISRC lookup but not with beets' hydration. A lateral move on the identity hot path,
not a net regression, and it closes entirely in step D when beets' gate is gone. The 26-track
spike ran both paths with no throttle and never tripped MB's limiter, so the live risk is low.

Raw MusicBrainz WS/2 JSON is returned as-is (hyphenated keys — `first-release-date`,
`release-group`, `date`); callers read the real MB shape rather than beets' underscored
re-mapping.
"""

from __future__ import annotations

import logging
import threading
import time
import urllib.parse

import requests

from app.config import MUSICBRAINZ_USER_AGENT

logger = logging.getLogger("cleanmuzik")

_RECORDING_URL = "https://musicbrainz.org/ws/2/recording/{mbid}"

# MusicBrainz's descriptive-UA requirement + 1-req/s cap (ADR-001). One home, so the whole
# process can't drift on either.
_UA = MUSICBRAINZ_USER_AGENT
_MIN_INTERVAL_S = 1.0
_TIMEOUT_S = 15

# One bounded retry on a transient failure, matching the ladder beets' mb_api carried
# (mb_retry total=1): MusicBrainz answers 503 under load — the T-226 live smoke hit one on
# the first attempt and the retry succeeded — so a single retry keeps a transient absorb
# without reintroducing beets' deep backoff tail (ADR-031). A retryable failure is a request
# exception or a 5xx/429; a 404 is a real answer and is NOT retried.
_MAX_ATTEMPTS = 2
_RETRY_BACKOFF_S = 1.0

# The ONE shared throttle state (was duplicated in isrc.py + beets). Guarded by the lock so
# a future non-serial caller can't race it. Tests reset `_last_request_monotonic` to None.
_rate_lock = threading.Lock()
_last_request_monotonic: float | None = None


def respect_rate_limit(clock_fn=time.monotonic, sleep_fn=time.sleep) -> None:
    """Block until at least `_MIN_INTERVAL_S` has passed since the last MusicBrainz request.

    The single limiter every direct MB call routes through (ADR-001). Injectable
    `clock_fn`/`sleep_fn` so tests assert the throttle without waiting a real second; the
    send time is recorded *after* any sleep so back-to-back calls space out by the interval
    rather than drifting.
    """
    global _last_request_monotonic
    with _rate_lock:
        now = clock_fn()
        if _last_request_monotonic is not None:
            wait = _MIN_INTERVAL_S - (now - _last_request_monotonic)
            if wait > 0:
                sleep_fn(wait)
                now = clock_fn()
        _last_request_monotonic = now


def parse_date(raw) -> tuple[int | None, int | None, int | None]:
    """A MusicBrainz date string (`YYYY`, `YYYY-MM`, or `YYYY-MM-DD`) → `(year, month, day)`.

    Replaces beets' `beetsplug.musicbrainz._get_date`. Missing components are `None`; an
    unparseable or empty value is all-`None`. Only the year needs to be an int for the
    caller's earliest-year comparison; month/day ride along for the fullest-date tiebreak.
    """
    if not raw or not isinstance(raw, str):
        return None, None, None
    parts = raw.split("-")
    out: list[int | None] = []
    for part in parts[:3]:
        try:
            out.append(int(part))
        except (ValueError, TypeError):
            out.append(None)
    while len(out) < 3:
        out.append(None)
    year, month, day = out
    return (year if year else None), month, day


def get_recording(
    mbid: str | None,
    *,
    includes: list[str] | None = None,
    http=requests,
    user_agent: str = _UA,
    timeout: int = _TIMEOUT_S,
    clock_fn=time.monotonic,
    sleep_fn=time.sleep,
) -> dict | None:
    """One MusicBrainz recording lookup by MBID → the raw WS/2 JSON dict, or `None`.

    Direct HTTP (no beets), fail-soft like `isrc_to_mb`: an empty id, a non-retryable non-200
    (e.g. 404), a persistent request failure, or an unparseable body all return `None`. One
    bounded retry absorbs a transient 5xx/429/exception (parity with beets' retired ladder);
    every attempt honours the shared 1-req/s limiter. `includes` become the `inc` param
    (space-joined, as MB expects). `http`/`clock_fn`/`sleep_fn` are injectable so the suite
    runs offline with no real sleep.
    """
    if not mbid or not str(mbid).strip():
        return None
    mbid = str(mbid).strip()

    params = {"fmt": "json"}
    if includes:
        params["inc"] = " ".join(includes)
    url = _RECORDING_URL.format(mbid=urllib.parse.quote(mbid, safe=""))

    for attempt in range(_MAX_ATTEMPTS):
        respect_rate_limit(clock_fn, sleep_fn)  # every request (incl. the retry) honours 1/sec
        try:
            resp = http.get(url, headers={"User-Agent": user_agent}, params=params, timeout=timeout)
        except Exception as exc:  # noqa: BLE001 — injectable client: ANY failure is fail-soft
            if attempt + 1 < _MAX_ATTEMPTS:
                sleep_fn(_RETRY_BACKOFF_S)
                continue
            logger.warning("MB recording lookup for %s failed (%s) — treating as no data", mbid, exc)
            return None

        status = getattr(resp, "status_code", None)
        if status == 200:
            try:
                data = resp.json()
            except (ValueError, TypeError) as exc:
                logger.warning("MB recording %s returned an unparseable body (%s)", mbid, exc)
                return None
            return data if isinstance(data, dict) else None

        # A 5xx/429 is transient — retry once; a 404 (or other 4xx) is a real answer.
        if status in (429, 500, 502, 503, 504) and attempt + 1 < _MAX_ATTEMPTS:
            sleep_fn(_RETRY_BACKOFF_S)
            continue
        logger.info("MB recording %s lookup returned HTTP %s", mbid, status if status is not None else "?")
        return None
    return None
