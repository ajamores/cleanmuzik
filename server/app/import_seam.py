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

import functools
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

import acoustid
from beets import config, dbcore, library, util
from beets.autotag import Recommendation
from beets.importer import Action, ImportSession

from app.artwork import embed_cover, fetch_cover_art
from app.beets_engine import LIBRARY_DIRECTORY, configure_beets
from app.config import Settings, get_settings
from app.db import Review, Store

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
    seam the single source of truth and the emitter a thin, honest relay. `art_url`
    on a candidate is the one field deliberately left null — see `_candidate_rows`.
    """

    action: str  # "landed" | "skipped" | "parked"
    top_score: float
    gap: float
    track_id: str | None = None  # the accepted recording MBID (landed)
    review_id: str | None = None  # the parked review row id (parked)
    art_embedded: bool = False  # Door B: did a cover land on the file (landed only)
    # --- T-013 SSE payloads, sourced where the data is in hand ------------------
    chosen: dict | None = None  # landed: {title, artist, album, year} of the match
    tags: dict | None = None  # landed: {title,artist,album,year,genre,has_art,has_lyrics}
    landed_path: str | None = None  # landed: the organized library path (str, decoded)
    candidates: list[dict] | None = None  # parked: rich candidate rows for the UI


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
        self.outcomes: list[Outcome] = []
        # Accepted matches await finalization: choose_item can only *decide* to
        # land; whether beets actually copied the file is known only after run()
        # (its duplicate stage may skip it). See finalize_outcomes().
        self._accepted: list[tuple[object, object, Dominance]] = []

    # --- the gate ---------------------------------------------------------

    def choose_item(self, task):
        """The one decision. Return a `TrackMatch` to land, or `Action.SKIP` to park."""
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

        if (
            candidates
            and dominance.top_score >= self.score_min
            and dominance.gap >= self.gap_min
        ):
            match = _matching_candidate(candidates, dominance.top_recording_ids)
            if match is not None:
                # T-009 acquire-time dedup, done HERE rather than via beets' import
                # duplicate stage. beets can't detect our duplicates: its probe is
                # built from the match's TrackInfo (recording id under `track_id`)
                # *before* the track_id→mb_trackid mapping, so a duplicate_keys query
                # on mb_trackid always finds nothing (verified). We already hold the
                # winning recording id and the library, so we query it directly.
                existing = self._library_duplicates(match.info.track_id)
                if existing:
                    return self._resolve_duplicate(task, existing, dominance)

                # Dominant, taggable, and not already in the library. Accept it —
                # but DON'T record "landed" yet: the receipt must not lie if the copy
                # later fails. The real outcome is settled in finalize_outcomes().
                self._accepted.append((task, match, dominance))
                logger.info(
                    "accepting %s: score=%.3f gap=%.3f recording=%s",
                    self.staging_path,
                    dominance.top_score,
                    dominance.gap,
                    match.info.track_id,
                )
                return match
            # Dominant fingerprint but its recording isn't among beets' candidates
            # (rare). Trusting a *different* candidate would betray the fingerprint,
            # so park rather than mis-tag.
            logger.info(
                "dominant fingerprint for %s but no matching candidate — parking",
                self.staging_path,
            )

        self._park(task, candidates, dominance)
        return Action.SKIP

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
            if skipped:
                logger.info(
                    "accepted %s but beets skipped it (duplicate) — not landed",
                    self.staging_path,
                )
            # Door B: fetchart skips singletons, so embed the cover ourselves — but
            # only for a track that actually landed, and never let it un-land one.
            art_embedded = False if skipped else self._embed_art(task.item, dominance)
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
        return self.outcomes

    def _embed_art(self, item, dominance: Dominance) -> bool:
        """Fetch + embed a cover for a landed item. Best-effort (Door B).

        Broad except by design: cover art is decorative, so a fetch/parse/embed
        failure logs and yields False — it must never turn a correctly-tagged,
        already-landed song into a failure.
        """
        try:
            image = self.art_fn(
                artist=getattr(item, "artist", "") or "",
                title=getattr(item, "title", "") or "",
                release_ids=dominance.top_release_ids,
            )
            if not image:
                return False
            embed_cover(item, image, log=logger)
            return True
        except Exception as exc:  # noqa: BLE001 — art must not un-land a track
            logger.warning(
                "cover art failed for %s (%s) — landed without a cover",
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
        if self.lib is None or not recording_id:
            return []
        return list(self.lib.items(dbcore.query.MatchQuery("mb_trackid", recording_id)))

    def _resolve_duplicate(
        self, task, existing: list[library.Item], dominance: Dominance
    ):
        """The song is already in the library — keep the existing copy, or park. T-009.

        R1 is deliberately **non-destructive**: it NEVER auto-deletes the owner's file
        (spec §5's "drop the other" is superseded by ADR-009). beets' own REMOVE path
        would delete the old copy *before* writing the new one with no rollback — a copy
        failure loses both. So the only two outcomes here both keep every existing file:

        - **an existing copy is at least as good → SKIP the new one.** The everyday
          re-paste: the fresh rip is the same recording at the same MP3-320 bitrate, and
          the library copy is already tagged, so the new copy adds nothing. Dropped, no
          second copy (spec §7). We compare on **bitrate only** — the one axis that's
          honest at this point (tags aren't applied yet, and for the same recording both
          copies get identical tags anyway). Tag-richness / acoustic tie-breaks are R2
          migrate, where two already-tagged files are genuinely compared.
        - **the new copy has a strictly higher bitrate than every existing one → park.**
          A genuine upgrade, but replacing means deleting, so hand the choice to the
          owner via the review queue ("you already have this — keep which?") rather than
          delete automatically. Returns Action.SKIP either way, so beets never lands a
          second file; the parked new file waits in staging for the owner's call.
        """
        new_bitrate = _bitrate(task.item)
        if any(_bitrate(item) >= new_bitrate for item in existing):
            # An existing copy is as good or better — keep it, drop the redundant
            # download. Emit "skipped" directly (this never entered _accepted): the new
            # copy didn't land, and its staging file is safe for T-012 to clean up.
            logger.info(
                "duplicate of %s already in library at >= bitrate (%d) — keeping "
                "existing, skipping the new copy",
                self.staging_path,
                new_bitrate,
            )
            self.outcomes.append(
                Outcome(
                    "skipped",
                    top_score=dominance.top_score,
                    gap=dominance.gap,
                )
            )
            return Action.SKIP

        # New copy out-qualities every existing one (higher bitrate). Never auto-delete
        # — park for the owner to confirm the replacement.
        self._park_duplicate(existing, dominance)
        return Action.SKIP

    def should_resume(self, path) -> bool:
        # Long-lived backend, no interactive prompts: never ask to resume.
        return False

    # --- parking ----------------------------------------------------------

    def _record_review(
        self,
        candidate_ids: list[str],
        rec: str,
        dominance: Dominance,
        candidates: list[dict] | None = None,
    ) -> Review:
        """Create a parked review row + its "parked" Outcome, and log the receipt.

        The one place a review is written, so both park callers — a weak/ambiguous
        match (`_park`) and an indistinguishable duplicate (`_park_duplicate`) — stay
        in lockstep on the row shape and the outcome. They differ only in what fills
        `candidate_ids` and `rec`.

        `candidates` is the rich per-candidate payload for T-013's
        `track.review_required` event (title/artist/album/…), distinct from the bare
        `candidate_ids` persisted to the row: the DB keeps only MBIDs (ADR-006), while
        the SSE event carries the display fields that are in hand *right now* so the
        card can render without a re-hydration round-trip. A duplicate park has no
        such candidates (it's a "keep which copy?" prompt), so it defaults to empty.
        """
        review = self.store.create_review(
            job_id=self.job_id,
            staging_path=self.staging_path,
            query=self.normalized_query,
            candidate_ids=candidate_ids,
            rec=rec,
        )
        self.outcomes.append(
            Outcome(
                "parked",
                top_score=dominance.top_score,
                gap=dominance.gap,
                review_id=review.id,
                candidates=candidates or [],
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
        candidate_ids = [
            c.info.track_id for c in candidates if getattr(c.info, "track_id", None)
        ]
        rec = getattr(task, "rec", None)
        rec_name = rec.name.lower() if isinstance(rec, Recommendation) else str(rec)
        # The rich rows ride along for T-013's event only — the row still persists IDs
        # alone. Built from the same candidates so the two never drift.
        return self._record_review(
            candidate_ids, rec_name, dominance, candidates=_candidate_rows(candidates)
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


def _landed_tags(item, has_art: bool) -> dict:
    """spec §6 `track.done.tags`: what actually landed on the file, post-organize.

    `genre` is whatever `lastgenre` wrote (null if no Last.fm key — a documented
    degrade, not a failure, spec §6). `has_art` is Door B's own result (whether a
    cover was embedded), passed in rather than re-read off disk. `has_lyrics` is the
    presence of the `lyrics` plugin's text on the item.
    """
    return {
        "title": getattr(item, "title", None),
        "artist": getattr(item, "artist", None),
        "album": getattr(item, "album", None),
        "year": getattr(item, "year", None) or None,
        "genre": getattr(item, "genre", None) or None,
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
    stored MBIDs (that's T-014's `GET /api/reviews` path). Two honest degrades:

    - **`art_url` is always null here.** Door B fetches cover art for the *one* track
      that lands, not per candidate; reaching art for every parked candidate would
      mean a Cover-Art-Archive round-trip apiece, for a song the owner may never open.
      Disproportionate coupling — so the field is present-but-null, and T-014/T-017
      fill it when the owner actually views the queue.
    - **`score` is `1 − beets' tag distance`** (0 distance = perfect = score 1.0), the
      only per-candidate confidence beets exposes here. It is NOT the acoustic
      fingerprint score (that's a single number for the whole match, not per
      candidate). Absent on a bare double → null.
    """
    rows: list[dict] = []
    for candidate in candidates:
        info = getattr(candidate, "info", None)
        if info is None:
            continue
        distance = getattr(candidate, "distance", None)
        rows.append(
            {
                "candidate_id": getattr(info, "track_id", None),
                "title": getattr(info, "title", None),
                "artist": getattr(info, "artist", None),
                "album": getattr(info, "album", None),
                "year": getattr(info, "year", None) or None,
                "art_url": None,
                "score": (1.0 - float(distance)) if distance is not None else None,
            }
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
    imp["write"].set(True)
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

    # Lyrics: the plugin already auto-fetches on import (LRCLib is a default source,
    # no key). Ask it to prefer *synced* lyrics so Jellyfin can scroll them with
    # playback, and keep the plain text too as a fallback.
    config["lyrics"]["synced"].set(True)
    config["lyrics"]["keep_synced"].set(True)


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
) -> list[Outcome]:
    """Run one staged MP3 through the gate. Returns the outcome(s).

    The script-provable entry point for the spine: given a tagged staging file,
    it drives the whole beets import (identify → tag → art/genre/lyrics →
    organize) and either lands the file or parks a review row — no web layer
    required, exactly as the spike proved the seam.

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

    session = FingerprintTrustSession(
        lib,
        store=store,
        job_id=job_id,
        staging_path=staging_path,
        query=query,
        score_min=score_min,
        gap_min=gap_min,
        dominance_fn=dominance_fn,
    )
    session.run()
    # Finalize AFTER run(): only now is a "landed" accept distinguishable from one
    # beets' duplicate stage skipped (finding #2).
    return session.finalize_outcomes()
