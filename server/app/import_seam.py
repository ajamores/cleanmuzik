"""The fingerprint-trust import seam — the product's spine (T-007, ADR-006).

Every downloaded song hits one gate: the machine either knows exactly which
recording this is and files it silently, or it doesn't and parks it for the owner
to pick. This module is that gate. It subclasses beets' `ImportSession`, imports
the staged MP3 **as a singleton**, and answers the one question beets would
otherwise prompt a human for.

## Why this can't just read beets' confidence (the load-bearing finding)

ADR-006 says: auto-accept when the top AcoustID fingerprint match is *dominant* —
its score is high AND there's a clear gap to the runner-up. The obvious plan is to
read that score off the top beets candidate. **It isn't there.** beets' `chroma`
plugin computes the AcoustID score inside `acoustid_match()`, uses it once for a
0.5 threshold check, and then throws it away — it keeps only the recording MBIDs
(`_matches[path]`). What reaches `task.candidates` is a `distance` per candidate,
and that is *tag* distance — the ~0.11 singleton floor the spike measured, a
different number that can never cross beets' `strong` bar (ADR-006).

So the seam recovers the score itself: `fingerprint_dominance()` runs its own
`acoustid.lookup` and reads the acoustic score AcoustID returns directly. That is
the number the gate trusts; beets is still driven for the actual tagging /
art / genre / lyrics / organize, because a dominant fingerprint's recording MBID
almost always *is* beets' top candidate (chroma gives it a -10 distance bonus).

Cost: this means one extra AcoustID lookup per song beyond chroma's own — and up
to `LOOKUP_RETRIES` more on the score-critical hop when the free tier throttles
(T-011 retry). For a single-user, one-song-at-a-time tool with ADR-001 delays
that's acceptable for R1; deduping it against chroma's cached fingerprint is a
later optimization, not a correctness issue.

## What lands vs. what parks

- **Dominant** (score ≥ `score_min` and gap ≥ `gap_min`) *and* the winning
  recording is among beets' candidates → return that `TrackMatch`. beets applies
  it, every plugin runs as a stage, and the file is organized into the library.
- **Everything else** → record the candidate **IDs** + `task.rec` to the `reviews`
  table (T-002) and return `Action.SKIP`, which leaves the disk untouched and
  parks the row. Non-blocking: the batch is never stalled by a weak match.

Thresholds are the T-008-measured values (score ≥ 0.90; the gap check retained but
off by default) and stay injectable per session for tests and any future re-tuning.
This module never lowers beets' global `strong_rec_thresh` (ADR-006).
"""

import copy
import functools
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

import acoustid
from beets import config, dbcore, library, metadata_plugins, plugins, util
from beets.autotag import Distance, Recommendation, TrackMatch
from beets.importer import Action, DuplicateAction, ImportSession
from beetsplug.musicbrainz import _get_date

from app import isrc as isrc_lookup
from app import normalize
from app import reconcile as reconcile_seam
from app import shazam as shazam_sense
from app.artwork import crop_to_square, fetch_cover_art, fetch_url_image
from app.beets_engine import LIBRARY_DIRECTORY, configure_beets
from app.config import Settings, get_settings
from app.db import Review, Store
from app.events import candidate_row
from app.source_signals import SourceSignals
from app.tagwriter import write_tags

logger = logging.getLogger("cleanmuzik")

# pyacoustid's *shared built-in* AcoustID application key — the same one beets'
# `chroma` uses for its own lookups. It's pooled across every pyacoustid user, so it
# throttles hard under load (T-008 measurement: 5 of 30 batch lookups rate-limited).
# T-011 makes this a *fallback*: `fingerprint_dominance` now runs the score-critical
# lookup on the owner's private `acoustid_apikey` when set (a valid application/lookup
# key with its own quota — verified 2026-07-14, `acoustid.lookup` → status=ok),
# resolved by `_resolve_api_key()` and bound in `import_song()`. This shared key is
# used only when the owner hasn't set one. (beets' *internal* chroma lookup during
# candidate generation still uses beets' own built-in key — a separate concern.)
API_KEY = "1vOwZtEn"

# T-011 retry-with-backoff for the identify lookup. AcoustID's free/shared tier is
# flaky and rate-limits under load, but recovers within a couple of seconds (T-008:
# every one of the 5 throttled lookups recovered on retry). Retry ONLY the network
# lookup — the fingerprint is generated once — and space attempts out per ADR-001.
LOOKUP_RETRIES = 3  # attempts after the first → 4 total before parking as a failure.
LOOKUP_BASE_DELAY = 1.0  # seconds; exponential: 1s → 2s → 4s between attempts.

# ADR-006 dominance thresholds — SET BY T-008 measurement (25 real songs across the
# owner's library + a YouTube playlist, 2026-07-14), not a guess. See docs/r1/adr.md.
SCORE_MIN = 0.90  # every correct match measured ≥ 0.955, every non-match = 0.0 — a
#                   clean, wide split with room to spare at 0.90.
GAP_MIN = 0.0  # gap-to-runner-up is kept as a knob but OFF by default: across all 25
#                songs a high runner-up was only ever the SAME song listed twice in
#                AcoustID (a re-release), never a different rival — so any gap
#                requirement only false-parked matches we were certain of. Raise this
#                only if real use ever surfaces two genuinely different recordings both
#                scoring ≥ SCORE_MIN (never observed in the sample).

# We need recording MBIDs (the identity) AND releases (so Door B's cover-art step
# can look art up on the Cover Art Archive by release MBID).
_LOOKUP_META = "recordings releases"
_LOOKUP_TIMEOUT = 10


class AcoustidLookupError(Exception):
    """A *transient* AcoustID service failure (network / timeout / rate limit / 5xx).

    Distinct from a clean "no acoustic match": this is retryable. `fingerprint_dominance`
    retries the lookup with exponential backoff around exactly this exception (T-011) and
    only re-raises once retries are exhausted; the session then parks the song rather than
    crash the run (ADR-003). A real no-match returns an all-zero `Dominance` instead (it
    simply can't be dominant) and is never retried.
    """


class AcoustidPermanentError(Exception):
    """A *non-retryable* AcoustID failure — a bad API key or malformed request.

    Deliberately NOT a subclass of `AcoustidLookupError`, so the retry loop lets it
    propagate immediately instead of retrying. Retrying these can't help: an invalid
    key returns the same error every time, so retrying would burn the full backoff on
    every song and then silently park the entire run (T-011 review finding). The gate
    parks the song (recoverable) but logs at ERROR so a misconfigured `ACOUSTID_APIKEY`
    is visible, not buried under a pile of "no match" parks.
    """


# AcoustID application-level error codes that no retry can fix — the key or request is
# wrong, not the service being briefly unavailable (codes per the AcoustID web-service
# API). Crucially includes the invalid-key codes (4, 6): a typo'd owner key must fail
# fast + loud, not retry. Any OTHER non-ok status (rate limit, service unavailable,
# internal error, or an unrecognised/absent code) is treated as transient and retried —
# a denylist, so an unknown code errs toward "retry" (harmless: at worst the pre-T-011
# behaviour of a wasted backoff), never toward "silently hammer a bad key".
_PERMANENT_ERROR_CODES = frozenset(
    {
        1,  # unknown format
        2,  # missing parameter
        3,  # invalid fingerprint
        4,  # invalid API key            ← the typo'd/revoked owner-key case
        6,  # invalid user API key
        7,  # invalid UUID
        8,  # invalid duration
        9,  # invalid bitrate
        10,  # invalid foreign id
        12,  # not allowed
        15,  # invalid MusicBrainz access token
        16,  # insecure request
        17,  # unknown application
    }
)


@dataclass(frozen=True)
class Dominance:
    """The two numbers ADR-006's gate needs, recovered straight from AcoustID.

    `top_recording_ids` are the MusicBrainz recording MBIDs grouped under the
    winning acoustic result — the identity we trust. `top_release_ids` are the
    releases those recordings appear on — Door B fetches cover art by them. The
    decision itself (compare against thresholds) lives in the session so T-008 can
    tune per run.
    """

    top_score: float
    runner_up_score: float
    top_recording_ids: tuple[str, ...]
    top_release_ids: tuple[str, ...] = ()

    @property
    def gap(self) -> float:
        return self.top_score - self.runner_up_score


def _resolve_api_key(settings: Settings) -> str:
    """The owner's private AcoustID quota if set, else the shared built-in key.

    The owner's `acoustid_apikey` (T-011) is a valid application/lookup key with its
    own rate budget; the shared `API_KEY` is pooled across every pyacoustid user and
    throttles hard under load (T-008). Prefer the owner's whenever present. An empty
    string in `.env` (the "absent is not a failure" default) falls back cleanly.
    """
    return settings.acoustid_apikey or API_KEY


def _lookup_dominance(
    fp: bytes,
    duration: float,
    *,
    api_key: str,
    meta: str,
    timeout: int,
) -> Dominance:
    """One AcoustID lookup on an already-generated fingerprint → `Dominance`.

    The retryable network hop, split out so `fingerprint_dominance` can retry *only*
    this (the fingerprint above is deterministic local work). Raises
    `AcoustidLookupError` on a transient service failure; a clean no-match returns an
    all-zero `Dominance` (not an error).
    """
    try:
        res = acoustid.lookup(api_key, fp, duration, meta=meta, timeout=timeout)
    except acoustid.AcoustidError as exc:
        # Network / HTTP / parse failure from the free tier (flaky, per the spike).
        raise AcoustidLookupError(str(exc)) from exc

    if res.get("status") != "ok":
        # pyacoustid doesn't raise on an application-level error (no raise_for_status);
        # it returns the JSON, so a rate-limit AND an invalid key both land here as a
        # non-ok status. Split them by error code: a permanent one (bad key / malformed
        # request) fails fast, everything else is transient and retried.
        error = res.get("error") or {}
        code = error.get("code")
        message = error.get("message") or res.get("status")
        if code in _PERMANENT_ERROR_CODES:
            raise AcoustidPermanentError(f"acoustid error {code}: {message}")
        raise AcoustidLookupError(f"acoustid error {code}: {message}")

    results = res.get("results") or []
    if not results:
        return Dominance(0.0, 0.0, ())

    # Sort by score ourselves — don't rely on AcoustID's response ordering. Each
    # result groups the recordings that share one acoustic fingerprint.
    results = sorted(results, key=lambda r: r.get("score") or 0.0, reverse=True)
    top = results[0]
    top_score = float(top.get("score") or 0.0)
    recording_ids = tuple(
        rec["id"] for rec in (top.get("recordings") or []) if rec.get("id")
    )
    # Releases the winning recordings appear on — order-preserving dedup (a set
    # would shuffle, making art fetches non-reproducible). Door B fetches art by
    # these; empty is fine (iTunes fallback by artist+title covers it).
    release_ids = tuple(
        dict.fromkeys(
            rel["id"]
            for rec in (top.get("recordings") or [])
            for rel in (rec.get("releases") or [])
            if rel.get("id")
        )
    )

    # The runner-up is the best result for a *different* recording. Two acoustic
    # clusters of the same recording aren't rivals — counting one would shrink the
    # gap and over-park a genuinely dominant match (ADR-006's "one recording
    # clearly winning"). A lone/only-same-recording set leaves runner-up at 0.0,
    # so the score threshold alone decides it.
    top_ids = set(recording_ids)
    runner_up_score = 0.0
    for other in results[1:]:
        other_ids = {
            rec["id"] for rec in (other.get("recordings") or []) if rec.get("id")
        }
        if top_ids.isdisjoint(other_ids):
            runner_up_score = float(other.get("score") or 0.0)
            break

    return Dominance(top_score, runner_up_score, recording_ids, release_ids)


def fingerprint_dominance(
    path: bytes | str,
    *,
    api_key: str = API_KEY,
    meta: str = _LOOKUP_META,
    timeout: int = _LOOKUP_TIMEOUT,
    retries: int = LOOKUP_RETRIES,
    base_delay: float = LOOKUP_BASE_DELAY,
    sleep_fn=time.sleep,
) -> Dominance:
    """Fingerprint `path` and read its AcoustID score + runner-up gap.

    THE crux of T-007 (see module docstring): the number beets throws away. Generates
    the fingerprint once, then runs an independent `acoustid.lookup` — retried with
    exponential backoff on a transient failure (T-011) — and returns a `Dominance`.
    Raises `AcoustidLookupError` only after retries are exhausted, so the caller parks
    rather than crashes. A fingerprint that generates but matches nothing returns an
    all-zero `Dominance` (not an error — it just parks) and is never retried.
    """
    try:
        duration, fp = acoustid.fingerprint_file(util.syspath(path))
    except acoustid.NoBackendError:
        # fpcalc/Chromaprint is unreachable AT RUNTIME — the boot smoke_check
        # passed but the backend has since vanished (FPCALC points at a cleared
        # scratchpad binary, a shared lib went missing, …). This is a *systemic*
        # engine failure, not a per-file miss: swallowing it as a no-match would
        # silently park every song with zero signal — the exact degradation the
        # boot receipt treats as hard-red. Surface it loudly instead. (Caught
        # before FingerprintGenerationError below, of which it is a subclass.)
        raise
    except acoustid.FingerprintGenerationError as exc:
        # This *one* file won't fingerprint (corrupt audio). Not retryable and not
        # a match: park it rather than crash the run.
        logger.warning("fingerprint generation failed for %r: %s", path, exc)
        return Dominance(0.0, 0.0, ())

    # Retry ONLY the lookup — the fingerprint above is generated once. A transient
    # AcoustidLookupError (bad status / network / rate-limit) backs off and retries;
    # a clean no-match returns from _lookup_dominance without raising and stops here.
    last_exc: AcoustidLookupError | None = None
    for attempt in range(retries + 1):
        try:
            return _lookup_dominance(
                fp, duration, api_key=api_key, meta=meta, timeout=timeout
            )
        except AcoustidLookupError as exc:
            last_exc = exc
            if attempt < retries:
                delay = base_delay * (2**attempt)
                logger.warning(
                    "acoustid lookup for %r failed (%s) — retry %d/%d in %.1fs",
                    path,
                    exc,
                    attempt + 1,
                    retries,
                    delay,
                )
                sleep_fn(delay)

    # Retries exhausted — surface the last transient error so the session parks the
    # song (ADR-003). The loop body always runs ≥ once, so last_exc is set.
    assert last_exc is not None
    raise last_exc


@dataclass
class Outcome:
    """What the gate did with one task — the seam's observable receipt.

    T-012/T-013 turn this into SSE events; the standalone driver and tests read it
    to confirm the real side effect (spine is script-provable before any web layer).

    ## Why the SSE-shaped fields live on the receipt (T-013)

    spec §6's rich payloads — `track.tagging.chosen`, `track.done.tags`+`path`, and
    `track.review_required.candidates[]` — are only knowable *inside the seam*: the
    chosen candidate is the `TrackMatch` we accepted, the final tags/path are the
    beets `Item` after it applied and organized, and the candidate list is the beets
    candidates in hand at park time. `run_pipeline` emits the events but has none of
    that data. Rather than have the emitter reach back into beets (re-reading the
    landed file, or re-hydrating candidates — the latter is T-014's job), the seam,
    which already holds every value, hands them up on this receipt. That keeps the
    seam the single source of truth and the emitter a thin, honest relay. A candidate
    carries only `candidate_id`/`title`/`artist`/`score` — album, year and art were
    removed from the contract (ADR-010: a recording is not a release), see
    `_candidate_rows`.
    """

    action: str  # "landed" | "skipped" | "parked"
    top_score: float
    gap: float
    track_id: str | None = None  # the accepted recording MBID (landed)
    review_id: str | None = None  # the parked review row id (parked)
    # T-206: the reconcile Verdict's park discriminators, carried up so the live
    # `track.review_required` event tells the same park story the persisted row does
    # (the card need not fetch to learn why). Empty on the R1/degrade park (no Verdict).
    reason: str | None = None
    contradictions: list[str] = field(default_factory=list)
    rec: str | None = None  # parked: the row's `rec`, so the SSE event can tell the
    # card WHICH question to render — a weak/ambiguous match ("none"/"low"/…) vs a
    # "duplicate" (T-017). The card would otherwise have to fetch GET /api/reviews just
    # to discriminate; carrying it here keeps the common weak-match path fetch-free.
    art_embedded: bool = False  # Door B: did a cover land on the file (landed only)
    # --- T-013 SSE payloads, sourced where the data is in hand ------------------
    chosen: dict | None = None  # landed: {title, artist, album, year} of the match
    tags: dict | None = None  # landed: {title,artist,album,year,genre,has_art,has_lyrics}
    landed_path: str | None = None  # landed: the organized library path (str, decoded)
    candidates: list[dict] | None = None  # parked: rich candidate rows for the UI


@dataclass
class _Reconciliation:
    """One reconcile attempt's outcome — what the T-205 2-of-3 gate consumes.

    `verdict` is the validated `Verdict`, or `None` on a failure the gate turns into a
    park. `candidates` is the augmented `candidates[]` the verdict's indices point into,
    and `shazam` is the raw Shazam record — both needed to RE-DERIVE agreement in code.
    `degraded` means the adjudicator is unusable (a rejected/expired key), so the gate
    falls back to the R1 fingerprint gate instead of parking (spec §6 degrade row).
    """

    verdict: reconcile_seam.Verdict | None
    candidates: list[dict]
    shazam: dict | None
    degraded: bool = False


# --- original release year (ADR-014) ----------------------------------------

_mb_api_cache = None


def _musicbrainz_api():
    """The loaded `musicbrainz` plugin's rate-limited API client, or None.

    Reuses beets' own client (its session, config, and MusicBrainz rate limiter)
    rather than standing up a second one, and caches it: the plugin is a
    process-lifetime singleton, so re-scanning `find_plugins()` on every landed
    track is pure waste (review F6). None (uncached) only until plugins load —
    which happens before the pipeline path via `configure_beets`.
    """
    global _mb_api_cache
    if _mb_api_cache is not None:
        return _mb_api_cache
    for plugin in plugins.find_plugins():
        if plugin.name == "musicbrainz":
            _mb_api_cache = getattr(plugin, "mb_api", None)
            return _mb_api_cache
    return None


def fetch_original_date(
    recording_id: str | None,
) -> tuple[int | None, int | None, int | None]:
    """Original-ish release date for a MusicBrainz recording, as (year, month, day).

    ADR-014's proxy for a track's original year: a singleton's `TrackInfo` carries
    no date (a recording lookup fetches no releases), so we look the accepted
    recording up ONCE (releases + release-groups) and read a date from it:

    1. the recording's own `first_release_date` — MusicBrainz's authoritative
       "when this recording first came out" (review F4); failing that,
    2. the earliest date across the recording's releases (the release-group
       `first_release_date` preferred, else the per-release `date`), and for a tie
       on year the most complete date wins (review F3).

    A proxy, not a guarantee: MusicBrainz models each remaster as its own recording,
    so this is the true original year only when the fingerprint matched the original
    master. Best-effort — any failure returns all-None and the track lands with a
    blank year, never an error (the caller treats it like a missing cover).
    """
    if not recording_id:
        return None, None, None
    api = _musicbrainz_api()
    if api is None:
        return None, None, None
    recording = api.get_recording(
        recording_id, includes=["releases", "release-groups"]
    )
    year, month, day = _get_date(recording.get("first_release_date"))
    if year:
        return year, month, day

    dated: list[tuple[int, int | None, int | None]] = []
    for release in recording.get("releases") or []:
        release_group = release.get("release_group") or {}
        for raw in (release_group.get("first_release_date"), release.get("date")):
            y, m, d = _get_date(raw)
            if y:
                dated.append((y, m, d))
                break  # prefer the release-group date for this release
    if not dated:
        return None, None, None
    # Earliest year, and within that year the most complete date (month/day known).
    return min(dated, key=lambda t: (t[0], t[1] is None, t[2] is None))


class FingerprintTrustSession(ImportSession):
    """Drives a singleton import and answers `choose_item` with the ADR-006 gate.

    Constructed per song. `query` is the normalized title (T-006) recorded on a
    parked review so the UI can show what was searched — deliberately NOT beets'
    own `self.query` (a `dbcore.Query`), which stays `None` for a path import.
    """

    def __init__(
        self,
        lib: library.Library | None,
        *,
        store: Store,
        job_id: str,
        staging_path: bytes | str,
        query: str,
        score_min: float = SCORE_MIN,
        gap_min: float = GAP_MIN,
        dominance_fn=fingerprint_dominance,
        art_fn=fetch_cover_art,
        shazam_art_fn=fetch_url_image,
        tag_writer_fn=write_tags,
        date_fn=fetch_original_date,
        source_signals: SourceSignals | None = None,
        shazam_fn=None,
        isrc_fn=None,
        reconcile_fn=None,
    ) -> None:
        super().__init__(lib, None, [os.fspath(staging_path)], None)
        self.store = store
        self.job_id = job_id
        # fsdecode, NOT fspath: beets item paths are bytes, and the signature
        # accepts bytes, but this value is written to the TEXT staging_path column
        # and read back by T-014/T-012 — a bytes value would round-trip as a BLOB.
        self.staging_path = os.fsdecode(staging_path)
        self.normalized_query = query
        self.score_min = score_min
        self.gap_min = gap_min
        self.dominance_fn = dominance_fn
        self.art_fn = art_fn
        # T-222 (ADR-033): the cover fetcher for the Shazam/thumbnail source — a plain
        # URL GET, distinct from `art_fn`'s CAA/iTunes release lookup. Injected for tests.
        self.shazam_art_fn = shazam_art_fn
        # T-223 (ADR-033): the mutagen ID3 tag+art writer that lands a track's tags,
        # replacing beets' `write` stage + `embedart` (import `write` is now off). Injected
        # so the decision tests stub it offline; the on-disk seam tests use the real writer.
        self.tag_writer_fn = tag_writer_fn
        self.date_fn = date_fn
        # R1.5 reconcile seam (T-204), each stubbable offline exactly as dominance_fn is.
        # source_signals is sense 1 (T-201); shazam_fn is sense 3 (T-202, called once per
        # track, hard-timeout); isrc_fn resolves a Shazam ISRC to a real MB recording
        # (T-203); reconcile_fn(evidence) -> Verdict is the LLM adjudicator. All default to
        # absent so the resolve/keep-untagged subclasses and the R1 gate are untouched —
        # `_reconcile` bails when reconcile_fn is None, so no sense is even gathered then.
        self.source_signals = source_signals
        self.shazam_fn = shazam_fn
        self.isrc_fn = isrc_fn
        self.reconcile_fn = reconcile_fn
        # T-204 produces a Verdict here; T-205 makes the land/park decision consume it.
        self.verdict: reconcile_seam.Verdict | None = None
        # The augmented candidates the Verdict's indices point into (beets' MB
        # candidates ++ the synthetic ISRC entry). Stashed for T-206, which persists the
        # LLM-ranked candidate order onto a parked review — the Verdict's `ranking` is
        # meaningless without this list to resolve its indices to real MBIDs.
        self.reconcile_candidates: list[dict] = []
        self.outcomes: list[Outcome] = []
        # Accepted matches await finalization: choose_item can only *decide* to
        # land; whether beets actually copied the file is known only after run()
        # (its duplicate stage may skip it). See finalize_outcomes().
        self._accepted: list[tuple[object, object, Dominance]] = []
        # T-208: memoize full MusicBrainz hydrations for this ONE track. Session = one
        # song, so there is no staleness question; routing every `track_for_id` through
        # it (`_cached_track_for_id`) collapses the same-MBID-twice repeats T-218 caught
        # before they hit MusicBrainz's 1/sec limiter.
        self._trackinfo_cache: dict[str, object] = {}
        # T-222 (ADR-033): the Shazam record for THIS track, gathered once in
        # choose_item and reused everywhere — the reconcile evidence AND the land tail's
        # tag/art source. Restores ADR-024's "Shazam every track": T-219's fast-path had
        # stopped gathering it on the corroborated majority, but the tag/art reshape
        # needs it in hand there too (the recognition is the cheap sense; the expensive
        # ISRC + LLM steps the fast-path skips stay skipped). `None` until gathered / when
        # no `shazam_fn` is wired (resolve + keep-untagged subclasses).
        self.shazam_record: dict | None = None
        # T-222: the resolved tag/art source per accepted task (keyed by id(task)) —
        # `{"kind": "shazam"|"acoustid", "record": <shazam dict|None>}`. Kept beside
        # `_accepted` rather than in its tuple so the resolve/keep-untagged subclasses'
        # own accept/finalize paths (which never set it) are untouched and default to
        # the AcoustID/MB behaviour. Read + cleared in finalize_outcomes.
        self._tag_sources: dict[int, dict] = {}

    # --- the gate ---------------------------------------------------------

    def choose_item(self, task):
        """The one decision. Return a `TrackMatch` to land, or `Action.SKIP` to park.

        R1.5 (T-205): when a reconcile adjudicator is wired, the **2-of-3 gate** decides
        (`_reconcile_gate`); with none wired — no `ANTHROPIC_APIKEY`, a rejected key, or
        a resolve session — the pipeline **degrades** to R1's fingerprint-only gate
        (`_fingerprint_gate`, spec §6 degrade row). A fingerprint-lookup failure parks
        regardless: an identity we couldn't even fingerprint can't be reconciled.
        """
        # Reset the per-track reconcile state up front (T-206). A park that happens BEFORE
        # the reconcile branch below — an AcoustID lookup failure — otherwise reads a
        # Verdict/candidates left over from a prior track, which `_park` would persist onto
        # this one. Safe by construction today (one session per song), but the reset makes
        # `_park`'s correctness independent of that invariant rather than reliant on it.
        self.verdict = None
        self.reconcile_candidates = []
        self.shazam_record = None
        try:
            dominance = self.dominance_fn(task.item.path)
        except AcoustidPermanentError as exc:
            # A bad key / malformed request — no retry helps, so it arrived here
            # immediately (not after the backoff). Park the song (recoverable) but log
            # LOUDLY: an invalid ACOUSTID_APIKEY would otherwise park every song in the
            # run with no hint why (T-011 review finding). ERROR, not WARNING, and it
            # names the likely cause so the misconfig is actionable.
            logger.error(
                "acoustid permanently rejected the lookup for %s (%s) — parking; "
                "check ACOUSTID_APIKEY in .env",
                self.staging_path,
                exc,
            )
            self._park(task, list(task.candidates or []), Dominance(0.0, 0.0, ()))
            return Action.SKIP
        except AcoustidLookupError as exc:
            # The seam's own AcoustID lookup failed transiently AND exhausted its
            # retries (fingerprint_dominance backs off and retries first, T-011). Don't
            # let it unwind out of beets' pipeline and crash the import — park to review
            # so the song is recoverable, and log distinctly (ADR-003: one failure never
            # stops the run).
            logger.warning(
                "acoustid lookup failed for %s (%s) — parking for review",
                self.staging_path,
                exc,
            )
            self._park(task, list(task.candidates or []), Dominance(0.0, 0.0, ()))
            return Action.SKIP

        candidates = list(task.candidates or [])

        # T-222 (ADR-033): gather Shazam ONCE per track, here, so every land path — the
        # degrade gate, the T-219 fast-path, and the full reconcile gate — has the record
        # in hand as its tag/art source. Only the cheap recognition runs here; the
        # expensive ISRC resolve + LLM adjudication stay where they were (the fast-path
        # still skips them). `recognize` is fail-soft (never raises), but a test double
        # might, so guard it — a Shazam miss is a non-vote, never a crash.
        self.shazam_record = self._gather_shazam()

        if self.reconcile_fn is None:
            # No LLM adjudicator wired (no ANTHROPIC_APIKEY, or a resolve/keep-untagged
            # session) — R1's fingerprint-only *land decision* (spec §6 degrade row). The
            # DECISION is unchanged; the tag/art SOURCE is not: with Shazam now gathered
            # above, a corroborated land here sources tags/art from the Shazam record like
            # any other (ADR-033) — the degrade path loses the LLM, not the Shazam tags.
            return self._fingerprint_gate(task, dominance, candidates)

        # T-219 corroboration fast-path: land a dominant, source-corroborated fingerprint
        # WITHOUT the EXPENSIVE reconcile senses (ISRC resolve + LLM — the ~3–6s steady
        # per-track cost, T-218). fp + yt agreeing is the 2-of-3 accept bar re-derived in
        # code (the same two senses `_agreeing_senses` would count), so it lands what the
        # gate lands on that evidence. It is NOT purely the gate minus latency: skipping
        # reconcile also drops the LLM's veto and the Shazam→ISRC correction for this
        # case — the deliberate T-219 trade, recorded and owner-adjudicated in ADR-032.
        # (Shazam's own recognition IS now gathered above for the tag source — ADR-032
        # amended by T-222; only the ISRC + LLM are skipped here.) Everything weaker
        # falls through to the full gate below.
        fast = self._corroboration_fast_path(task, dominance, candidates)
        if fast is not None:
            return fast

        # An adjudicator IS wired (R1.5): reconcile the three senses into a Verdict,
        # then let the 2-of-3 gate decide. A rejected/expired key degrades to the R1
        # gate — a stale key must not park every track; a transient failure on a valid
        # key parks THIS track ('adjudication unavailable'), never a silent land.
        result = self._reconcile(task, dominance, candidates)
        self.verdict = result.verdict
        self.reconcile_candidates = result.candidates  # for T-206's ranked persistence
        if result.degraded:
            return self._fingerprint_gate(task, dominance, candidates)
        if result.verdict is None:
            self.verdict = reconcile_seam.Verdict(
                verdict="park",
                chosen_candidate=None,
                reason="adjudication unavailable",
            )
            self._park(task, candidates, dominance)
            return Action.SKIP
        return self._reconcile_gate(task, dominance, candidates, result)

    # --- T-219 corroboration fast-path (skip the LLM when fp + yt agree) ---

    def _corroboration_fast_path(self, task, dominance, candidates):
        """Land a dominant, source-corroborated fingerprint without the LLM (T-219, ADR-032).

        Returns a `TrackMatch`/`Action.SKIP` when the fast-path fires and settles the
        track, or `None` to fall through to the full reconcile gate. Fires iff the two
        senses the 2-of-3 gate accepts on already agree, re-derived here through the SAME
        helpers the gate uses so the two cannot drift:

        - `fp` supports: `_dominant_match` — a dominant fingerprint (score ≥ `score_min`,
          gap ≥ `gap_min`) whose winning recording is among beets' candidates (the exact
          test `_fingerprint_gate` lands on; recording-MBID identity, not text).
        - `yt` supports: `_yt_supports` — the YouTube source signals corroborate that
          candidate on artist AND title.

        That is fp + yt = the 2-of-3 accept bar, so this lands what the gate would land
        on that same evidence. It is NOT merely the gate minus latency: skipping
        reconcile also skips the LLM's *veto* (it can no longer park a corroborated match
        on album/year context) and the Shazam→ISRC *correction* (a wrong-recording-of-the-
        right-song is not re-picked). Both are the deliberate T-219 trade — a ≥0.90
        fingerprint identifies the actual audio, the yt agreement guards the Pa Salieu
        mis-fire, and the original year is stamped independently (ADR-014) — recorded and
        owner-adjudicated in ADR-032. Anything weaker returns `None` and runs the full
        gate. Lands through the shared `_accept` tail, so the T-009 duplicate check,
        ADR-028 credit fold, and T-208 re-hydration all run exactly as on the gate paths.
        """
        match = self._dominant_match(dominance, candidates)
        if match is None:
            return None
        info = match.info
        if not self._yt_supports(
            getattr(info, "artist", None), getattr(info, "title", None)
        ):
            return None
        return self._accept(
            task,
            match,
            dominance,
            detail=(
                f"score={dominance.top_score:.3f} gap={dominance.gap:.3f} "
                "senses=['fp', 'yt'] (corroboration fast-path)"
            ),
        )

    # --- R1 fingerprint gate (the degrade target) -------------------------

    def _dominant_match(self, dominance, candidates):
        """The beets candidate that IS the dominant fingerprint's recording, or `None`.

        The single 'is this a dominant fingerprint whose recording is on the candidate
        list' test (ADR-006), shared by `_fingerprint_gate` and the T-219 fast-path so
        both agree on what *dominant* means. Dominant = there are candidates, the score
        clears `score_min`, the gap clears `gap_min`, AND a candidate matches the winning
        recording MBID. `None` when any part fails — the caller distinguishes the reasons
        only if it needs to (the gate re-checks the threshold for its distinct log).
        """
        if not (
            candidates
            and dominance.top_score >= self.score_min
            and dominance.gap >= self.gap_min
        ):
            return None
        return _matching_candidate(candidates, dominance.top_recording_ids)

    def _fingerprint_gate(self, task, dominance, candidates):
        """R1's fingerprint-trust gate (ADR-006), also R1.5's degrade path.

        Auto-land a dominant fingerprint (score ≥ `score_min`, gap ≥ `gap_min`) whose
        winning recording is among beets' candidates; anything else parks.
        """
        match = self._dominant_match(dominance, candidates)
        if match is not None:
            # The fingerprint IS the identity here, so its dominance describes the
            # landed recording — correct release ids for the cover-art fetch.
            return self._accept(
                task,
                match,
                dominance,
                detail=(
                    f"score={dominance.top_score:.3f} "
                    f"gap={dominance.gap:.3f} (fingerprint)"
                ),
            )
        # Dominant fingerprint but its recording isn't among beets' candidates (rare):
        # trusting a *different* candidate would betray the fingerprint, so park rather
        # than mis-tag. Re-check the threshold (diagnostic only — the land decision is
        # `_dominant_match` above) so the log fires solely on that in-between case.
        if (
            candidates
            and dominance.top_score >= self.score_min
            and dominance.gap >= self.gap_min
        ):
            logger.info(
                "dominant fingerprint for %s but no matching candidate — parking",
                self.staging_path,
            )

        self._park(task, candidates, dominance)
        return Action.SKIP

    def _accept(self, task, match, dominance: Dominance, *, detail: str = ""):
        """Accept `match` for landing — the shared tail of both gates.

        Runs T-009's acquire-time dedup HERE rather than via beets' import duplicate
        stage: beets can't detect our duplicates (its probe is built from the match's
        TrackInfo — recording id under `track_id` — *before* the track_id→mb_trackid
        mapping, so a duplicate_keys query on mb_trackid always finds nothing). We hold
        the winning recording id and the library, so we query it directly and park an
        upgrade for the owner.

        Records the accept but DON'T mark "landed" yet: whether beets actually copied
        the file is known only post-`run()` (finalize_outcomes) — the receipt must not
        lie if the copy later fails. `dominance` must describe the LANDED recording (its
        release ids drive the cover-art fetch); the reconcile gate zeroes it when the
        fingerprint dissented, so art never comes from a recording we didn't land.
        """
        # T-222 (ADR-033): the tag/art SOURCE for this land — the accepted identity, not
        # a MusicBrainz re-derivation. When Shazam is in hand AND corroborates the landed
        # recording, its record is the source; otherwise (Shazam missed or named a
        # different song) the AcoustID-only path re-hydrates from MusicBrainz as before.
        # Decided here, BEFORE hydration, because the Shazam source skips it entirely.
        source = self._resolve_tag_source(match)

        if source["kind"] == "shazam":
            # Override the applied identity's PATH-relevant tags (artist/album/title) with
            # the Shazam record now, so beets organizes the file coherently with what will
            # be written — year/genre/art are non-path and get set in finalize. No
            # `_ensure_full_match`: the Shazam-backed land never touches MusicBrainz.
            match = self._shazam_match(match, source["record"])
        else:
            # T-208 (load-bearing): re-hydrate a thin winner to full tags BEFORE anything
            # reads it. Steps 2/3 make beets' candidates thin (track_id/title/artist/length
            # only); the single recording that actually lands is re-fetched here — the one
            # point both gates cross — so it can never write a file missing ISRC/genre/art
            # silently. A hydration failure parks (never land thin); a full match (Step-1
            # today, or a full winner) passes straight through.
            full = self._ensure_full_match(task, match)
            if full is None:
                self._park(task, list(task.candidates or []), dominance)
                return Action.SKIP
            match = full
        match = canonicalize_credit(match)  # ADR-028 (T-308): fold before the match is applied
        existing = self._library_duplicates(match.info.track_id)
        if existing:
            return self._resolve_duplicate(task, existing, dominance)
        self._accepted.append((task, match, dominance))
        self._tag_sources[id(task)] = source
        logger.info(
            "accepting %s: recording=%s source=%s %s",
            self.staging_path,
            match.info.track_id,
            source["kind"],
            detail,
        )
        return match

    # --- T-222 tag/art source (the accepted identity, not a MB re-derivation) ---

    def _resolve_tag_source(self, match) -> dict:
        """Pick the tag/art source for an accepted `match` (ADR-033 decisions 1–2).

        `{"kind": "shazam", "record": <record>}` when Shazam matched this track AND
        corroborates the landed identity — its tags + `art_url` are then the source, no
        MusicBrainz. Otherwise `{"kind": "acoustid", "record": None}` — Shazam missed or
        named a different song, so the AcoustID-only path re-hydrates one `get_recording`
        (the T-208 discipline) for tags + art. Corroboration — not a lone Shazam vote —
        authorises trusting Shazam's tags (ADR-021: Shazam never lands alone; preserved).
        """
        record = self.shazam_record
        if record and record.get("matched") and _shazam_corroborates(record, match.info):
            return {"kind": "shazam", "record": record}
        return {"kind": "acoustid", "record": None}

    def _shazam_match(self, match, record: dict):
        """`match` with its PATH-relevant tags overridden from the Shazam record (T-222).

        Deep-copies the `TrackInfo` first (it can be a beets-cached object shared across
        candidates — the same hazard `canonicalize_credit` guards) and sets
        artist/album/title from Shazam, keeping the recording MBID (`track_id`) so dedup
        and `mb_trackid` are unchanged. beets applies these onto the item and organizes
        by them, so the folder matches the tags; year/genre/art (non-path) are set in
        finalize. A field Shazam omits leaves the existing value rather than blanking it.
        """
        info = copy.deepcopy(match.info)
        if record.get("shazam_artist"):
            info.artist = record["shazam_artist"]
        if record.get("shazam_title"):
            info.title = record["shazam_title"]
        if record.get("album"):
            info.album = record["album"]
        # Shazam's ISRC is authoritative — carry it so skipping the MB hydration doesn't
        # drop the ISRC tag on the Shazam path (the mutagen writer, T-223, then owns it).
        if record.get("isrc"):
            info.isrc = record["isrc"]
        return TrackMatch(match.distance, info, match.item)

    def _ensure_full_match(self, task, match):
        """Re-hydrate a thin candidate to a full `TrackInfo`, or `None` if it can't (T-208).

        The single guard behind the no-thin-landing rule. Steps 2/3 emit `cm_thin`
        candidates carrying only the fields scoring reads; every other tag (ISRC, genre,
        artist relations, the data cover-art keys off) exists only on a full
        `track_for_id`. A full match — or any match with no `cm_thin` marker, which is
        every match before Step 2 ships — returns unchanged, so this is a no-op today.
        A thin match is re-fetched through the per-track cache (the winner is hydrated
        exactly once); a lookup miss returns `None` so the caller parks rather than land
        a hollow file. The recording MBID and distance are preserved.
        """
        info = getattr(match, "info", None)
        if not getattr(info, "cm_thin", False):
            return match
        full = _cached_track_for_id(
            getattr(info, "track_id", None), self._trackinfo_cache
        )
        if full is None:
            logger.warning(
                "thin winner %s did not re-hydrate for %s — parking (never land thin)",
                getattr(info, "track_id", None),
                self.staging_path,
            )
            return None
        return TrackMatch(match.distance, full, task.item)

    # --- the 2-of-3 reconcile gate (R1.5 T-205) ---------------------------

    def _reconcile_gate(self, task, dominance, candidates, result: _Reconciliation):
        """The 2-of-3 accept gate (spec §5) — the safety spine.

        Auto-land iff ALL hold: (1) the Verdict accepts; (2) **≥2 present senses**
        genuinely support the chosen candidate, RE-DERIVED in code (`_agreeing_senses`),
        never the LLM's own `agreeing_senses` count; (3) the chosen candidate carries a
        real MBID. Anything else parks (carrying the Verdict's reason/contradictions,
        which T-206 persists). An accepted identity lands via the same
        `match_for_recording` machinery a manual resolve uses — no new landing path, and
        the same T-009 duplicate check the fingerprint gate runs.
        """
        verdict = result.verdict
        chosen = _candidate_by_n(result.candidates, verdict.chosen_candidate)
        agreeing = (
            self._agreeing_senses(chosen, dominance, result.shazam) if chosen else []
        )

        if (
            verdict.verdict == "accept"
            and chosen is not None
            and chosen.get("mbid")
            and len(agreeing) >= 2
        ):
            # match_for_recording can hit a LIVE MusicBrainz lookup (track_for_id) when
            # the chosen candidate — e.g. the synthetic ISRC entry — isn't among beets'
            # candidates. A transient MB failure must PARK this track, never error the
            # run (spec §5: a reconcile-path failure is never a silent land, and never a
            # crash either). A `None` return (recording no longer resolves) parks too.
            try:
                match = match_for_recording(
                    task, chosen["mbid"], cache=self._trackinfo_cache
                )
            except Exception as exc:  # noqa: BLE001 — a live-lookup failure parks, not errors
                logger.warning(
                    "reconcile land-lookup failed for %s (recording %s: %s) — parking",
                    self.staging_path,
                    chosen["mbid"],
                    exc,
                )
                match = None
            if match is not None:
                # Carry a dominance that describes the recording we're LANDING, not the
                # fingerprint's pick. When fp is among the agreeing senses its
                # recording IS the chosen one, so its release ids give correct cover
                # art; otherwise (an ISRC correction the fingerprint dissented from)
                # zero it so `_resolve_cover` falls back to artist/title instead of
                # embedding the wrong recording's cover (as ResolveSession does).
                land_dominance = dominance if "fp" in agreeing else Dominance(0.0, 0.0, ())
                return self._accept(
                    task,
                    match,
                    land_dominance,
                    detail=f"source={chosen.get('source')} senses={agreeing} (reconcile)",
                )
            # The chosen recording no longer resolves to metadata — park, not a hole.
            logger.warning(
                "reconcile chose recording %s for %s but it did not resolve — parking",
                chosen["mbid"],
                self.staging_path,
            )

        logger.info(
            "reconcile-park %s: verdict=%s chosen=%s agreeing=%s (llm claimed %s) reason=%r",
            self.staging_path,
            verdict.verdict,
            verdict.chosen_candidate,
            agreeing,
            verdict.agreeing_senses,
            verdict.reason,
        )
        self._park(task, candidates, dominance)
        return Action.SKIP

    def _yt_supports(self, artist, title) -> bool:
        """Does the YouTube source sense (sense 1) support a candidate with this artist/title?

        The ONE yt-vote rule, shared by `_agreeing_senses` (the 2-of-3 gate) and the
        T-219 fast-path so the two can never drift out of lockstep — the fast-path's
        safety claim (fp+yt here == the gate's fp+yt) holds only while this is the sole
        definition. A None `yt_artist` is an unrecoverable claim that supports nothing
        (T-201); BOTH fields must loose-match (`normalize.loose_match`) or yt can't vote
        — what parks Strawberry Swing (yt "frankocean" ⊄ candidate "coldplay"). Callers
        pass the candidate's artist/title: a dict entry in the gate, a `TrackInfo`'s
        fields in the fast-path.
        """
        ss = self.source_signals
        return bool(
            ss is not None
            and ss.yt_artist
            and normalize.loose_match(ss.yt_artist, artist)
            and normalize.loose_match(ss.yt_title, title)
        )

    def _agreeing_senses(self, chosen, dominance, shazam) -> list[str]:
        """Which PRESENT senses genuinely support `chosen`, re-derived in code (spec §5).

        The load-bearing guard the whole 2-of-3 rule rests on — never trusting the LLM's
        `agreeing_senses`. A sense counts only when it is both present and supports the
        chosen candidate on artist AND title (loose containment, `normalize.loose_match`),
        except `fp`, which supports by recording-MBID *identity*, and `sz` for the
        ISRC-sourced candidate, which IS Shazam's own identity.
        """
        senses: list[str] = []
        if self._yt_supports(chosen["artist"], chosen["title"]):
            senses.append("yt")
        # fp: present iff the fingerprint named any recording; supports iff the chosen
        # candidate IS one of them — recording identity, not a text match.
        if dominance.top_recording_ids and chosen["mbid"] in set(
            dominance.top_recording_ids
        ):
            senses.append("fp")
        # sz: present iff Shazam matched; supports the ISRC-sourced candidate by
        # construction (that entry is Shazam's identity), else on both fields matching.
        if shazam and shazam.get("matched"):
            if chosen["source"] == "isrc" or (
                normalize.loose_match(shazam.get("shazam_artist"), chosen["artist"])
                and normalize.loose_match(shazam.get("shazam_title"), chosen["title"])
            ):
                senses.append("sz")
        return senses

    # --- sense gathering + adjudication (R1.5 T-204/T-205) ----------------

    def _gather_shazam(self) -> dict | None:
        """Recognise this track via Shazam, fail-soft — the tag/art source (T-222).

        Called once per track in choose_item so the record is in hand on every land
        path. `recognize` (T-202) is already fail-soft with a hard timeout and never
        raises, but a test double or a mis-wired fn might, so a failure here degrades to
        `None` (a Shazam miss — the AcoustID-only tag path takes over) rather than crash
        the gate. Returns `None` when no `shazam_fn` is wired (resolve/keep-untagged).
        """
        if not self.shazam_fn:
            return None
        try:
            return self.shazam_fn(self.staging_path)
        except Exception as exc:  # noqa: BLE001 — a Shazam failure is a non-vote, never a crash
            logger.warning(
                "shazam recognition raised for %s (%s) — treating as a miss",
                self.staging_path,
                exc,
            )
            return None

    def _reconcile(self, task, dominance, candidates) -> _Reconciliation:
        """Resolve the ISRC, build augmented candidates, adjudicate → a `_Reconciliation`.

        Order (spec §6): the Shazam record (already gathered once in choose_item,
        T-222) → resolve its ISRC via `isrc_fn` → build the augmented `candidates[]`
        (beets' MB candidates ++ the synthetic ISRC entry *iff* the ISRC resolved) →
        `reconcile_fn(evidence)`. Only reached when a `reconcile_fn` is wired (choose_item
        gates on that). `dominance` was already computed by the caller and rides in the
        evidence.

        Failure is never a silent land. A rejected/expired key (401/403) returns
        `degraded=True` → choose_item falls back to the R1 gate (spec §6 degrade). Any
        other reconcile failure — a transient 5xx/timeout, a non-schema response, or a
        sense that raised — returns `verdict=None` → choose_item parks this one track.
        """
        try:
            shazam_record = self.shazam_record
            isrc_recording = None
            if self.isrc_fn and shazam_record and shazam_record.get("matched"):
                isrc_recording = self.isrc_fn(shazam_record.get("isrc"))
            augmented = reconcile_seam.build_candidates(candidates, isrc_recording)
            evidence = reconcile_seam.build_evidence(
                self.source_signals, dominance, augmented, shazam_record
            )
        except Exception as exc:  # noqa: BLE001 — can't build evidence → park, don't crash
            logger.warning(
                "reconcile evidence-gathering failed for %s (%s) — parking",
                self.staging_path,
                exc,
            )
            return _Reconciliation(verdict=None, candidates=[], shazam=None)

        try:
            verdict = self.reconcile_fn(evidence)
        except Exception as exc:  # noqa: BLE001 — a reconcile failure must not crash the gate
            if _is_auth_error(exc):
                logger.warning(
                    "reconcile rejected the key for %s (%s) — degrading to the R1 gate",
                    self.staging_path,
                    exc,
                )
                return _Reconciliation(
                    verdict=None,
                    candidates=augmented,
                    shazam=shazam_record,
                    degraded=True,
                )
            logger.warning(
                "reconcile failed for %s (%s) — parking (adjudication unavailable)",
                self.staging_path,
                exc,
            )
            return _Reconciliation(
                verdict=None, candidates=augmented, shazam=shazam_record
            )
        return _Reconciliation(
            verdict=verdict, candidates=augmented, shazam=shazam_record
        )

    def finalize_outcomes(self) -> list[Outcome]:
        """Settle accepted matches against what beets actually did, post-`run()`.

        choose_item can only *decide* to land. Whether the file truly landed is
        known only after the pipeline runs: a task can still be skipped (`task.skip`)
        before the copy. So we record "landed" only for accepts that weren't skipped,
        and "skipped" otherwise — an honest receipt so T-013's SSE doesn't report done
        on a no-op. Idempotent.

        Staging-cleanup contract for T-012 (uniform across every outcome the seam
        emits, here and in choose_item): **"parked" retains the staging file** — it IS
        the copy the owner will resolve — while **"landed" and "skipped" are safe to
        clean** (landed left its original behind a copy; skipped never entered the
        library and isn't wanted).
        """
        for task, match, dominance in self._accepted:
            skipped = bool(getattr(task, "skip", False))
            source = self._tag_sources.get(id(task), {"kind": "acoustid", "record": None})
            if skipped:
                logger.info(
                    "accepted %s but beets skipped it (duplicate) — not landed",
                    self.staging_path,
                )
            # T-222 (ADR-033): year/genre/lyrics are non-path tags, resolved onto the item
            # in-memory from the source (no file write here — the mutagen writer below
            # persists them). Shazam-backed → the widened Shazam record (no MusicBrainz);
            # AcoustID-only → the ADR-014 MusicBrainz release-year stamp, as before (and no
            # genre/lyrics — with the plugins gone, Shazam is the only free source, T-224).
            if not skipped:
                if source["kind"] == "shazam":
                    self._apply_shazam_tags(task.item, source["record"])
                else:
                    self._stamp_original_year(task.item, match.info.track_id)
            # T-223 (ADR-033): the ONE write on the land path — mutagen writes the
            # authoritative ID3 tags + APIC cover (no beets `write`, no `embedart`). The
            # cover comes from the resolved source: Shazam's `art_url` → the YouTube
            # thumbnail (centre-cropped square), or the AcoustID recording's releases via
            # Cover Art Archive. Best-effort: it never un-lands a track, and `art_embedded`
            # reflects whether the APIC frame actually landed.
            if skipped:
                art_embedded = False
            else:
                image = self._resolve_cover(task.item, dominance, source)
                art_embedded = self._write_landed_tags(task.item, image)
            # T-013 rich payloads, read at the one moment they're all true: post-run,
            # so task.item carries the applied tags AND its final organized path, and
            # match.info is the candidate we chose to apply. Only for a real landing —
            # a skip lands nothing, so it carries none of them (the receipt must not
            # imply a file that isn't there).
            self.outcomes.append(
                Outcome(
                    "skipped" if skipped else "landed",
                    top_score=dominance.top_score,
                    gap=dominance.gap,
                    track_id=match.info.track_id,
                    art_embedded=art_embedded,
                    chosen=None if skipped else _chosen_tags(match.info),
                    tags=None if skipped else _landed_tags(task.item, art_embedded),
                    landed_path=None if skipped else _item_path(task.item),
                )
            )
        self._accepted.clear()
        self._tag_sources.clear()
        return self.outcomes

    def _stamp_original_year(self, item, recording_id: str | None) -> None:
        """Set the accepted recording's original-ish release year on the item (ADR-014).

        In-memory only (T-223): the mutagen writer persists it — this just resolves the
        value onto the item that `_landed_tags` and the writer both read. Best-effort: a
        lookup failure or a recording with no dated release leaves the year blank and logs,
        never un-landing a correctly-tagged song. The AcoustID-only tag source; the Shazam
        source uses `_apply_shazam_tags` instead.
        """
        try:
            year, month, day = self.date_fn(recording_id)
        except Exception as exc:  # noqa: BLE001 — a wrong year must not un-land a track
            logger.warning(
                "original-year lookup failed for %s (%s) — landed without a year",
                self.staging_path,
                exc,
            )
            return
        if not year:
            logger.info(
                "no MusicBrainz release date for %s (recording %s) — year left blank",
                self.staging_path,
                recording_id,
            )
            return
        item.year = year
        item.month = month or 0
        item.day = day or 0

    def _apply_shazam_tags(self, item, record: dict) -> None:
        """Set the Shazam record's year + genre + lyrics on a landed item (ADR-033).

        The non-path half of the Shazam tag source (artist/album/title already rode the
        applied match). Year comes from the widened record (a 4-digit int, T-221); genre
        from Shazam's `genres.primary`; lyrics from the record's LYRICS section (clean
        plain lines, T-221). In-memory only — the mutagen writer (T-223) persists all
        three, so there is no separate file write to roll back here. A field Shazam omits
        is left as-is.

        Genre and lyrics used to come from the `lastgenre` / `lyrics` beets plugins;
        T-224 (ADR-033 decision 4) retires them, so the Shazam record is now the only free
        source for both — "write what Shazam supplies free, never a standalone fetcher".
        """
        if record.get("year"):
            item.year = record["year"]
            item.month = 0
            item.day = 0
        if record.get("genre"):
            item.genre = record["genre"]
        if record.get("lyrics"):
            item.lyrics = record["lyrics"]

    def _resolve_cover(self, item, dominance: Dominance, source: dict) -> bytes | None:
        """Fetch cover bytes from the resolved tag source (Door B, T-223). Best-effort.

        Shazam-backed → Shazam's `art_url` (the `coverarthq` already fetched), falling
        back to the YouTube thumbnail centre-cropped square — both plain URLs, no
        release-picking, which is what removes the wrong-cover class. AcoustID-only → the
        Cover Art Archive / iTunes fetch by the landed recording's releases. Returns the
        raw image bytes for the writer to embed, or `None`; any fetch failure logs and
        yields `None` (art is decorative — a hiccup never un-lands a track).
        """
        if source["kind"] != "shazam":
            try:
                return self.art_fn(
                    artist=getattr(item, "artist", "") or "",
                    title=getattr(item, "title", "") or "",
                    release_ids=dominance.top_release_ids,
                )
            except Exception as exc:  # noqa: BLE001 — art must not un-land a track
                logger.warning(
                    "cover art failed for %s (%s) — landed without a cover",
                    self.staging_path,
                    exc,
                )
                return None
        record = source["record"] or {}
        try:
            image = self.shazam_art_fn(record.get("art_url"))
            if image:
                return image  # Shazam's coverarthq is already square album art
            thumb = self.shazam_art_fn(_thumbnail_url(self.source_signals))
            return crop_to_square(thumb) if thumb else None
        except Exception as exc:  # noqa: BLE001 — art must not un-land a track
            logger.warning(
                "shazam cover failed for %s (%s) — landed without a cover",
                self.staging_path,
                exc,
            )
            return None

    def _write_landed_tags(self, item, image: bytes | None) -> bool:
        """Write the item's tags + `image` onto the landed file with mutagen (T-223).

        The single write on the land path — ID3 frames + APIC, no beets `write`/`embedart`
        (ADR-033). Returns whether a cover was embedded. Best-effort at the file level: a
        write failure (or a missing path) never un-lands the already-copied file — it rolls
        the **year** back to beets' sentinel so the `track.done` payload, which reads year
        from the in-memory item, can't report a year the file never got (the F2 discipline
        `_stamp_original_year` used to own). Genre is NOT rolled back: `_landed_tags` reads
        genre straight off the file (`_genre_on_disk`, T-309), so on a failure it already
        reports the file's true genre — a memory rollback there would be a no-op that only
        reads as if it did something (review F3).
        """
        path = getattr(item, "path", None)
        try:
            if not path:
                raise OSError("landed item has no path to tag")
            return self.tag_writer_fn(
                os.fsdecode(path),
                artist=getattr(item, "artist", None),
                albumartist=getattr(item, "albumartist", None),
                album=getattr(item, "album", None),
                title=getattr(item, "title", None),
                year=getattr(item, "year", None) or None,
                genre=getattr(item, "genre", None),
                lyrics=getattr(item, "lyrics", None),
                isrc=getattr(item, "isrc", None),
                image=image,
            )
        except Exception as exc:  # noqa: BLE001 — a write failure must not un-land a track
            item.year = item.month = item.day = 0
            logger.warning(
                "tag write failed for %s (%s) — landed with degraded tags",
                self.staging_path,
                exc,
            )
            return False

    def choose_match(self, task):
        """Album path. R1 imports songs as singletons, so this should not fire;
        if a directory ever yields an album task, park it rather than guess."""
        logger.warning("unexpected album task for %s — parking", self.staging_path)
        self._park(task, list(task.candidates or []), Dominance(0.0, 0.0, ()))
        return Action.SKIP

    def _library_duplicates(self, recording_id: str | None) -> list[library.Item]:
        """Existing library items that are the SAME recording as the incoming song.

        Detection is by MusicBrainz recording id — the same recording under a
        different filename or sloppier tags is caught, and a live take vs the studio
        cut (same artist+title, different recording) is NOT falsely merged. We query
        the library directly here instead of via beets' import duplicate stage because
        that stage's probe never carries the recording id at this point (it's built
        from the match's TrackInfo before the track_id→mb_trackid mapping), so it can
        never see our duplicates. Complete for R1 by construction: every landed copy
        carries an mb_trackid; untagged legacy files are R2 migrate input.
        """
        return items_for_recording(self.lib, recording_id)

    def _resolve_duplicate(
        self, task, existing: list[library.Item], dominance: Dominance
    ):
        """The song is already in the library — park for the owner to decide. T-009.

        R1 is deliberately **non-destructive**: it NEVER auto-deletes the owner's file
        (spec §5's "drop the other" is superseded by ADR-009). beets' own REMOVE path
        would delete the old copy *before* writing the new one with no rollback — a copy
        failure loses both.

        **Always parks, never silently skips** (ADR-009 amendment, 2026-08-04). The
        prior design silently dropped equal-bitrate duplicates — the card showed "Done"
        with no explanation, and a false-positive AcoustID match lost the song with no
        recourse. Since every song this app lands is MP3 320 (ADR-002), the silent-skip
        path fired on *every* duplicate while the park path was structurally unreachable.
        Parking always lets the owner verify the match and catch false positives; for a
        true re-paste, "Keep existing" is one click.
        """
        self._park_duplicate(existing, dominance)
        return Action.SKIP

    def should_resume(self, path) -> bool:
        # Long-lived backend, no interactive prompts: never ask to resume.
        return False

    def get_duplicate_action(self, task, found_duplicates):
        # Fully defuse beets' import duplicate stage. We detect and resolve
        # duplicates ourselves in choose_item (_library_duplicates → _resolve_duplicate)
        # by MusicBrainz recording id. Beets' stage uses a TrackInfo dict whose
        # track_id never maps to mb_trackid, so the dup query compares empty strings
        # and false-matches any library item landed via keep-untagged (empty MBID).
        return DuplicateAction.KEEP

    # --- parking ----------------------------------------------------------

    def _record_review(
        self,
        candidate_ids: list[str],
        rec: str,
        dominance: Dominance,
        candidates: list[dict] | None = None,
        reason: str | None = None,
        contradictions: list[str] | None = None,
    ) -> Review:
        """Create a parked review row + its "parked" Outcome, and log the receipt.

        The one place a review is written, so both park callers — a weak/ambiguous
        match (`_park`) and an indistinguishable duplicate (`_park_duplicate`) — stay
        in lockstep on the row shape and the outcome. They differ only in what fills
        `candidate_ids` and `rec`.

        `candidates` is the rich per-candidate payload for T-013's
        `track.review_required` event (title/artist/…), distinct from the bare
        `candidate_ids` persisted to the row: the DB keeps only MBIDs (ADR-006), while
        the SSE event carries the display fields that are in hand *right now* so the
        card can render without a re-hydration round-trip. A duplicate park has no
        such candidates (it's a "keep which copy?" prompt), so it defaults to empty.

        **`score` is the one exception to "MBIDs only" (T-028 / ADR-010 addendum).**
        The other display fields are re-derivable from a recording lookup; `score` is
        beets' tag distance between *this download* and the candidate, so it exists
        only here, at park time. Dropping it left `GET /api/reviews` returning
        `score: null` forever — the discriminator ADR-010 says the owner picks on,
        absent from the queue that exists to be picked from. The map is derived from
        the same `candidates` rows the event uses, so the stored and streamed scores
        cannot disagree.
        """
        review = self.store.create_review(
            job_id=self.job_id,
            staging_path=self.staging_path,
            query=self.normalized_query,
            candidate_ids=candidate_ids,
            rec=rec,
            candidate_scores={
                row["candidate_id"]: row["score"]
                for row in (candidates or [])
                if row.get("candidate_id") and row.get("score") is not None
            },
            reason=reason,
            contradictions=contradictions,
        )
        self.outcomes.append(
            Outcome(
                "parked",
                top_score=dominance.top_score,
                gap=dominance.gap,
                review_id=review.id,
                rec=rec,
                candidates=candidates or [],
                reason=reason,
                contradictions=contradictions or [],
            )
        )
        logger.info(
            "parking %s as review %s: rec=%s candidates=%d score=%.3f gap=%.3f",
            self.staging_path,
            review.id,
            rec,
            len(candidate_ids),
            dominance.top_score,
            dominance.gap,
        )
        return review

    def _park(self, task, candidates, dominance: Dominance) -> Review:
        """Record candidate IDs + `task.rec` to the reviews table and note it."""
        rec = getattr(task, "rec", None)
        rec_name = rec.name.lower() if isinstance(rec, Recommendation) else str(rec)
        beets_rows = _candidate_rows(candidates)
        # R1.5 reconcile park (T-206): render the candidate rows from the Verdict's ranked,
        # augmented list — beets' candidates ++ any synthetic ISRC entry, in LLM order —
        # and carry the Verdict's discriminators. Rendering ONE ordered list drives both
        # the persisted `candidate_ids` and the live `track.review_required` rows, so the
        # ISRC candidate reaches the owner on the first live card (not only after a reload)
        # and the durable row can never drift from the event (T-206 review, F6). The
        # R1/degrade path has no Verdict, and an evidence-gathering failure leaves the
        # augmented list empty — both keep beets' own rows/order.
        reason: str | None = None
        contradictions: list[str] = []
        rows = beets_rows
        verdict = self.verdict
        if verdict is not None:
            reason = verdict.reason or None
            contradictions = verdict.contradictions
            if self.reconcile_candidates:
                rows = _ranked_candidate_rows(
                    self.reconcile_candidates, verdict.ranking, beets_rows
                )
        # T-208: park at most the top few candidates. T-218 showed weak-match guesses are
        # often wrong (the real answer was off the list — the owner re-searches), so a full
        # fan-out is waste; a small cap keeps the one-click pick for a near-miss, with
        # re-search as the real fallback. The ISRC candidate is never capped out.
        isrc_mbid = next(
            (
                c["mbid"]
                for c in self.reconcile_candidates
                if c.get("source") == "isrc" and c.get("mbid")
            ),
            None,
        )
        rows = _cap_park_rows(rows, isrc_mbid)
        candidate_ids = [row["candidate_id"] for row in rows if row["candidate_id"]]
        # The rich rows ride along for T-013's event only — the row still persists IDs
        # alone. Both come off `rows`, so the event and the row can never disagree.
        return self._record_review(
            candidate_ids,
            rec_name,
            dominance,
            candidates=rows,
            reason=reason,
            contradictions=contradictions,
        )

    def _park_duplicate(self, duplicates, dominance: Dominance) -> Review:
        """Park a higher-bitrate duplicate the owner must resolve — an upgrade (T-009).

        Shares the reviews table and UI with a weak-match park, marked by
        `rec="duplicate"` so T-014/T-017 render it as "you already have this — keep
        which?" instead of a candidate list. The competing existing copy is
        recoverable from its MusicBrainz recording id (how it was detected as a
        duplicate) via the beets library, so no extra column is needed:
        `candidate_ids` carries the existing recording id(s), `staging_path` the new
        copy awaiting the owner's call.
        """
        existing_ids = [
            mbid
            for dup in duplicates
            if (mbid := getattr(dup, "mb_trackid", None))
        ]
        return self._record_review(existing_ids, "duplicate", dominance)


def items_for_recording(lib, recording_id: str | None) -> list:
    """Library items whose MusicBrainz recording id is `recording_id` (or []).

    The one query that answers "is this recording already in the library" — shared by
    the acquire-time gate (`_library_duplicates`, T-009) and T-014's `replace`, which
    must name the exact existing files it is about to delete. Module-level so the
    resolve orchestration can ask without standing up a session.
    """
    if lib is None or not recording_id:
        return []
    return list(lib.items(dbcore.query.MatchQuery("mb_trackid", recording_id)))


def _shazam_corroborates(record: dict, info) -> bool:
    """Does the Shazam `record` support the landed identity `info` on artist AND title?

    A pure function of `(record, info)` — the re-derived "Shazam is among the agreeing
    senses" test for the land tail. A loose alnum-fold match (`normalize.loose_match`, the
    shared sense-gate matcher) of the record's artist/title against the recording being
    landed; BOTH must match. A Shazam that named a different song (the cover-over-a-master
    case) does NOT corroborate and its tags are not trusted; the ISRC-sourced land IS
    Shazam's own identity, so it matches by construction.
    """
    return bool(
        normalize.loose_match(record.get("shazam_artist"), getattr(info, "artist", None))
        and normalize.loose_match(record.get("shazam_title"), getattr(info, "title", None))
    )


def _thumbnail_url(signals: SourceSignals | None) -> str | None:
    """The YouTube thumbnail URL for a source's video — the T-222 art fallback.

    `hqdefault.jpg` always exists for a valid video id (unlike `maxresdefault`, which
    404s on older uploads). Centre-cropping it to a square is deferred to the mutagen
    writer (T-223); here it is only the fallback cover URL when Shazam has no `art_url`.
    """
    video_id = getattr(signals, "video_id", None) if signals else None
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg" if video_id else None


def _matching_candidate(candidates, recording_ids: tuple[str, ...]):
    """First candidate whose recording MBID is in the dominant fingerprint's set.

    This is what makes the gate *fingerprint*-trust and not distance-trust: we
    only auto-accept a beets candidate that IS the winning acoustic identity.
    """
    if not recording_ids:
        return None
    wanted = set(recording_ids)
    for candidate in candidates:
        if getattr(candidate.info, "track_id", None) in wanted:
            return candidate
    return None


def _cached_track_for_id(recording_id: str | None, cache: dict | None = None):
    """Full MusicBrainz hydration for one recording id, memoized per track (T-208).

    The ONE place a full `track_for_id` runs for the seam, so every hydration routes
    through it and same-MBID repeats within a track (T-218 saw the same id fetched
    twice, uncached) collapse before reaching MusicBrainz's 1/sec limiter. `cache` is a
    per-session dict — one session is one song, so there is no staleness question;
    `None` disables memoization for callers with no session. A `None` result (the id no
    longer resolves) is cached too, so a dead id isn't re-fetched.
    """
    if not recording_id:
        return None
    if cache is not None and recording_id in cache:
        return cache[recording_id]
    info = metadata_plugins.track_for_id(recording_id, "musicbrainz")
    if cache is not None:
        cache[recording_id] = info
    return info


def match_for_recording(task, recording_id: str | None, *, cache: dict | None = None):
    """A `TrackMatch` for `recording_id`, from `task.candidates` or a MusicBrainz lookup.

    The one place a settled recording id becomes a landable match — shared by the
    reconcile gate's accept (T-205, where the id can be the synthetic ISRC candidate
    beets never generated) and `ResolveSession._forced_match` (the owner's explicit
    pick). Prefers a beets candidate: it carries the full `TrackInfo` (album, year, …)
    a bare recording lookup lacks — but once Steps 2/3 make candidates thin, that
    preference returns a thin match, which `_ensure_full_match` re-hydrates at the accept
    point (kept there deliberately, not here, because the surviving candidate is thin or
    full nondeterministically under beets' plugin ThreadPool). Falls back to a cached
    `track_for_id` for a recording that isn't among this task's candidates. `None` when
    the id no longer resolves.
    """
    if not recording_id:
        return None
    match = _matching_candidate(task.candidates or [], (recording_id,))
    if match is not None:
        return match
    info = _cached_track_for_id(recording_id, cache)
    if info is None:
        return None
    # Distance() is an empty (zero) distance: nothing is being ranked — the identity is
    # settled — and beets only reads it for display/threshold logic a forced match bypasses.
    return TrackMatch(Distance(), info, task.item)


def _candidate_by_n(candidates: list[dict], n: int | None) -> dict | None:
    """The augmented candidate at index `n` (its `n` field), or `None`.

    Resolves the Verdict's `chosen_candidate`/`ranking` indices against the *same*
    augmented list the model was shown, so an index never resolves against a different
    order (T-204's canonical-order guarantee, re-checked here at the gate).
    """
    if n is None:
        return None
    for candidate in candidates:
        if candidate.get("n") == n:
            return candidate
    return None


def _ranked_candidate_ids(candidates: list[dict], ranking: list[int]) -> list[str]:
    """The augmented candidates' MBIDs, `ranking`-order first, the rest appended (T-206).

    Resolves each `ranking` index against the same augmented list the model was shown
    (via `_candidate_by_n`) → the recording MBID to persist, so a restart re-hydrates the
    card in the LLM's order and the synthetic ISRC candidate — absent from beets' own list
    — reaches the row (the F6 gap T-205 left). Every augmented candidate carries a real
    MBID by construction (`reconcile.build_candidates` drops any without one).

    A **reorder, never a filter**: any augmented candidate the ranking omits (or names by a
    stray index that resolved to nothing) is appended in canonical `n` order, so a
    partial/empty ranking can never make a real, pickable candidate silently vanish from
    the review row. Returns [] only when there are no augmented candidates at all.
    """
    ids: list[str] = []
    for n in ranking:
        candidate = _candidate_by_n(candidates, n)
        mbid = candidate.get("mbid") if candidate else None
        if mbid and mbid not in ids:
            ids.append(mbid)
    for candidate in candidates:  # append any un-ranked candidate — reorder, not filter
        mbid = candidate.get("mbid")
        if mbid and mbid not in ids:
            ids.append(mbid)
    return ids


PARK_CANDIDATE_LIMIT = 3  # T-208: the review card's pick-list cap


def _cap_park_rows(rows: list[dict], isrc_mbid: str | None) -> list[dict]:
    """The top `PARK_CANDIDATE_LIMIT` park rows, always keeping the ISRC row (T-208).

    Rows arrive best-first (the reconcile ranking, or beets' distance order). Capping to
    the top few keeps a one-click pick for a near-miss without persisting a full fan-out;
    re-search (`POST /api/reviews/{id}/search`) is the fallback when none fit. The ISRC
    candidate, if the ranking pushed it past the cap, displaces the last kept row rather
    than dropping — it is the ADR-021 marquee-correction vehicle and never expendable.
    """
    if len(rows) <= PARK_CANDIDATE_LIMIT:
        return rows
    capped = rows[:PARK_CANDIDATE_LIMIT]
    if isrc_mbid and not any(r.get("candidate_id") == isrc_mbid for r in capped):
        isrc_row = next(
            (r for r in rows if r.get("candidate_id") == isrc_mbid), None
        )
        if isrc_row is not None:
            capped = capped[: PARK_CANDIDATE_LIMIT - 1] + [isrc_row]
    return capped


def _ranked_candidate_rows(
    candidates: list[dict], ranking: list[int], beets_rows: list[dict]
) -> list[dict]:
    """The augmented candidates as spec §6 rows, in `ranking` order (T-206).

    The SSE/persistence counterpart to `_ranked_candidate_ids`: it renders the SAME set,
    in the SAME order (it reuses that function so the order can't diverge), as
    `candidate_row` dicts — so the live `track.review_required` event and the durable row
    show one identical, ranked candidate list, the synthetic ISRC entry included.

    `score` (beets' tag distance, 1 − distance) is a property of *this download* vs a
    candidate, not of the recording, so it exists only on `beets_rows`; it's carried over
    by MBID. The ISRC entry is not a beets candidate and has no such distance → its score
    is null, exactly as a re-hydrated ISRC candidate reads from `GET /api/reviews`.
    """
    scores = {
        row["candidate_id"]: row.get("score")
        for row in beets_rows
        if row.get("candidate_id")
    }
    by_mbid = {c["mbid"]: c for c in candidates if c.get("mbid")}
    rows: list[dict] = []
    for mbid in _ranked_candidate_ids(candidates, ranking):
        cand = by_mbid.get(mbid)
        if cand is None:
            continue
        rows.append(
            candidate_row(
                mbid,
                title=cand.get("title"),
                artist=cand.get("artist"),
                score=scores.get(mbid),
            )
        )
    return rows


def _is_auth_error(exc: Exception) -> bool:
    """True for an auth/permission rejection (a bad or expired ANTHROPIC_APIKEY).

    Detected structurally — an HTTP 401/403 `status_code`, or the Anthropic SDK's
    `AuthenticationError`/`PermissionDeniedError` class name — so this module needn't
    import `anthropic`, and a test stub can raise a plain object carrying
    `status_code=401`. A rejected key degrades to the R1 gate (spec §6); every other
    failure parks (see `_reconcile`).
    """
    if getattr(exc, "status_code", None) in (401, 403):
        return True
    return type(exc).__name__ in ("AuthenticationError", "PermissionDeniedError")


# --- T-009: acquire-time duplicate quality ----------------------------------
#
# When an incoming song is the same recording as one already in the library
# (`_library_duplicates`, by MusicBrainz recording id), R1 keeps the existing file
# and never auto-deletes it (ADR-009). The only quality axis compared at this point
# is **bitrate**: it's a real property of the staged file, whereas tags aren't
# applied yet — and for the same recording both copies get identical tags anyway, so
# tag richness can't legitimately differentiate an acquire-time duplicate. (Comparing
# two already-tagged files by tag richness / acoustic fingerprint is the R2 migrate
# job.) An existing copy at >= bitrate → keep it, drop the download; a strictly
# higher-bitrate download → park for the owner, never delete.


def _bitrate(item) -> int:
    """A copy's bitrate in bits/sec (0 if unknown). Read via getattr so a real beets
    `Item` and a test double both work."""
    return int(getattr(item, "bitrate", 0) or 0)


# --- T-013: shaping the seam's data into spec §6 payloads -------------------
#
# Read straight off the objects the seam already holds — the chosen `TrackMatch`,
# the landed beets `Item`, the beets candidates at park time. Everything is `getattr`
# with a null default so a real beets object and a bare test double both work, and a
# genuinely-absent field degrades to null rather than fabricating a value.


def _chosen_tags(info) -> dict:
    """spec §6 `track.tagging.chosen`: what the gate decided to apply (the match)."""
    return {
        "title": getattr(info, "title", None),
        "artist": getattr(info, "artist", None),
        "album": getattr(info, "album", None),
        "year": getattr(info, "year", None) or None,
    }


def _genre_on_disk(item) -> str | None:
    """The genre tag read back off the landed file — the authoritative value (T-309).

    Genre is now the Shazam record's genre, stamped by the mutagen writer (T-224/ADR-033;
    it used to be `lastgenre`'s Last.fm write). Reading it back off the file is still the
    truth of "what actually landed" — robust to any drift between the in-memory `item.genre`
    and the bytes on disk (the T-103 discrepancy that motivated this: `item.genre` None
    while the file carried `'Soul'`). Best-effort and guarded like the other read-off-disk
    helpers — a missing path or read error degrades to the in-memory field rather than
    lying either way (a bare/absent genre is a documented degrade, spec §6, not a failure).

    Disk wins when it carries a genre, but a *bare* disk tag does not shadow a present
    in-memory value: report a genre if either source has one (T-309, review Finding 3).
    """
    path = getattr(item, "path", None)
    if path:
        try:
            from mediafile import MediaFile

            disk = MediaFile(os.fsdecode(path)).genre
            if disk:
                return disk
        except Exception as exc:  # noqa: BLE001 — an unreadable tag must not un-land a track
            logger.debug("could not read genre off %s (%s)", path, exc)
    return getattr(item, "genre", None)


def _landed_tags(item, has_art: bool) -> dict:
    """spec §6 `track.done.tags`: what actually landed on the file, post-organize.

    `genre` is the Shazam genre the mutagen writer stamped, read back OFF THE LANDED FILE
    (T-309) — the file is the source of truth (null when Shazam didn't cover the track — a
    documented degrade, not a failure, spec §6). `has_art` is Door B's own result (whether
    a cover was embedded), passed in rather than re-read off disk. `has_lyrics` is the
    presence of the Shazam record's lyrics on the item (T-224 — the `lyrics` plugin is gone).
    """
    return {
        "title": getattr(item, "title", None),
        "artist": getattr(item, "artist", None),
        "album": getattr(item, "album", None),
        "year": getattr(item, "year", None) or None,
        "genre": _genre_on_disk(item) or None,
        "has_art": has_art,
        "has_lyrics": bool(getattr(item, "lyrics", None)),
    }


def _item_path(item) -> str | None:
    """The landed file's path as text. beets item paths are bytes; decode to the same
    TEXT form the review row uses so the event and the DB agree."""
    path = getattr(item, "path", None)
    return os.fsdecode(path) if path else None


def _candidate_rows(candidates) -> list[dict]:
    """spec §6 `track.review_required.candidates[]`, from the beets candidates in hand.

    Built at park time from the candidates the seam already has — NOT re-hydrated from
    stored MBIDs (that's T-014's `GET /api/reviews` path). Both paths yield the same
    three fields, because both bottom out in the same recording lookup.

    - **No album / year / art_url (ADR-010).** These are *release* properties; a
      singleton candidate is a *recording* (`item_candidates` → `tracks_for_ids` →
      `track_for_id` → `track_info(recording)`), and one recording is on many releases.
      They were emitted as null here from T-007 to 2026-07-17 with a note saying
      "T-014/T-017 fill it when the owner views the queue" — **they don't; that was
      withdrawn.** Filling them needs a browse-releases call per candidate plus a
      which-release heuristic, which ADR-010 rejects (T-008: 88% auto-accept, and the
      queue's real traffic is no-match songs that title+artist already separates).
      Don't re-add the fields; read the ADR first if you're about to.
    - **`score` is `1 − beets' tag distance`** (0 distance = perfect = score 1.0), the
      only per-candidate confidence beets exposes here — and therefore *the*
      discriminator when two candidates read alike. It is NOT the acoustic fingerprint
      score (that's a single number for the whole match, not per candidate). Absent on
      a bare double → null.
    """
    rows: list[dict] = []
    for candidate in candidates:
        info = getattr(candidate, "info", None)
        if info is None:
            continue
        distance = getattr(candidate, "distance", None)
        rows.append(
            candidate_row(
                getattr(info, "track_id", None),
                title=getattr(info, "title", None),
                artist=getattr(info, "artist", None),
                score=(1.0 - float(distance)) if distance is not None else None,
            )
        )
    return rows


# --- driving beets ----------------------------------------------------------


def _configure_import_options() -> None:
    """Set the import options for a non-interactive, singleton, copy-in import.

    Every value here has a reason: singletons because a YouTube rip is always a
    lone track; autotag so candidates are looked up; copy+write so the tagged
    file lands in the library and staging survives for T-012 to clean up; the
    non-interactive flags so `choose_item` is the *only* per-song identity decision —
    which is also where T-009 does duplicate handling (against the library directly),
    so beets' own import duplicate stage is neutralised (see duplicate_keys below).
    threaded=False keeps beets' pipeline in our caller's thread — T-012 owns the
    worker thread, and ADR-001 forbids parallelizing the pipeline anyway.
    """
    imp = config["import"]
    imp["singletons"].set(True)
    imp["autotag"].set(True)
    imp["copy"].set(True)
    imp["move"].set(False)
    # T-223 (ADR-033): beets is retired from tag-writing. It still copies + organizes the
    # file (by the item's applied fields), but the tags + cover are written by the mutagen
    # ID3 writer in finalize (`_write_landed_tags`), NOT beets' `write` stage / `embedart`.
    # "No beets tag-write on the path" is this line. (Plugin teardown is T-224.)
    imp["write"].set(False)
    imp["resume"].set(False)
    imp["incremental"].set(False)
    imp["quiet"].set(False)
    imp["timid"].set(False)
    imp["group_albums"].set(False)
    # T-009: neutralise beets' own import duplicate stage — we detect and resolve
    # duplicates ourselves in choose_item (`_library_duplicates`, by recording id).
    # beets' stage can't do it: its probe is built from the match's TrackInfo, whose
    # recording id lives under `track_id`, *before* the track_id→mb_trackid mapping, so
    # a `duplicate_keys` query on mb_trackid always finds nothing (verified). Setting
    # the key to mb_trackid makes that stage a guaranteed no-op — so it never acts on a
    # false artist+title match (a live take vs the studio cut) behind our back — while
    # our choose_item query stays the single source of truth. duplicate_action is then
    # only beets' unreached fallback; kept a valid value so as_choice never trips.
    imp["duplicate_keys"]["item"].set("mb_trackid")
    imp["duplicate_action"].set("skip")
    config["threaded"].set(False)

    # ADR-013: the accepted identity is the sole source of a landed track's tags — never
    # yt-dlp's `--embed-metadata` junk. `from_scratch` makes apply clear the item before
    # applying the match, so a field the match doesn't supply lands BLANK instead of keeping
    # the YouTube value. Without it the singleton path keeps the junk: genre = YouTube's
    # category (TCON="Music", T-021) and a wrong year (a 1996 track stamped 2026, T-025) both
    # survive because item_data drops the None fields the match leaves unset. Item.clear()
    # spares audio properties (models.py:717) and runs before apply, so it wipes only stale
    # tags, never one the match or the mutagen writer will set. (Pre-T-224 it also ran before
    # the genre/lyrics/art plugin stages; those plugins are retired — tags land via
    # `_apply_shazam_tags` + the mutagen writer in finalize, not plugin stages.)
    imp["from_scratch"].set(True)

    # T-224 (ADR-033): the `lyrics` plugin is gone — lyrics now come from the Shazam
    # record (`_apply_shazam_tags`), so there is no `config["lyrics"]` to tune here.


def _beets_library_path(settings: Settings) -> Path:
    """beets' own item DB (distinct from our app DB) — next to it under data/."""
    return settings.db_path.parent / "beets_library.db"


def get_library(settings: Settings | None = None) -> library.Library:
    """The beets Library that imports land in, organized under the watched folder.

    Separate from the app's SQLite store (T-002): this is beets' catalogue of
    imported items, used to organize into `LIBRARY_DIRECTORY` and (T-009) to
    detect duplicates on re-import.
    """
    s = settings or get_settings()
    configure_beets(s)
    db_path = _beets_library_path(s)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return library.Library(str(db_path), LIBRARY_DIRECTORY)


# --- T-014: resuming a parked import on the owner's decision -----------------


class ResolveError(Exception):
    """The owner's chosen recording could not be turned into a match to apply.

    Distinct from a beets failure: it means the MBID the owner picked resolves to
    nothing (MusicBrainz merged or removed the recording since the park — documented
    data drift, see learnings 2026-07-12), so there is no metadata to land. The caller
    surfaces it as a resolve error and leaves the review in the queue.
    """


class ResolveSession(FingerprintTrustSession):
    """Re-imports a parked staging file applying the recording the OWNER chose (T-014).

    The acquire-time gate asks "what is this song?" and parks when it can't be sure.
    By the time we get here that question is answered — by a click — so this session
    does **not** re-run the gate. It overrides `choose_item` to force one specific
    recording and never parks, never dedups:

    - **No fingerprint lookup.** The identity is settled; re-running `dominance_fn`
      would spend an AcoustID call to re-derive an answer we were handed. Outcomes
      carry a zero `Dominance`, which is honest — no fingerprint was consulted.
    - **No duplicate check, deliberately.** For `replace` and `keep_both` the incoming
      song IS a known duplicate — that is *why* it parked — so re-running T-009's check
      would park it again, forever (the resolve would be unimplementable). ADR-009's
      addendum settles the principle: an explicit owner click is the consent the
      never-auto-delete rule was protecting, so a chosen recording lands. The same
      applies to a weak-match accept whose candidate happens to be in the library
      already: the owner picked it, so it lands.

    `suffix` (the `keep_both` branch) is appended to the **title tag** before beets
    applies the match, never to the filename — Jellyfin renders tags, so two files
    distinguished only on disk are two identical rows (spec §5). beets derives the
    path from the tags, so the filename follows for free and beets' own sanitizer
    handles characters that are illegal on disk.

    Inherits `finalize_outcomes` (so a landed/skipped receipt is settled post-`run()`
    exactly as on the acquire path) and its mutagen writer (T-223). Its `_tag_sources`
    is never set, so it takes the AcoustID branch — tags stamped from the applied match +
    the ADR-014 year, cover via `_resolve_cover`. Art degrades to the iTunes artist+title
    fallback here: Cover Art Archive is keyed by the *release* MBIDs the fingerprint
    lookup returns, and we deliberately don't run one — a cover is decorative and doesn't
    justify an AcoustID round-trip on a settled identity.
    """

    def __init__(self, lib, *, recording_id: str, suffix: str | None = None, **kwargs):
        # dominance_fn is never called (choose_item is fully overridden); pass a
        # poison default so a future edit that reaches for it fails loudly rather
        # than silently spending an AcoustID lookup on the resolve path.
        kwargs.setdefault("dominance_fn", _no_dominance)
        super().__init__(lib, **kwargs)
        self.recording_id = recording_id
        self.suffix = suffix

    def choose_item(self, task):
        """Apply the owner's recording. Raises rather than parks — a park here would
        put the song straight back in the queue it was just resolved out of."""
        match = self._forced_match(task)
        if match is not None:
            # T-208: the owner's pick can resolve to a thin beets candidate (Steps 2/3);
            # this path bypasses _accept, so hydrate here too or a resolve lands hollow.
            match = self._ensure_full_match(task, match)
        if match is None:
            raise ResolveError(
                f"recording {self.recording_id} no longer resolves at MusicBrainz"
            )
        if self.suffix:
            match = _with_title_suffix(match, self.suffix)
        # ADR-028 (T-308): the resolve path bypasses _accept — fold here too, or it
        # silently keeps writing the stylised credit.
        match = canonicalize_credit(match)
        self._accepted.append((task, match, Dominance(0.0, 0.0, ())))
        logger.info(
            "resolving %s onto recording %s%s",
            self.staging_path,
            self.recording_id,
            f" with suffix {self.suffix!r}" if self.suffix else "",
        )
        return match

    def _forced_match(self, task) -> TrackMatch | None:
        """A `TrackMatch` for `self.recording_id` (the owner's explicit pick).

        Thin wrapper over the shared `match_for_recording`: prefers a beets candidate
        for its full `TrackInfo`, falls back to `track_for_id` when the candidate list
        drifted since the park or the row's recording is the existing library copy's (a
        duplicate park, never in this task's candidates). `None` if it no longer resolves.
        """
        return match_for_recording(
            task, self.recording_id, cache=self._trackinfo_cache
        )


def _no_dominance(*args, **kwargs):
    raise AssertionError(
        "ResolveSession must not run a fingerprint lookup — the identity is the "
        "owner's explicit choice, not something to re-derive"
    )


def _with_title_suffix(match: TrackMatch, suffix: str) -> TrackMatch:
    """`match` with `suffix` appended to its title tag (the `keep_both` branch).

    Deep-copies the `TrackInfo` first: it can be an object beets cached or shares with
    another candidate, and mutating it in place would leak the suffix into anything
    else holding the same reference. beets applies `info.item_data` onto the item, so
    a suffixed title here is what gets written to the file AND what the path template
    (`$artist/$title`) derives from — one edit, both effects.
    """
    info = copy.deepcopy(match.info)
    info.title = f"{(info.title or '').strip()} {suffix}".strip()
    return TrackMatch(match.distance, info, match.item)


# Credit fields on a matched TrackInfo that name the artist's canonical identity
# and drive BOTH the ID3 write and the path template ($artist / $albumartist). A
# singleton TrackInfo carries `artist`/`artist_credit`; the `albumartist` variants
# appear on a merged album match — fold whichever are present and set (ADR-028).
_CREDIT_FIELDS = ("artist", "artist_credit", "albumartist", "albumartist_credit")


def canonicalize_credit(match: TrackMatch) -> TrackMatch:
    """`match` with its artist credit folded to the owner's canonical identity (ADR-028).

    Deep-copies the `TrackInfo` first — it can be a beets-cached object shared
    across candidates, and mutating it in place would leak the fold into anything
    else holding the reference (the same hazard `_with_title_suffix` guards).
    beets applies `info.item_data` onto the item, so the single edit drives BOTH
    the ID3 `artist`/`albumartist` write AND the path template — one edit, both
    effects, closing the clean-tag/wrong-folder split a path-only fix would leave.

    Emits ONE structured log line when any codepoint changes, so a fold that fires
    (or mis-fires) is never silent (ADR-028 observability clause).
    """
    # Compute the folds off the ORIGINAL first, so a credit that needs no fold —
    # the common case, and every path that discards the match (a duplicate) — pays
    # no deep-copy. Only a real change copies + mutates.
    changed = {}
    for name in _CREDIT_FIELDS:
        before = getattr(match.info, name, None)
        if not isinstance(before, str):
            continue
        after = normalize.canonical_credit(before)
        if after != before:
            changed[name] = (before, after)
    if not changed:
        return match
    info = copy.deepcopy(match.info)
    for name, (_before, after) in changed.items():
        setattr(info, name, after)
    logger.info(
        "canonicalized artist credit (ADR-028): %s",
        ", ".join(f"{n} {b!r}→{a!r}" for n, (b, a) in changed.items()),
    )
    return TrackMatch(match.distance, info, match.item)


def resolve_import(
    staging_path: bytes | str,
    *,
    store: Store,
    job_id: str,
    recording_id: str,
    query: str = "",
    suffix: str | None = None,
    lib: library.Library | None = None,
    settings: Settings | None = None,
) -> list[Outcome]:
    """Land a parked staging file as `recording_id` (T-014). The resolve twin of `import_song`.

    Same beets driving, same receipt shape — only the decision differs: `import_song`
    asks the fingerprint gate, this applies the owner's answer. Raises `ResolveError`
    if the chosen recording can't be resolved to metadata; any other exception is a
    genuine beets apply/organize failure and belongs to the caller's `land` stage.
    """
    s = settings or get_settings()
    configure_beets(s)
    _configure_import_options()
    lib = lib or get_library(s)

    session = ResolveSession(
        lib,
        store=store,
        job_id=job_id,
        staging_path=staging_path,
        query=query,
        recording_id=recording_id,
        suffix=suffix,
    )
    session.run()
    return session.finalize_outcomes()


class KeepUntaggedSession(FingerprintTrustSession):
    """Imports a parked staging file as-is with owner-supplied tags (ADR-020 exit 2).

    The owner has looked at the candidates, searched MusicBrainz themselves, and
    decided the recording genuinely isn't in the database. This session writes the
    owner's tags to the file and returns `Action.ASIS` — beets organizes it per the
    path template and registers it in the library, but applies no MusicBrainz match.

    Consequences per ADR-020:
    - No `mb_trackid` (no fabricated MBID, no borrowed release).
    - No cover art and no auto-genre/lyrics — those came from the accepted identity
      (Shazam / a release lookup), and a keep-untagged file has no accepted identity.
      (Pre-T-224 the same held via the retired fetchart/lastgenre/lyrics plugins.)
    - `ftintitle` still fires (it reads the item's tags, not the match).

    The junk yt-dlp embedded (channel name, upload date, genre "Entertainment") is
    cleared before import — ADR-013's intent, even though `from_scratch` only fires
    for matched imports.
    """

    def __init__(
        self,
        lib,
        *,
        manual_title: str,
        manual_artist: str,
        manual_album: str | None = None,
        manual_year: int | None = None,
        **kwargs,
    ):
        kwargs.setdefault("dominance_fn", _no_dominance)
        super().__init__(lib, **kwargs)
        self.manual_title = manual_title
        self.manual_artist = manual_artist
        self.manual_album = manual_album
        self.manual_year = manual_year

    def choose_item(self, task):
        """Write the owner's tags and accept as-is."""
        self._write_manual_tags(task.item)
        self._accepted.append((task, None, Dominance(0.0, 0.0, ())))
        logger.info(
            "keep-untagged %s: artist=%r title=%r",
            self.staging_path,
            self.manual_artist,
            self.manual_title,
        )
        return Action.ASIS

    def _write_manual_tags(self, item) -> None:
        """Clear yt-dlp junk and write the owner's fields onto the staging file."""
        from mutagen import File as MutagenFile

        audio = MutagenFile(os.fsdecode(item.path), easy=True)
        if audio is None:
            raise ResolveError(
                f"cannot read the staging file's tags — is it a valid MP3? "
                f"({os.fsdecode(item.path)})"
            )
        audio.delete()
        audio["title"] = self.manual_title
        audio["artist"] = self.manual_artist
        if self.manual_album:
            audio["album"] = self.manual_album
        if self.manual_year:
            audio["date"] = str(self.manual_year)
        audio.save()

        item.title = self.manual_title
        item.artist = self.manual_artist
        if self.manual_album:
            item.album = self.manual_album
        if self.manual_year:
            item.year = self.manual_year

    def finalize_outcomes(self) -> list[Outcome]:
        """Settle the as-is import — same shape as the matched path."""
        for task, _match, dominance in self._accepted:
            skipped = bool(getattr(task, "skip", False))
            if skipped:
                logger.info(
                    "keep-untagged %s but beets skipped it — not landed",
                    self.staging_path,
                )
            else:
                # T-223 (ADR-033): beets' `write` is off, so re-persist the item's tags
                # with mutagen post-run. This is load-bearing here, not just tidy: the
                # `imported` stage runs `ftintitle` (ADR-012), which splits a "feat." credit
                # out of the artist field IN MEMORY during run() — with beets no longer
                # writing, that split would otherwise never reach the file. `_write_manual_tags`
                # seeded the staging copy; this writes the final, ftintitle-adjusted tags.
                self._write_landed_tags(task.item, None)
            art_embedded = False
            self.outcomes.append(
                Outcome(
                    "skipped" if skipped else "landed",
                    top_score=0.0,
                    gap=0.0,
                    track_id=None,
                    art_embedded=art_embedded,
                    chosen={
                        "title": self.manual_title,
                        "artist": self.manual_artist,
                        "album": self.manual_album,
                        "year": self.manual_year,
                    },
                    tags=None if skipped else _landed_tags(task.item, art_embedded),
                    landed_path=None if skipped else _item_path(task.item),
                )
            )
        self._accepted.clear()
        return self.outcomes


def resolve_asis_import(
    staging_path: bytes | str,
    *,
    store: Store,
    job_id: str,
    query: str = "",
    manual_title: str,
    manual_artist: str,
    manual_album: str | None = None,
    manual_year: int | None = None,
    lib: library.Library | None = None,
    settings: Settings | None = None,
) -> list[Outcome]:
    """Land a parked staging file with owner-supplied tags (ADR-020 exit 2).

    The keep-untagged twin of `resolve_import`: same receipt shape, but writes the
    owner's tags instead of forcing a MusicBrainz recording. Raises `ResolveError` on
    a file that can't be read; any other exception is a beets organize failure.
    """
    s = settings or get_settings()
    configure_beets(s)
    _configure_import_options()
    lib = lib or get_library(s)

    session = KeepUntaggedSession(
        lib,
        store=store,
        job_id=job_id,
        staging_path=staging_path,
        query=query,
        manual_title=manual_title,
        manual_artist=manual_artist,
        manual_album=manual_album,
        manual_year=manual_year,
    )
    session.run()
    return session.finalize_outcomes()


def import_song(
    staging_path: bytes | str,
    *,
    store: Store,
    job_id: str,
    query: str,
    lib: library.Library | None = None,
    settings: Settings | None = None,
    score_min: float = SCORE_MIN,
    gap_min: float = GAP_MIN,
    dominance_fn=None,
    source_signals: SourceSignals | None = None,
    shazam_fn=None,
    isrc_fn=None,
    reconcile_fn=None,
) -> list[Outcome]:
    """Run one staged MP3 through the gate. Returns the outcome(s).

    The script-provable entry point for the spine: given a tagged staging file,
    it drives the whole beets import (identify → tag → art/genre/lyrics →
    organize) and either lands the file or parks a review row — no web layer
    required, exactly as the spike proved the seam.

    `source_signals` is sense 1 — the yt-dlp `SourceSignals` (R1.5, T-201) that
    `run_pipeline` threads down from the download stage. **T-201 only carries it to
    this boundary; T-204 wires it into `FingerprintTrustSession` as reconcile
    evidence.** Optional and defaulting to `None` so the ad-hoc/script callers and
    the offline orchestration tests need not supply it.

    Precondition: `job_id` must be a job already persisted via `store.create_job`
    — a parked review's `job_id` is a foreign key into `jobs`. T-012 owns creating
    the job before the pipeline runs.
    """
    s = settings or get_settings()
    configure_beets(s)
    _configure_import_options()
    lib = lib or get_library(s)

    if dominance_fn is None:
        # T-011: run the score-critical lookup on the owner's private AcoustID quota
        # when set, else the shared built-in key — bound here so the session's call
        # site stays key-agnostic and test doubles need no key. Retry/backoff defaults
        # ride along from fingerprint_dominance.
        dominance_fn = functools.partial(
            fingerprint_dominance, api_key=_resolve_api_key(s)
        )

    # R1.5 reconcile seam (T-204). The default reconcile_fn is built from the owner's
    # ANTHROPIC_APIKEY (T-200); absent, make_reconcile_fn returns None and the LLM
    # *adjudication* never runs — the R1 land decision applies (spec §6 degrade). shazam_fn
    # / isrc_fn default to the real senses. T-222 (ADR-033): shazam_fn now fires on EVERY
    # track (the tag/art source, gathered in choose_item, independent of reconcile_fn);
    # isrc_fn still fires only inside `_reconcile`, so only when a reconcile_fn exists.
    if reconcile_fn is None:
        reconcile_fn = reconcile_seam.make_reconcile_fn(s)
    if shazam_fn is None:
        shazam_fn = shazam_sense.recognize
    if isrc_fn is None:
        isrc_fn = isrc_lookup.isrc_to_mb

    session = FingerprintTrustSession(
        lib,
        store=store,
        job_id=job_id,
        staging_path=staging_path,
        query=query,
        score_min=score_min,
        gap_min=gap_min,
        dominance_fn=dominance_fn,
        source_signals=source_signals,
        shazam_fn=shazam_fn,
        isrc_fn=isrc_fn,
        reconcile_fn=reconcile_fn,
    )
    session.run()
    # Finalize AFTER run(): only now is a "landed" accept distinguishable from one
    # beets' duplicate stage skipped (finding #2).
    return session.finalize_outcomes()
