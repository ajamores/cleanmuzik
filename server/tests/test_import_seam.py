"""T-007 tests — the fingerprint-trust gate lands the dominant, parks the rest.

Two layers, both offline:

1. `fingerprint_dominance` parses AcoustID's response shape correctly — the number
   beets throws away. `acoustid.fingerprint_file`/`lookup` are monkeypatched, so
   no fpcalc or network is touched; we're testing our reading of the result.
2. `FingerprintTrustSession.choose_item` makes the right call given a `Dominance`.
   The session runs with `lib=None` and an injected `dominance_fn` (choose_item
   never touches the library), against a REAL temp SQLite Store so a parked review
   is a real row — directly exercising the ticket's land-vs-park Done-when.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest
from beets import library
from beets.autotag import Recommendation
from beets.importer import Action

import app.import_seam as seam
from app.db import Store
from app.import_seam import (
    AcoustidLookupError,
    AcoustidPermanentError,
    Dominance,
    FingerprintTrustSession,
    fingerprint_dominance,
)


# --- fingerprint_dominance: reading the score beets discards -----------------


def _patch_acoustid(monkeypatch, *, lookup=None, fp_error=False):
    def fake_fp(_path):
        if fp_error:
            raise seam.acoustid.FingerprintGenerationError("boom")
        return (180, b"AQAAfake")

    monkeypatch.setattr(seam.acoustid, "fingerprint_file", fake_fp)
    if lookup is not None:
        monkeypatch.setattr(seam.acoustid, "lookup", lambda *a, **k: lookup)


def test_dominance_reads_top_score_gap_and_recordings(monkeypatch):
    _patch_acoustid(
        monkeypatch,
        lookup={
            "status": "ok",
            "results": [
                {"score": 0.95, "recordings": [{"id": "rec-A"}, {"id": "rec-B"}]},
                {"score": 0.40, "recordings": [{"id": "rec-C"}]},
            ],
        },
    )
    dom = fingerprint_dominance("/tmp/song.mp3")
    assert dom.top_score == pytest.approx(0.95)
    assert dom.runner_up_score == pytest.approx(0.40)
    assert dom.gap == pytest.approx(0.55)
    assert dom.top_recording_ids == ("rec-A", "rec-B")


def test_dominance_captures_release_ids_for_art(monkeypatch):
    # Door B fetches cover art by release MBID — dedup, order-preserving.
    _patch_acoustid(
        monkeypatch,
        lookup={
            "status": "ok",
            "results": [
                {
                    "score": 0.95,
                    "recordings": [
                        {"id": "rec-A", "releases": [{"id": "rel-1"}, {"id": "rel-2"}]},
                        {"id": "rec-B", "releases": [{"id": "rel-1"}]},  # dup rel-1
                    ],
                }
            ],
        },
    )
    dom = fingerprint_dominance("/tmp/song.mp3")
    assert dom.top_release_ids == ("rel-1", "rel-2")


def test_dominance_lone_result_has_zero_runner_up(monkeypatch):
    _patch_acoustid(
        monkeypatch,
        lookup={"status": "ok", "results": [{"score": 0.9, "recordings": [{"id": "x"}]}]},
    )
    dom = fingerprint_dominance("/tmp/song.mp3")
    assert dom.runner_up_score == 0.0
    assert dom.gap == pytest.approx(0.9)


def test_dominance_no_results_is_all_zero_not_error(monkeypatch):
    _patch_acoustid(monkeypatch, lookup={"status": "ok", "results": []})
    dom = fingerprint_dominance("/tmp/song.mp3")
    assert dom == Dominance(0.0, 0.0, ())


def test_dominance_sorts_unordered_results(monkeypatch):
    # Don't trust AcoustID's ordering: the highest score is the top regardless.
    _patch_acoustid(
        monkeypatch,
        lookup={
            "status": "ok",
            "results": [
                {"score": 0.30, "recordings": [{"id": "low"}]},
                {"score": 0.95, "recordings": [{"id": "high"}]},
            ],
        },
    )
    dom = fingerprint_dominance("/tmp/song.mp3")
    assert dom.top_recording_ids == ("high",)
    assert dom.top_score == pytest.approx(0.95)
    assert dom.runner_up_score == pytest.approx(0.30)


def test_dominance_runner_up_skips_same_recording_cluster(monkeypatch):
    # Two acoustic clusters of the SAME recording aren't rivals; the gap is to the
    # first result for a DIFFERENT recording.
    _patch_acoustid(
        monkeypatch,
        lookup={
            "status": "ok",
            "results": [
                {"score": 0.95, "recordings": [{"id": "rec-A"}]},
                {"score": 0.93, "recordings": [{"id": "rec-A"}]},  # same → ignored
                {"score": 0.40, "recordings": [{"id": "rec-B"}]},  # true runner-up
            ],
        },
    )
    dom = fingerprint_dominance("/tmp/song.mp3")
    assert dom.top_score == pytest.approx(0.95)
    assert dom.runner_up_score == pytest.approx(0.40)
    assert dom.gap == pytest.approx(0.55)


def test_dominance_missing_backend_raises_loudly(monkeypatch):
    # fpcalc vanished at runtime: a systemic failure must surface, not silently park
    # every song as a no-match.
    def no_backend(_path):
        raise seam.acoustid.NoBackendError()

    monkeypatch.setattr(seam.acoustid, "fingerprint_file", no_backend)
    with pytest.raises(seam.acoustid.NoBackendError):
        fingerprint_dominance("/tmp/song.mp3")


def test_dominance_bad_status_raises_for_retry(monkeypatch):
    # A non-ok status with no error code is treated as transient (retryable). retries=0
    # isolates the classification from the backoff loop (covered separately).
    _patch_acoustid(monkeypatch, lookup={"status": "error"})
    with pytest.raises(AcoustidLookupError):
        fingerprint_dominance("/tmp/song.mp3", retries=0)


def test_dominance_lookup_error_raises_for_retry(monkeypatch):
    _patch_acoustid(monkeypatch)

    def boom(*a, **k):
        raise seam.acoustid.WebServiceError("flaky")

    monkeypatch.setattr(seam.acoustid, "lookup", boom)
    with pytest.raises(AcoustidLookupError):
        fingerprint_dominance("/tmp/song.mp3", retries=0)


# --- T-011: retry-with-backoff on the transient lookup ----------------------


def test_dominance_retries_lookup_then_succeeds(monkeypatch):
    # The flaky free tier fails then recovers — the whole point of the retry. Verify
    # it lands the match, fingerprints ONCE (only the network hop retries), and backs
    # off exponentially between attempts.
    calls = {"fp": 0, "lookup": 0}

    def fake_fp(_path):
        calls["fp"] += 1
        return (180, b"AQAAfake")

    def flaky_lookup(*a, **k):
        calls["lookup"] += 1
        if calls["lookup"] < 3:
            raise seam.acoustid.WebServiceError("rate limited")
        return {"status": "ok", "results": [{"score": 0.97, "recordings": [{"id": "rec-A"}]}]}

    monkeypatch.setattr(seam.acoustid, "fingerprint_file", fake_fp)
    monkeypatch.setattr(seam.acoustid, "lookup", flaky_lookup)
    slept = []

    dom = fingerprint_dominance("/tmp/song.mp3", sleep_fn=slept.append)

    assert dom.top_score == pytest.approx(0.97)
    assert dom.top_recording_ids == ("rec-A",)
    assert calls["lookup"] == 3  # failed twice, succeeded on the third attempt
    assert calls["fp"] == 1  # fingerprinted once despite the retries
    assert slept == [1.0, 2.0]  # exponential backoff before attempts 2 and 3


def test_dominance_retries_exhausted_reraises(monkeypatch):
    # A lookup that never recovers must re-raise after the configured retries so the
    # session parks it — not retry forever.
    _patch_acoustid(monkeypatch)

    def always_boom(*a, **k):
        raise seam.acoustid.WebServiceError("service down")

    monkeypatch.setattr(seam.acoustid, "lookup", always_boom)
    slept = []

    with pytest.raises(AcoustidLookupError):
        fingerprint_dominance("/tmp/song.mp3", retries=2, sleep_fn=slept.append)

    assert slept == [1.0, 2.0]  # slept before each retry, not after the final failure


def test_dominance_no_match_is_not_retried(monkeypatch):
    # A clean empty result is a real no-match, not a transient error — it must return
    # immediately, never burn retries/backoff on a song AcoustID simply doesn't know.
    calls = {"lookup": 0}

    def counting_lookup(*a, **k):
        calls["lookup"] += 1
        return {"status": "ok", "results": []}

    _patch_acoustid(monkeypatch)
    monkeypatch.setattr(seam.acoustid, "lookup", counting_lookup)
    slept = []

    dom = fingerprint_dominance("/tmp/song.mp3", sleep_fn=slept.append)

    assert dom == Dominance(0.0, 0.0, ())
    assert calls["lookup"] == 1  # one attempt, no retries
    assert slept == []


def test_dominance_invalid_key_is_permanent_not_retried(monkeypatch):
    # The review's core finding: an invalid API key (code 4) returns the same error
    # every time. It must fail fast as an AcoustidPermanentError — NOT retry the full
    # backoff on a doomed request — so the gate can park loudly instead of silently.
    calls = {"lookup": 0}

    def bad_key_lookup(*a, **k):
        calls["lookup"] += 1
        return {"status": "error", "error": {"code": 4, "message": "invalid API key"}}

    _patch_acoustid(monkeypatch)
    monkeypatch.setattr(seam.acoustid, "lookup", bad_key_lookup)
    slept = []

    with pytest.raises(AcoustidPermanentError):
        fingerprint_dominance("/tmp/song.mp3", sleep_fn=slept.append)

    assert calls["lookup"] == 1  # failed once, never retried
    assert slept == []  # no backoff burned on a permanently-bad key


def test_dominance_rate_limit_status_is_retryable(monkeypatch):
    # A rate-limit arrives as a non-ok status too (code 14, not in the permanent set),
    # but IS transient — it must be retried and recover, not fail fast like a bad key.
    calls = {"lookup": 0}

    def throttled_then_ok(*a, **k):
        calls["lookup"] += 1
        if calls["lookup"] < 2:
            return {"status": "error", "error": {"code": 14, "message": "rate limit"}}
        return {"status": "ok", "results": [{"score": 0.96, "recordings": [{"id": "r"}]}]}

    _patch_acoustid(monkeypatch)
    monkeypatch.setattr(seam.acoustid, "lookup", throttled_then_ok)

    dom = fingerprint_dominance("/tmp/song.mp3", sleep_fn=lambda _s: None)

    assert dom.top_score == pytest.approx(0.96)
    assert calls["lookup"] == 2  # retried past the throttle


# --- T-011: owner AcoustID key resolution -----------------------------------


def test_resolve_api_key_prefers_owner_key():
    settings = SimpleNamespace(acoustid_apikey="ownerPrivateKey")
    assert seam._resolve_api_key(settings) == "ownerPrivateKey"


def test_resolve_api_key_falls_back_to_shared_when_unset():
    settings = SimpleNamespace(acoustid_apikey="")
    assert seam._resolve_api_key(settings) == seam.API_KEY


def test_dominance_fingerprint_failure_is_no_match(monkeypatch):
    # Corrupt audio can't fingerprint: not retryable, just unmatched → parks.
    _patch_acoustid(monkeypatch, fp_error=True)
    dom = fingerprint_dominance("/tmp/song.mp3")
    assert dom == Dominance(0.0, 0.0, ())


# --- the gate: choose_item land vs park -------------------------------------


@pytest.fixture
def store(tmp_path: Path) -> Store:
    s = Store(tmp_path / "app.db")
    s.init_schema()
    return s


def _candidate(track_id: str):
    return SimpleNamespace(info=SimpleNamespace(track_id=track_id))


def _task(track_ids, rec=Recommendation.medium):
    return SimpleNamespace(
        item=SimpleNamespace(path=b"/staging/song.mp3"),
        candidates=[_candidate(t) for t in track_ids],
        rec=rec,
    )


def _session(store, dominance, **kw):
    job = store.create_job("https://youtu.be/x")
    # Default art_fn returns nothing so decision tests never touch the network;
    # art-specific tests override it.
    kw.setdefault("art_fn", lambda **_: None)
    return FingerprintTrustSession(
        None,
        store=store,
        job_id=job.id,
        staging_path="/staging/song.mp3",
        query="Dreams",
        dominance_fn=lambda _path: dominance,
        **kw,
    )


def test_dominant_with_matching_candidate_lands(store):
    session = _session(store, Dominance(0.95, 0.20, ("rec-A",)))
    task = _task(["rec-Z", "rec-A"], rec=Recommendation.medium)

    choice = session.choose_item(task)
    outcomes = session.finalize_outcomes()  # "landed" is settled post-run

    assert choice is task.candidates[1]  # the fingerprint's recording, not #0
    assert outcomes[-1].action == "landed"
    assert outcomes[-1].track_id == "rec-A"
    assert store.list_reviews() == []  # nothing parked


def test_accepted_but_skipped_duplicate_is_not_landed(store):
    # beets' duplicate stage skipped the copy (task.skip) — the receipt must say so.
    session = _session(store, Dominance(0.97, 0.30, ("rec-A",)))
    task = _task(["rec-A"])
    task.skip = True

    session.choose_item(task)
    outcomes = session.finalize_outcomes()

    assert outcomes[-1].action == "skipped"
    assert outcomes[-1].track_id == "rec-A"


def test_transient_lookup_failure_parks_not_crashes(store):
    # A flaky AcoustID lookup must park the song, never unwind out and crash the run.
    session = _session(store, Dominance(0.0, 0.0, ()))

    def boom(_path):
        raise seam.AcoustidLookupError("flaky free tier")

    session.dominance_fn = boom
    choice = session.choose_item(_task(["rec-A"]))

    assert choice is Action.SKIP
    assert len(store.list_reviews()) == 1
    assert session.outcomes[-1].action == "parked"


def test_permanent_lookup_failure_parks_not_crashes(store):
    # A permanent AcoustID error (bad key) reaches choose_item without retrying; it must
    # also park the song rather than unwind out of beets' pipeline and crash the run.
    session = _session(store, Dominance(0.0, 0.0, ()))

    def bad_key(_path):
        raise seam.AcoustidPermanentError("acoustid error 4: invalid API key")

    session.dominance_fn = bad_key
    choice = session.choose_item(_task(["rec-A"]))

    assert choice is Action.SKIP
    assert len(store.list_reviews()) == 1
    assert session.outcomes[-1].action == "parked"


def test_low_score_parks(store):
    session = _session(store, Dominance(0.80, 0.30, ("rec-A",)))
    task = _task(["rec-A"])

    choice = session.choose_item(task)

    assert choice is Action.SKIP
    reviews = store.list_reviews()
    assert len(reviews) == 1
    assert reviews[0].candidate_ids == ["rec-A"]
    assert reviews[0].query == "Dreams"
    assert reviews[0].rec == "medium"
    assert session.outcomes[-1].action == "parked"


def test_narrow_gap_lands_by_default(store):
    # T-008: the gap check is OFF by default (GAP_MIN = 0.0). A high-score match whose
    # runner-up is right behind — the "Through The Wire" case, where the runner-up is
    # the SAME song listed twice in AcoustID — must now LAND, not park. This is the
    # measured decision: a gap only ever false-parked certain matches.
    session = _session(store, Dominance(0.95, 0.90, ("rec-A",)))
    choice = session.choose_item(_task(["rec-A"]))
    assert choice.info.track_id == "rec-A"
    assert store.list_reviews() == []


def test_narrow_gap_parks_when_gap_check_enabled(store):
    # The gap MECHANISM still works when a caller opts into it (kept as a knob for any
    # future re-tuning): with gap_min back on, a runner-up right behind parks the song.
    session = _session(store, Dominance(0.95, 0.90, ("rec-A",)), gap_min=0.10)
    choice = session.choose_item(_task(["rec-A"]))
    assert choice is Action.SKIP
    assert len(store.list_reviews()) == 1


def test_dominant_but_recording_absent_parks(store):
    # Fingerprint is dominant, but its recording isn't among beets' candidates:
    # trusting a different candidate would betray the fingerprint → park.
    session = _session(store, Dominance(0.97, 0.40, ("rec-A",)))
    choice = session.choose_item(_task(["rec-Y", "rec-Z"]))
    assert choice is Action.SKIP
    assert len(store.list_reviews()) == 1


def test_custom_thresholds_flip_the_decision(store):
    # T-008 knob: a 0.85 match parks at default but lands if the bar drops.
    dom = Dominance(0.85, 0.50, ("rec-A",))
    assert _session(store, dom).choose_item(_task(["rec-A"])) is Action.SKIP
    landed = _session(store, dom, score_min=0.80).choose_item(_task(["rec-A"]))
    assert landed.info.track_id == "rec-A"


def test_no_candidates_parks_with_empty_ids(store):
    session = _session(store, Dominance(0.99, 0.50, ("rec-A",)))
    choice = session.choose_item(_task([]))
    assert choice is Action.SKIP
    assert store.list_reviews()[0].candidate_ids == []


# --- Door B: cover art on landed tracks -------------------------------------


def test_landed_track_gets_cover_embedded(store, monkeypatch):
    embedded = []
    monkeypatch.setattr(
        seam, "embed_cover", lambda item, img, **k: embedded.append(img) or True
    )
    session = _session(
        store,
        Dominance(0.96, 0.30, ("rec-A",), ("rel-1",)),
        art_fn=lambda **kw: b"\xff\xd8jpeg-bytes",
    )
    session.choose_item(_task(["rec-A"]))
    outcomes = session.finalize_outcomes()

    assert outcomes[-1].action == "landed"
    assert outcomes[-1].art_embedded is True
    assert embedded == [b"\xff\xd8jpeg-bytes"]


def test_skipped_duplicate_gets_no_art(store, monkeypatch):
    called = []
    monkeypatch.setattr(seam, "embed_cover", lambda *a, **k: called.append(1) or True)
    session = _session(
        store,
        Dominance(0.97, 0.30, ("rec-A",), ("rel-1",)),
        art_fn=lambda **kw: b"img",
    )
    task = _task(["rec-A"])
    task.skip = True
    session.choose_item(task)
    outcomes = session.finalize_outcomes()

    assert outcomes[-1].action == "skipped"
    assert outcomes[-1].art_embedded is False
    assert called == []  # never even attempt art for a track that didn't land


def test_art_failure_does_not_unland_the_track(store):
    def boom(**kw):
        raise RuntimeError("cover service down")

    session = _session(
        store, Dominance(0.96, 0.30, ("rec-A",), ("rel-1",)), art_fn=boom
    )
    session.choose_item(_task(["rec-A"]))
    outcomes = session.finalize_outcomes()

    assert outcomes[-1].action == "landed"  # still landed
    assert outcomes[-1].art_embedded is False


# --- T-009: acquire-time duplicate handling (choose_item + the real library) --
#
# The song already exists in the library. Detection is by MusicBrainz recording id
# via a DIRECT query against a real (in-memory) beets library — not beets' import
# duplicate stage, which can't see our duplicates (its probe carries the recording
# id under `track_id`, before the mb_trackid mapping). R1 is NON-destructive: it
# never deletes an existing file. choose_item keeps the existing copy (SKIP) when an
# existing copy is at >= bitrate, and otherwise parks the strictly-higher-bitrate
# upgrade for the owner. These drive the WHOLE path (find + decide), against the real
# temp Store so a parked row is real — closing the earlier "tests bypass detection"
# gap.


def _dup_item(bitrate, *, mb_trackid="rec-A", **tags):
    """A stand-in for the INCOMING staged item: bitrate + a path choose_item reads."""
    return SimpleNamespace(
        bitrate=bitrate, mb_trackid=mb_trackid, path=b"/staging/song.mp3", **tags
    )


def _dup_task(bitrate, *, track_ids=("rec-A",), mb_trackid="rec-A", **tags):
    return SimpleNamespace(
        item=_dup_item(bitrate, mb_trackid=mb_trackid, **tags),
        candidates=[_candidate(t) for t in track_ids],
        rec=Recommendation.medium,
    )


def _lib_item(mb_trackid="rec-A", bitrate=320000, *, path=None, **tags):
    """A real beets library Item — the existing landed copy we detect against."""
    return library.Item(
        mb_trackid=mb_trackid,
        bitrate=bitrate,
        path=path or f"/lib/{mb_trackid}-{bitrate}.mp3".encode(),
        **tags,
    )


def _lib_with(*items) -> library.Library:
    lib = library.Library(":memory:")
    for item in items:
        lib.add(item)
    lib._connection().commit()
    return lib


def _session_with_lib(store, dominance, lib, **kw):
    job = store.create_job("https://youtu.be/x")
    kw.setdefault("art_fn", lambda **_: None)
    return FingerprintTrustSession(
        lib,
        store=store,
        job_id=job.id,
        staging_path="/staging/song.mp3",
        query="Dreams",
        dominance_fn=lambda _path: dominance,
        **kw,
    )


def test_library_duplicates_matches_by_recording_id(store):
    # Detection is by mb_trackid — the same recording, not a title collision.
    lib = _lib_with(_lib_item("rec-A", 320000))
    session = _session_with_lib(store, Dominance(0.96, 0.2, ("rec-A",)), lib)

    assert [d.mb_trackid for d in session._library_duplicates("rec-A")] == ["rec-A"]
    assert session._library_duplicates("rec-OTHER") == []  # a different recording
    assert session._library_duplicates(None) == []  # no id → no query


def test_choose_item_no_library_duplicate_accepts(store):
    # Empty library → nothing to dedup against → the dominant match lands.
    lib = _lib_with()
    session = _session_with_lib(store, Dominance(0.96, 0.2, ("rec-A",)), lib)
    task = _dup_task(320000)

    choice = session.choose_item(task)

    assert choice is task.candidates[0]  # the match, accepted
    assert session._accepted  # queued to finalize as landed
    assert store.list_reviews() == []


def test_choose_item_dedup_keeps_existing_equal_bitrate(store):
    # The everyday re-paste: same recording already in the library at the same 320
    # bitrate → keep existing, drop the redundant download. No second copy, no nag.
    lib = _lib_with(_lib_item("rec-A", 320000, artist="A", title="T"))
    session = _session_with_lib(store, Dominance(0.96, 0.2, ("rec-A",)), lib)

    choice = session.choose_item(_dup_task(320000))

    assert choice is Action.SKIP
    assert session.outcomes[-1].action == "skipped"
    assert not session._accepted  # never queued to land
    assert store.list_reviews() == []


def test_choose_item_dedup_keeps_existing_higher_bitrate(store):
    # Existing is strictly better (320 vs an incoming 128) → keep it, skip the new.
    lib = _lib_with(_lib_item("rec-A", 320000))
    session = _session_with_lib(store, Dominance(0.96, 0.2, ("rec-A",)), lib)

    choice = session.choose_item(_dup_task(128000))

    assert choice is Action.SKIP
    assert session.outcomes[-1].action == "skipped"
    assert store.list_reviews() == []


def test_choose_item_dedup_parks_higher_bitrate_upgrade(store):
    # Incoming out-qualities every existing copy on bitrate (320 vs 256). A genuine
    # upgrade — but R1 never auto-deletes, so park it for the owner to confirm.
    lib = _lib_with(_lib_item("rec-A", 256000))
    session = _session_with_lib(store, Dominance(0.96, 0.2, ("rec-A",)), lib)

    choice = session.choose_item(_dup_task(320000))

    assert choice is Action.SKIP  # never lands a second file
    reviews = store.list_reviews()
    assert len(reviews) == 1
    assert reviews[0].rec == "duplicate"
    assert reviews[0].candidate_ids == ["rec-A"]  # the existing recording id
    assert reviews[0].staging_path == "/staging/song.mp3"  # the new copy awaits
    assert session.outcomes[-1].action == "parked"
    assert not session._accepted  # dedup returns before the accept


def test_choose_item_dedup_skips_if_any_existing_covers(store):
    # Two existing copies of the recording (256 + 320). The incoming 320 is covered by
    # the 320 → keep existing, no park. (Cleaning up the weaker 256 is R2's job.)
    lib = _lib_with(
        _lib_item("rec-A", 256000, path=b"/lib/a-256.mp3"),
        _lib_item("rec-A", 320000, path=b"/lib/a-320.mp3"),
    )
    session = _session_with_lib(store, Dominance(0.96, 0.2, ("rec-A",)), lib)

    choice = session.choose_item(_dup_task(320000))

    assert choice is Action.SKIP
    assert session.outcomes[-1].action == "skipped"
    assert store.list_reviews() == []


def test_choose_item_dedup_single_outcome_then_finalize(store):
    # A deduped song must end with EXACTLY one outcome: the dedup returns before the
    # accept, so finalize (which only settles _accepted) adds nothing more.
    lib = _lib_with(_lib_item("rec-A", 256000))
    session = _session_with_lib(store, Dominance(0.96, 0.2, ("rec-A",)), lib)

    session.choose_item(_dup_task(320000))  # parks (upgrade)
    outcomes = session.finalize_outcomes()

    parked = [o for o in outcomes if o.action == "parked"]
    assert len(parked) == 1 and parked[0].review_id
    assert not any(o.action in ("landed", "skipped") for o in outcomes)
