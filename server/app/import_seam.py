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

Cost: this means one extra AcoustID lookup per song beyond chroma's own (two
total). For a single-user, one-song-at-a-time tool with ADR-001 delays that's
acceptable for R1; deduping it against chroma's cached fingerprint is a later
optimization, not a correctness issue.

## What lands vs. what parks

- **Dominant** (score ≥ `score_min` and gap ≥ `gap_min`) *and* the winning
  recording is among beets' candidates → return that `TrackMatch`. beets applies
  it, every plugin runs as a stage, and the file is organized into the library.
- **Everything else** → record the candidate **IDs** + `task.rec` to the `reviews`
  table (T-002) and return `Action.SKIP`, which leaves the disk untouched and
  parks the row. Non-blocking: the batch is never stalled by a weak match.

Thresholds default to the ADR-006 starting guess (0.90 / 0.10) but are injectable
per session — T-008 tunes them on a real sample and writes the number back into
the ADR. This module never lowers beets' global `strong_rec_thresh` (ADR-006).
"""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

import acoustid
from beets import config, library, util
from beets.autotag import Recommendation
from beets.importer import Action, ImportSession

from app.artwork import embed_cover, fetch_cover_art
from app.beets_engine import LIBRARY_DIRECTORY, configure_beets
from app.config import Settings, get_settings
from app.db import Review, Store

logger = logging.getLogger("cleanmuzik")

# beets' built-in AcoustID *application* key — the same one `chroma` uses for
# lookups (proven in the spike). The owner's optional `acoustid_apikey` is a
# submission key, not an app key, so lookups use this regardless.
API_KEY = "1vOwZtEn"

# ADR-006 dominance thresholds — a starting guess, not gospel. T-008 measures the
# real auto-accept rate on a batch and writes the tuned numbers back into the ADR.
SCORE_MIN = 0.90  # the top match's acoustic score must be at least this
GAP_MIN = 0.10  # ...and lead the runner-up result by at least this

# We need recording MBIDs (the identity) AND releases (so Door B's cover-art step
# can look art up on the Cover Art Archive by release MBID).
_LOOKUP_META = "recordings releases"
_LOOKUP_TIMEOUT = 10


class AcoustidLookupError(Exception):
    """A transient AcoustID service failure (bad status / network / rate limit).

    Distinct from a clean "no acoustic match": this is retryable, and T-011 wraps
    the identify stage in retry-with-backoff around exactly this exception. A real
    no-match returns an all-zero `Dominance` instead (it simply can't be dominant).
    """


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


def fingerprint_dominance(
    path: bytes | str,
    *,
    api_key: str = API_KEY,
    meta: str = _LOOKUP_META,
    timeout: int = _LOOKUP_TIMEOUT,
) -> Dominance:
    """Fingerprint `path` and read its AcoustID score + runner-up gap.

    THE crux of T-007 (see module docstring): the number beets throws away. Runs
    an independent `acoustid.lookup` and returns a `Dominance`. Raises
    `AcoustidLookupError` on a transient service failure so the caller can retry;
    a fingerprint that generates but matches nothing returns an all-zero
    `Dominance` (not an error — it just parks).
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

    try:
        res = acoustid.lookup(api_key, fp, duration, meta=meta, timeout=timeout)
    except acoustid.AcoustidError as exc:
        # Network / HTTP / parse failure from the free tier (flaky, per the spike).
        raise AcoustidLookupError(str(exc)) from exc

    if res.get("status") != "ok":
        # AcoustID sometimes returns a non-ok status that clears on retry.
        raise AcoustidLookupError(f"acoustid status={res.get('status')!r}")

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


@dataclass
class Outcome:
    """What the gate did with one task — the seam's observable receipt.

    T-012/T-013 turn this into SSE events; the standalone driver and tests read it
    to confirm the real side effect (spine is script-provable before any web layer).
    """

    action: str  # "landed" | "skipped" | "parked"
    top_score: float
    gap: float
    track_id: str | None = None  # the accepted recording MBID (landed)
    review_id: str | None = None  # the parked review row id (parked)
    art_embedded: bool = False  # Door B: did a cover land on the file (landed only)


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
        except AcoustidLookupError as exc:
            # The seam's own AcoustID lookup failed transiently (flaky free tier).
            # Don't let it unwind out of beets' pipeline and crash the import —
            # park to review so the song is recoverable, and log distinctly. T-011
            # adds retry-with-backoff ahead of this fallback; until then a
            # transient failure surfaces as a review, not a lost track (ADR-003).
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
                # Dominant AND the winning recording is one beets can tag. Accept
                # it — but DON'T record "landed" yet: beets' later duplicate stage
                # may still skip the copy, and the receipt must not lie. The real
                # outcome is settled in finalize_outcomes() after run().
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
        known only after the pipeline runs: beets' duplicate stage may skip the
        copy (duplicate_action=skip → `task.skip`). So we record "landed" only for
        accepts that weren't skipped, and "skipped" otherwise — an honest receipt
        so T-012 doesn't clean up staging for a track that never entered the
        library, and T-013's SSE doesn't report done on a no-op. Idempotent.
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
            self.outcomes.append(
                Outcome(
                    "skipped" if skipped else "landed",
                    top_score=dominance.top_score,
                    gap=dominance.gap,
                    track_id=match.info.track_id,
                    art_embedded=art_embedded,
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

    def should_resume(self, path) -> bool:
        # Long-lived backend, no interactive prompts: never ask to resume.
        return False

    # --- parking ----------------------------------------------------------

    def _park(self, task, candidates, dominance: Dominance) -> Review:
        """Record candidate IDs + `task.rec` to the reviews table and note it."""
        candidate_ids = [
            c.info.track_id for c in candidates if getattr(c.info, "track_id", None)
        ]
        rec = getattr(task, "rec", None)
        rec_name = rec.name.lower() if isinstance(rec, Recommendation) else str(rec)

        review = self.store.create_review(
            job_id=self.job_id,
            staging_path=self.staging_path,
            query=self.normalized_query,
            candidate_ids=candidate_ids,
            rec=rec_name,
        )
        self.outcomes.append(
            Outcome(
                "parked",
                top_score=dominance.top_score,
                gap=dominance.gap,
                review_id=review.id,
            )
        )
        logger.info(
            "parking %s as review %s: rec=%s candidates=%d score=%.3f gap=%.3f",
            self.staging_path,
            review.id,
            rec_name,
            len(candidate_ids),
            dominance.top_score,
            dominance.gap,
        )
        return review


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


# --- driving beets ----------------------------------------------------------


def _configure_import_options() -> None:
    """Set the import options for a non-interactive, singleton, copy-in import.

    Every value here has a reason: singletons because a YouTube rip is always a
    lone track; autotag so candidates are looked up; copy+write so the tagged
    file lands in the library and staging survives for T-012 to clean up; the
    non-interactive flags so `choose_item` is the *only* decision point; and
    duplicate_action=skip as a safe R1 default (T-009 replaces it with the
    keep-better-copy tie-break). threaded=False keeps beets' pipeline in our
    caller's thread — T-012 owns the worker thread, and ADR-001 forbids
    parallelizing the pipeline anyway.
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
    dominance_fn=fingerprint_dominance,
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
