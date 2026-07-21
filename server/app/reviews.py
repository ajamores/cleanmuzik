"""The review queue's read + decision layer (T-014, spec §5/§6).

The queue is the product's spine (ADR-006 made it the *primary* path, not the
exception), and it holds **two different questions** that happen to share a table:

- **"What is this song?"** — a weak/ambiguous match. `rec` is a beets recommendation
  name (`none`, `low`, `medium`, …) and `candidate_ids` are the recordings to choose
  among. Answered with `{choice: "<candidate_id>"|"reject"}`.
- **"You already have this — keep which?"** — `rec == "duplicate"`, parked by T-009
  when the download is a strictly-higher-bitrate copy of a library track. Answered
  with `{choice: "keep_existing"|"replace"|"keep_both", suffix?}` (ADR-009 addendum).

`candidate_ids` means something **different** in each: candidate choices in the first,
the **existing library copy's** recording id(s) in the second (`_park_duplicate`'s
docstring). Re-hydrating a duplicate row's ids as if they were candidates would render
a nonsense UI — "which of these is it?" for a question that isn't being asked. So the
two shapes are built by different functions here and never share a path.

## Import weight

Deliberately import-light at module scope so `app.routes.reviews` can import it
without pulling beets onto the app's import path (T-001's lazy-engine property). The
pure parts — validating a body against the row's `rec`, bounding the suffix — are
therefore testable with no engine at all. Everything that touches beets or
MusicBrainz is imported *inside* the function that needs it.

## Re-hydration is a network call per candidate

The row stores bare MBIDs (ADR-006: never a cached candidate object — it goes stale).
So listing the queue means a MusicBrainz lookup per candidate, and a queue of 20
reviews x 5 candidates is 100 lookups on a route the UI blocks on. Three things keep
that honest:

  1. **A process-lifetime cache.** A recording's metadata doesn't move; a re-render of
     the queue costs nothing after the first.
  2. **beets' own rate limiter.** Its MusicBrainz client builds a
     `LimiterTimeoutSession(per_second=rate_limit)`, and `rate_limit` is a hard-coded
     **1.0/sec** for the musicbrainz.org host (verified live, not assumed). ADR-001's
     between-request delay is therefore already enforced inside the library — adding
     our own `sleep` would only double it. The consequence to keep in view: the pass
     is paced, so a cold 20-review queue takes ~1s per uncached candidate. That is
     the price of ADR-006's ID-only rows, and the cache below is what stops it
     recurring.
  3. **A failing lookup degrades to the id-only row, never a 500.** One merged/removed
     MBID (documented data drift, learnings 2026-07-12) must not blank the whole queue.

**What re-hydration recovers:** title + artist, and nothing more. A candidate is a
MusicBrainz *recording*; album/year/art are *release* properties that a recording
lookup never carries, so they are not in the candidate contract at all (ADR-010, not
an oversight). The one field the park-time SSE row has that this path lacks is `score`
(beets' tag distance, unknowable from a bare id), so it re-hydrates as null. The rich
"you already have this" comparison for a *duplicate* row is unaffected — it reads a
tagged library file, which has album/year/art for free (see `_duplicate_detail`).
"""

import logging
import threading
import unicodedata
from dataclasses import dataclass

from app.db import Review, Store
from app.events import candidate_row

logger = logging.getLogger("cleanmuzik")

# The `rec` value that marks a duplicate park (import_seam._park_duplicate).
DUPLICATE_REC = "duplicate"

# Resolve choices. The weak-match branch takes a candidate id or REJECT; the
# duplicate branch takes exactly one of DUPLICATE_CHOICES (ADR-009 addendum).
CHOICE_REJECT = "reject"
CHOICE_KEEP_EXISTING = "keep_existing"
CHOICE_REPLACE = "replace"
CHOICE_KEEP_BOTH = "keep_both"
DUPLICATE_CHOICES = frozenset({CHOICE_KEEP_EXISTING, CHOICE_REPLACE, CHOICE_KEEP_BOTH})

# Bounds on the owner-typed `keep_both` suffix (spec §6). It reaches a filesystem path
# by way of the title tag, so it is bounded — but this is about not producing a file
# the owner can't find, not a security boundary (single-user localhost, ADR-004).
# beets' own path sanitizer is what actually handles illegal characters on disk.
_SUFFIX_MAX = 60
_SUFFIX_ILLEGAL = set('/\\')


@dataclass(frozen=True)
class ResolveRequest:
    """A validated resolve decision — what the worker needs, with the JSON gone.

    `recording_id` is the recording to land, already chosen: the picked candidate for
    a weak match, or (for `replace`/`keep_both`) the duplicate row's existing-copy
    recording id, which is by construction the SAME recording as the incoming file —
    that identity is exactly how T-009 detected the duplicate. It is None for the two
    discard branches, which land nothing.
    """

    choice: str
    recording_id: str | None = None
    suffix: str | None = None

    @property
    def lands(self) -> bool:
        """Whether this decision puts a file in the library (vs. discarding it)."""
        return self.recording_id is not None


class ResolveValidationError(Exception):
    """The body doesn't answer the question this row is asking → 400.

    Deliberately raised rather than guessed at: the two body shapes are disjoint, so a
    `keep_both` sent to a weak-match row (or a candidate id sent to a duplicate) is a
    client bug. Guessing an intent would land the wrong file, which for a duplicate
    could mean deleting the owner's copy on a misread.
    """


def sanitize_suffix(raw) -> str:
    """Bound the owner-typed `keep_both` suffix, or raise `ResolveValidationError`.

    Strips control characters (they'd ride into an ID3 tag and a path invisibly) and
    rejects path separators outright — a `/` in a title turns beets' single path
    component into two, filing the song somewhere the owner will never look. Length is
    capped so the derived path can't blow past a filesystem limit.
    """
    if not isinstance(raw, str):
        raise ResolveValidationError("'suffix' must be a string.")
    # Category "C" is control/format/surrogate/unassigned — none of which belong in a
    # title tag, and all of which are invisible in the UI that would display it.
    cleaned = "".join(c for c in raw if unicodedata.category(c)[0] != "C").strip()
    if not cleaned:
        raise ResolveValidationError("'suffix' must not be empty or whitespace-only.")
    if illegal := _SUFFIX_ILLEGAL.intersection(cleaned):
        raise ResolveValidationError(
            f"'suffix' must not contain a path separator ({''.join(sorted(illegal))})."
        )
    if len(cleaned) > _SUFFIX_MAX:
        raise ResolveValidationError(
            f"'suffix' must be at most {_SUFFIX_MAX} characters (got {len(cleaned)})."
        )
    return cleaned


def validate_resolve_body(review: Review, body: dict | None) -> ResolveRequest:
    """Check a resolve body against the row's `rec` and return the decision.

    The route's whole gate. Raises `ResolveValidationError` (→ 400) on any mismatch
    rather than guessing which question is being answered — see the exception's
    docstring for why guessing is worse than failing here.
    """
    choice = (body or {}).get("choice")
    if not isinstance(choice, str) or not choice.strip():
        raise ResolveValidationError("Missing 'choice'.")
    choice = choice.strip()

    if review.rec == DUPLICATE_REC:
        return _validate_duplicate(review, body or {}, choice)
    return _validate_weak_match(review, body or {}, choice)


def _validate_weak_match(review: Review, body: dict, choice: str) -> ResolveRequest:
    """`{choice: "<candidate_id>"}` or `{choice: "reject"}` (spec §6)."""
    if choice in DUPLICATE_CHOICES:
        raise ResolveValidationError(
            f"'{choice}' answers a duplicate review; this one (rec={review.rec!r}) "
            f"asks which candidate is the right match."
        )
    if choice == CHOICE_REJECT:
        return ResolveRequest(CHOICE_REJECT)
    if choice not in review.candidate_ids:
        # An empty candidate list is a real park shape (no fingerprint match AND no
        # usable title — learnings 2026-07-14), so say so rather than imply a typo.
        known = ", ".join(review.candidate_ids) or "none — this song parked with no candidates"
        raise ResolveValidationError(
            f"'{choice}' is not a candidate of this review. Candidates: {known}. "
            f"Send 'reject' to discard the song."
        )
    return ResolveRequest(choice, recording_id=choice)


def _validate_duplicate(review: Review, body: dict, choice: str) -> ResolveRequest:
    """`{choice: "keep_existing"|"replace"|"keep_both", suffix?}` (ADR-009 addendum)."""
    if choice not in DUPLICATE_CHOICES:
        raise ResolveValidationError(
            f"'{choice}' does not answer a duplicate review. Send one of: "
            f"{', '.join(sorted(DUPLICATE_CHOICES))}."
        )
    if choice == CHOICE_KEEP_EXISTING:
        return ResolveRequest(CHOICE_KEEP_EXISTING)

    # replace / keep_both both LAND the incoming copy, so both need the recording to
    # apply. The row's candidate_ids hold the existing copy's recording id — the same
    # recording as the incoming file (that identity is how the duplicate was detected),
    # so it is exactly the right thing to tag the incoming copy with.
    recording_id = next(iter(review.candidate_ids), None)
    if recording_id is None:
        raise ResolveValidationError(
            "This duplicate review records no recording id, so the incoming copy "
            "cannot be tagged. Send 'keep_existing' to discard it."
        )
    if choice == CHOICE_REPLACE:
        if "suffix" in body:
            raise ResolveValidationError("'suffix' applies to 'keep_both' only.")
        return ResolveRequest(CHOICE_REPLACE, recording_id=recording_id)

    if "suffix" not in body:
        raise ResolveValidationError(
            "'keep_both' requires a 'suffix' — it is what distinguishes the two "
            "copies in Jellyfin (spec §5)."
        )
    return ResolveRequest(
        CHOICE_KEEP_BOTH,
        recording_id=recording_id,
        suffix=sanitize_suffix(body["suffix"]),
    )


# --- re-hydration (the GET side) --------------------------------------------
#
# Everything below reaches MusicBrainz / beets and is imported lazily, per the module
# docstring's import-weight note.

# recording MBID → candidate row. Process-lifetime and unbounded-by-design: it is
# keyed by the MBIDs of songs the owner personally parked, so its ceiling is the size
# of one person's review queue, not of MusicBrainz. A None value is NOT cached — a
# lookup that failed transiently must be retried on the next view, not remembered as
# a permanent miss.
_hydration_cache: dict[str, dict] = {}
# Serializes the lookup pass. Two concurrent GET /api/reviews would otherwise fire the
# same lookups twice and race the rate limiter for no benefit (single user, ADR-001).
_hydration_lock = threading.Lock()


def hydrate_review(store: Store, review_id: str) -> dict | None:
    """One pending review, shaped like a `GET /api/reviews` row (spec §6, T-017).

    The narrow read behind `GET /api/reviews/{id}`. Two callers need one row, not the
    queue:

      - the card re-hydrates a single panel when it has lost the live payload — a
        stream drop, or a process restart, which wipes the in-memory SSE channel the
        panel's candidates rode in on (the durable row survives; the event doesn't);
      - the duplicate panel reads its one row's existing-vs-incoming detail without
        triggering `hydrate_reviews`' per-candidate MusicBrainz pass over *every other*
        parked review (the cost that route's own callers must eat).

    Returns None when the row is gone or already resolved (→ 404), so a stale panel
    reads as "not here" rather than rendering controls over a review that can no
    longer be resolved.
    """
    from app.db import REVIEW_PENDING

    review = store.get_review(review_id)
    if review is None or review.status != REVIEW_PENDING:
        return None
    with _hydration_lock:
        lib = None
        if review.rec == DUPLICATE_REC:
            from app.import_seam import get_library

            try:
                lib = get_library()
            except Exception as exc:  # noqa: BLE001 — a bad library still lists the row bare
                logger.warning("library open failed for review %s: %s", review_id, exc)
        return _hydrate(review, lib)


def hydrate_reviews(store: Store) -> list[dict]:
    """Every pending review, shaped for `GET /api/reviews` (spec §6).

    Blocking and network-bound — the caller runs it off the event loop. This is a
    *read*, not the pipeline, so it does not belong on the single job worker thread
    (ADR-001 forbids parallelizing the pipeline; it does not require every network
    call in the process to queue behind a running import — and blocking the queue
    would hang the UI for the length of a download).
    """
    from app.db import REVIEW_PENDING

    reviews = store.list_reviews(status=REVIEW_PENDING)
    if not reviews:
        return []
    with _hydration_lock:
        # Open the beets library at most once for the whole batch. `_duplicate_detail`
        # runs under this lock for every duplicate row, and re-opening the sqlite-backed
        # library per row is serial I/O the UI blocks on. Lazy: only a duplicate row
        # needs it, so a queue of pure weak-match reviews never opens it at all.
        lib = None
        if any(review.rec == DUPLICATE_REC for review in reviews):
            from app.import_seam import get_library

            try:
                lib = get_library()
            except Exception as exc:  # noqa: BLE001 — batch-open is only an optimization
                # If the library won't open, don't let it take down the whole queue.
                # Leaving `lib=None` makes each duplicate row fall back to its own
                # get_library() inside `_duplicate_detail`, which runs under `_hydrate`'s
                # per-row guard — so a bad library blanks only the duplicate rows, and
                # weak-match rows (which never touch the library) still list.
                logger.warning("batch library open failed; falling back to per-row: %s", exc)
                lib = None
        return [_hydrate(review, lib) for review in reviews]


def _hydrate(review: Review, lib=None) -> dict:
    """One review row → its API shape. Never raises: a row that can't be enriched
    still lists, because a queue that 500s is a queue the owner can't empty."""
    row = {
        "review_id": review.id,
        "job_id": review.job_id,
        "query": review.query,
        "rec": review.rec,
        "candidates": [],
        # Why this row last failed a resolve, if it re-parked (T-029). Carried on the
        # hydrated shape so a card that reconnects/reloads recovers the reason the live
        # SSE `message` would otherwise have lost (finding #2).
        "last_error": review.last_error,
    }
    try:
        if review.rec == DUPLICATE_REC:
            row["duplicate"] = _duplicate_detail(review, lib)
        else:
            row["candidates"] = [
                _candidate(cid, review.candidate_scores.get(cid))
                for cid in review.candidate_ids
            ]
    except Exception as exc:  # noqa: BLE001 — one bad row must not blank the queue
        logger.warning("could not hydrate review %s (%s) — listing it bare", review.id, exc)
    return row


def _candidate(recording_id: str, score: float | None = None) -> dict:
    """A candidate row re-hydrated from its MBID, degrading to id-only on failure.

    `events.candidate_row` builds it either way, so the key set is identical whether
    the lookup succeeded — the UI never has to branch on which path produced the row.

    `score` is passed in from the review row, not looked up (T-028): it is the tag
    distance measured against *this download* at park time, which no recording lookup
    can recover. `None` for a row written before T-028.
    """
    if (cached := _hydration_cache.get(recording_id)) is not None:
        return {**cached, "score": score}
    try:
        from beets import metadata_plugins

        info = metadata_plugins.track_for_id(recording_id, "musicbrainz")
    except Exception as exc:  # noqa: BLE001 — MusicBrainz is down / rate-limited
        logger.warning("MusicBrainz lookup failed for %s (%s)", recording_id, exc)
        info = None
    if info is None:
        # Not cached: a merged MBID stays gone, but a rate-limited one comes back, and
        # remembering the failure would make a transient blip permanent for the process.
        return candidate_row(recording_id, score=score)
    # album / year / art_url are gone from the contract entirely — a recording is not
    # a release (ADR-010), so they were never reachable here to begin with. `score`
    # comes from the caller, not from `info`, and is deliberately NOT cached below:
    # the cache is keyed by recording id, and the same recording can be parked by two
    # different downloads at two different distances. Caching it would serve one
    # review's score to another.
    row = candidate_row(
        recording_id,
        title=getattr(info, "title", None),
        artist=getattr(info, "artist", None),
    )
    _hydration_cache[recording_id] = row
    return {**row, "score": score}


def _duplicate_detail(review: Review, lib=None) -> dict:
    """The "keep which?" payload: what's already in the library vs. what was downloaded.

    A duplicate row's `candidate_ids` are the EXISTING copy's recording id(s), so this
    resolves them against the beets library — real files with real bitrates — rather
    than against MusicBrainz. That contrast (existing 192k vs incoming 320k) IS the
    question the owner is answering, and neither side of it is a "candidate".

    Both loops are de-duplicated, and neither is paranoia: `_park_duplicate` builds
    `candidate_ids` with one entry per duplicate *item*, and every duplicate it found
    carries the SAME `mb_trackid` (they were found by a MatchQuery on exactly that id).
    So two library copies of one recording — the state `keep_both` creates — store
    `["rec-X", "rec-X"]`, and a naive ids x items loop would report each file twice.
    """
    from app.import_seam import get_library, items_for_recording

    if lib is None:  # a direct caller (or a test) that didn't pre-open one
        lib = get_library()
    seen: set = set()
    existing = []
    for rid in dict.fromkeys(review.candidate_ids):  # order-preserving id dedup
        for item in items_for_recording(lib, rid):
            if item.id in seen:  # a file can match more than one stored id
                continue
            seen.add(item.id)
            existing.append({
                "path": _decode(item.path),
                "bitrate": int(getattr(item, "bitrate", 0) or 0),
                "title": getattr(item, "title", None),
                "artist": getattr(item, "artist", None),
                "album": getattr(item, "album", None),
            })
    return {"existing": existing, "incoming": _incoming_detail(review.staging_path)}


def _incoming_detail(staging_path: str) -> dict:
    """The downloaded copy's own numbers, read off the staging file.

    `exists: false` is a real, listable state, not an error: staging lives under the
    system temp dir, so an OS temp sweep between the park and the resolve can take the
    file while the SQLite row survives. The owner needs to SEE that (the landing
    branches will 409) rather than meet a blank panel.
    """
    import os

    if not os.path.isfile(staging_path):
        return {"exists": False, "bitrate": 0, "title": None, "artist": None}
    try:
        from mediafile import MediaFile

        media = MediaFile(staging_path)
        return {
            "exists": True,
            "bitrate": int(getattr(media, "bitrate", 0) or 0),
            "title": media.title,
            "artist": media.artist,
        }
    except Exception as exc:  # noqa: BLE001 — an unreadable staging file still lists
        logger.warning("could not read staging file %s (%s)", staging_path, exc)
        return {"exists": True, "bitrate": 0, "title": None, "artist": None}


def _decode(path) -> str | None:
    """beets item paths are bytes; decode to the TEXT form the rest of the API uses."""
    import os

    return os.fsdecode(path) if path else None
