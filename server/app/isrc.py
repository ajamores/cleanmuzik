"""ISRC → MusicBrainz recording fact lookup (T-203, spec §5 facts-from-a-real-lookup / §6).

Multi-sense reconciliation's ONE network floor on the identity path (spec §6). Given an
ISRC (Shazam hands us one when it matches), ask MusicBrainz for the single recording that
ISRC names and return that recording's **real** MBID + artist + title — or `None` when the
ISRC resolves to nothing. The ~54% miss rate is expected and normal, not an error: a track
simply proceeds on its other senses.

**It authors nothing.** It returns exactly what MusicBrainz says, or `None`. There is no
synthesis, no LLM, no invention. The MBID it returns is the sole source of a *real*
recording id for the Pa Salieu correction (ADR-021 Rule 2 / spec §5): the reconcile call
can only point at candidates whose MBID came from a real lookup, and this is one of them.

## Contract for T-204

`isrc_to_mb(isrc) -> ISRCRecording | None` is a plain function, injectable/stubbable
offline exactly as `dominance_fn` is (`import_seam.py`). T-204 builds a synthetic candidate
`{n, artist, title, mbid, source: "isrc"}` from the returned `ISRCRecording` — reading its
`.mbid` / `.artist` / `.title` — and appends it iff this returns non-`None`.

## Two load-bearing obligations, both from ADR-001

1. **User-Agent REQUIRED.** MusicBrainz refuses/throttles anonymous clients. We send the
   same descriptive UA `app.artwork` already uses for its CAA/iTunes calls (kept in sync
   here rather than imported, to avoid pulling beets in at module scope).
2. **1 request/second — its OWN gate, not yet coordinated with beets.** ADR-001 caps
   identification traffic at 1/sec. This is a *direct* MusicBrainz call outside beets' own
   MB limiter, and it keeps its OWN monotonic-clock throttle (a module-level gate) so its
   calls never self-collide. **Caveat:** that gate does not share state with beets'
   `LimiterTimeoutSession`, so within one track a beets MB candidate call followed
   immediately by this lookup can put two requests to `musicbrainz.org` inside one second.
   The 26-track spike ran both paths against live MB with *no* throttle and never tripped
   MB's limiter, so the practical risk is low; a true shared limiter is deferred to
   `docs/backlog/` (T-210) and the collision is watched for in the T-209 verify sweep.

**Fail-soft:** any network error, non-200 status (a well-formed but unknown ISRC returns a
real HTTP 404), or unparseable body → `None`, treated as "no ISRC entry". Never raises for
a lookup failure.
"""

import logging
import threading
import time
import urllib.parse
from dataclasses import dataclass

import requests

from app.config import MUSICBRAINZ_USER_AGENT

logger = logging.getLogger("cleanmuzik")

# The exact endpoint T-203 specifies. `fmt`/`inc` ride as query params (below) so the
# path stays clean and the ISRC is the only interpolated segment.
_ISRC_URL = "https://musicbrainz.org/ws/2/isrc/{isrc}"
_QUERY = {"fmt": "json", "inc": "artist-credits"}

# The MusicBrainz-required descriptive User-Agent (ADR-001), from its single home in
# config so this and `app.artwork` can't drift. config pulls no `beetsplug`, so
# importing it here is cheap (unlike importing `artwork`).
_UA = MUSICBRAINZ_USER_AGENT

# MusicBrainz's rate limit (ADR-001). We never issue two requests closer than this.
_MIN_INTERVAL_S = 1.0
_TIMEOUT_S = 15

# The one piece of shared state the 1/sec gate needs: when the last request went out, on
# the monotonic clock. Guarded by the lock so a future non-serial caller can't race it.
_rate_lock = threading.Lock()
_last_request_monotonic: float | None = None


@dataclass(frozen=True)
class ISRCRecording:
    """A real MusicBrainz recording resolved from an ISRC. Every field came from the API.

    Frozen because it is a fact, not a working value — nothing downstream should mutate
    what MusicBrainz said. T-204 reads `.mbid`/`.artist`/`.title` to build its synthetic
    `source: "isrc"` candidate.
    """

    mbid: str
    artist: str
    title: str


def _respect_rate_limit(clock_fn, sleep_fn) -> None:
    """Block until at least `_MIN_INTERVAL_S` has passed since the last request (ADR-001).

    Injectable `clock_fn`/`sleep_fn` so tests can assert the throttle without waiting a
    real second. Records the send time *after* any sleep, so back-to-back calls space
    out by the interval rather than drifting.
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


def _artist_credit_phrase(credit) -> str:
    """Join a MusicBrainz `artist-credit` array into its as-credited display phrase.

    A credit is `[{name, joinphrase, artist:{…}}, …]` — e.g. "A feat. B" arrives as two
    parts with a joinphrase between them. We reproduce MusicBrainz's own phrase verbatim
    (credited `name` + `joinphrase`), never inventing or reformatting it.
    """
    if not isinstance(credit, list):
        return ""
    out = []
    for part in credit:
        if not isinstance(part, dict):
            continue
        out.append(part.get("name") or "")
        out.append(part.get("joinphrase") or "")
    return "".join(out).strip()


def _parse_recording(data) -> ISRCRecording | None:
    """The first recording in an ISRC response → `ISRCRecording`, or `None` if unusable.

    `None` whenever the payload can't yield a *complete real fact*: no recordings, or a
    recording missing its id / title / artist. A partial record is worse than none — T-205
    matches on artist AND title, and a blank field can't support anything.
    """
    # A well-formed but non-object 200 body (a JSON array/scalar from a proxy or an MB
    # error page) parses fine but has no `.get` — guard it here so the fail-soft contract
    # holds instead of an AttributeError escaping the identity stage.
    if not isinstance(data, dict):
        return None
    recordings = data.get("recordings") or []
    if not recordings:
        return None
    rec = recordings[0] if isinstance(recordings[0], dict) else {}
    mbid = rec.get("id")
    title = rec.get("title")
    artist = _artist_credit_phrase(rec.get("artist-credit"))
    if not (mbid and title and artist):
        return None
    return ISRCRecording(mbid=mbid, artist=artist, title=title)


def isrc_to_mb(
    isrc,
    *,
    http=requests,
    user_agent: str = _UA,
    timeout: int = _TIMEOUT_S,
    clock_fn=time.monotonic,
    sleep_fn=time.sleep,
) -> ISRCRecording | None:
    """One exact MusicBrainz lookup by ISRC → real recording MBID + artist + title.

    Returns `None` when the ISRC is empty, does not resolve (HTTP 404 / no recordings),
    or the request fails — all treated identically as "no ISRC entry" (fail-soft). Sets a
    required User-Agent and respects the 1/sec floor (ADR-001) before every request.

    `http` (a `requests`-shaped client), `clock_fn`, and `sleep_fn` are injectable so the
    test suite runs offline against a captured fixture with no network and no real sleep.
    """
    if not isrc or not str(isrc).strip():
        return None
    isrc = str(isrc).strip()

    _respect_rate_limit(clock_fn, sleep_fn)

    url = _ISRC_URL.format(isrc=urllib.parse.quote(isrc, safe=""))
    try:
        resp = http.get(
            url, headers={"User-Agent": user_agent}, params=dict(_QUERY), timeout=timeout
        )
    except Exception as exc:  # noqa: BLE001 — injectable client: ANY client failure is fail-soft
        # The docstring advertises `http` as an injectable seam (T-204 may pass a non-`requests`
        # client); a failure outside requests' own hierarchy must still degrade to "no entry",
        # never escape the identity stage.
        logger.warning("ISRC lookup for %s failed (%s) — treating as no entry", isrc, exc)
        return None

    if getattr(resp, "status_code", None) != 200:
        # A well-formed but unknown ISRC returns a real 404 here — the expected ~54% gap,
        # not an error. Logged at info, not warning.
        logger.info("ISRC %s did not resolve (HTTP %s)", isrc, getattr(resp, "status_code", "?"))
        return None

    try:
        data = resp.json()
    except (ValueError, TypeError) as exc:
        logger.warning("ISRC %s returned an unparseable body (%s)", isrc, exc)
        return None

    result = _parse_recording(data)
    if result is None:
        logger.info("ISRC %s resolved to no usable recording", isrc)
    return result
