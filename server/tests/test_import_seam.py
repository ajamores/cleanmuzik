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
from beets.autotag import Recommendation
from beets.importer import Action

import app.import_seam as seam
from app.db import Store
from app.import_seam import (
    AcoustidLookupError,
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
    _patch_acoustid(monkeypatch, lookup={"status": "error"})
    with pytest.raises(AcoustidLookupError):
        fingerprint_dominance("/tmp/song.mp3")


def test_dominance_lookup_error_raises_for_retry(monkeypatch):
    _patch_acoustid(monkeypatch)

    def boom(*a, **k):
        raise seam.acoustid.WebServiceError("flaky")

    monkeypatch.setattr(seam.acoustid, "lookup", boom)
    with pytest.raises(AcoustidLookupError):
        fingerprint_dominance("/tmp/song.mp3")


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


def test_narrow_gap_parks(store):
    # High score but the runner-up is right behind: can't tell the pressings apart.
    session = _session(store, Dominance(0.95, 0.90, ("rec-A",)))
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
