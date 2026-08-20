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
from beets.autotag import Distance, Recommendation, TrackMatch
from beets.importer import Action

import app.import_seam as seam
from app.db import Store
from app.import_seam import (
    AcoustidLookupError,
    AcoustidPermanentError,
    Dominance,
    FingerprintTrustSession,
    canonicalize_credit,
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
    # A faithful TrackMatch(distance, info, item) — the shape _accept rebuilds
    # (ADR-028's canonicalize_credit reads match.distance/.item), with a thin
    # info stand-in carrying only the fields these tests compare.
    return TrackMatch(Distance(), SimpleNamespace(track_id=track_id), None)


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
    # date_fn no-op by default so decision tests never touch MusicBrainz; the
    # year tests inject their own.
    kw.setdefault("date_fn", lambda _rid: (None, None, None))
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

    # The fingerprint's recording, not #0. Identity by track_id (not `is`): _accept
    # now returns a canonicalized copy of the match (ADR-028), not the candidate.
    assert choice.info.track_id == task.candidates[1].info.track_id == "rec-A"
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


# --- T-025 / ADR-014: stamp the accepted recording's original release year -----


def test_import_options_set_from_scratch(monkeypatch):
    # ADR-013: the import must clear yt-dlp's embedded junk before applying the match,
    # so MusicBrainz is the sole tag source. Guard the config value directly.
    monkeypatch.setattr(seam, "configure_beets", lambda *a, **k: None)
    seam.config["import"]["from_scratch"].set(False)  # ensure the assert is real
    seam._configure_import_options()
    assert seam.config["import"]["from_scratch"].get(bool) is True


def _fake_mb(recording, monkeypatch):
    """Point `_musicbrainz_api` at a stub whose get_recording returns `recording`."""
    api = SimpleNamespace(get_recording=lambda _rid, includes=None: recording)
    monkeypatch.setattr(seam, "_musicbrainz_api", lambda: api)
    return api


def test_fetch_original_date_prefers_recording_level_first_date(monkeypatch):
    # The recording's own first_release_date is MusicBrainz's authoritative original
    # date (review F4) — used ahead of any per-release scan, even if releases exist.
    _fake_mb(
        {
            "first_release_date": "1975-10-31",
            "releases": [{"date": "2020", "release_group": {"first_release_date": "2020"}}],
        },
        monkeypatch,
    )
    assert seam.fetch_original_date("rec-A") == (1975, 10, 31)


def test_fetch_original_date_picks_earliest_across_releases(monkeypatch):
    # No recording-level date, so fall back to releases: earliest wins, and the
    # release-group `first_release_date` is preferred over a later per-release `date`.
    _fake_mb(
        {
            "releases": [
                {"date": "2020-01-15", "release_group": {"first_release_date": "2020"}},
                {"date": "1975-11-21", "release_group": {"first_release_date": "1975-10-31"}},
            ]
        },
        monkeypatch,
    )
    assert seam.fetch_original_date("rec-A") == (1975, 10, 31)


def test_fetch_original_date_keeps_fullest_date_on_year_tie(monkeypatch):
    # Review F3: a year-only date and a full date for the SAME year — the complete
    # one must win, not get discarded by a naive min() over the tuples.
    _fake_mb(
        {
            "releases": [
                {"date": None, "release_group": {"first_release_date": "1975"}},
                {"date": "1975-10-31", "release_group": {}},
            ]
        },
        monkeypatch,
    )
    assert seam.fetch_original_date("rec-A") == (1975, 10, 31)


def test_fetch_original_date_falls_back_to_release_date(monkeypatch):
    # No recording-level or release-group date, but the release itself carries one.
    _fake_mb(
        {"releases": [{"date": "1982-01-02", "release_group": {}}]}, monkeypatch
    )
    assert seam.fetch_original_date("rec-A") == (1982, 1, 2)


def test_fetch_original_date_no_dated_release_returns_none(monkeypatch):
    _fake_mb(
        {"releases": [{"date": "", "release_group": {"first_release_date": ""}}]},
        monkeypatch,
    )
    assert seam.fetch_original_date("rec-A") == (None, None, None)


def test_fetch_original_date_no_recording_id_makes_no_call(monkeypatch):
    called = []
    monkeypatch.setattr(
        seam, "_musicbrainz_api", lambda: called.append(1) or SimpleNamespace()
    )
    assert seam.fetch_original_date(None) == (None, None, None)
    assert called == []  # short-circuits before touching MusicBrainz


def test_landed_track_gets_original_year_stamped(store):
    session = _session(
        store,
        Dominance(0.96, 0.30, ("rec-A",)),
        date_fn=lambda _rid: (1996, 6, 25),
    )
    task = _task(["rec-A"])
    session.choose_item(task)
    outcomes = session.finalize_outcomes()

    assert outcomes[-1].action == "landed"
    assert task.item.year == 1996  # stamped onto the item beets will keep
    assert outcomes[-1].tags["year"] == 1996  # and carried on the track.done payload


def test_blank_release_date_leaves_year_unstamped(store):
    session = _session(
        store,
        Dominance(0.96, 0.30, ("rec-A",)),
        date_fn=lambda _rid: (None, None, None),
    )
    task = _task(["rec-A"])
    session.choose_item(task)
    outcomes = session.finalize_outcomes()

    assert outcomes[-1].action == "landed"  # a missing date never blocks landing
    assert getattr(task.item, "year", None) is None
    assert outcomes[-1].tags["year"] is None


def test_year_lookup_failure_does_not_unland_the_track(store):
    def boom(_rid):
        raise RuntimeError("MusicBrainz unreachable")

    session = _session(store, Dominance(0.96, 0.30, ("rec-A",)), date_fn=boom)
    task = _task(["rec-A"])
    session.choose_item(task)
    outcomes = session.finalize_outcomes()

    assert outcomes[-1].action == "landed"  # best-effort: a failed year still lands
    assert outcomes[-1].tags["year"] is None


def test_year_write_failure_reports_no_year(store):
    # Review F2: the year is set in memory before the file write; if that write
    # fails, the track.done payload must NOT keep reporting a year the disk lacks.
    session = _session(
        store,
        Dominance(0.96, 0.30, ("rec-A",)),
        date_fn=lambda _rid: (1996, 6, 25),
    )
    task = _task(["rec-A"])

    def boom():
        raise OSError("read-only filesystem")

    task.item.try_write = boom
    task.item.store = lambda: None
    session.choose_item(task)
    outcomes = session.finalize_outcomes()

    assert outcomes[-1].action == "landed"  # still landed
    assert outcomes[-1].tags["year"] is None  # but rolled back — no phantom year


def test_skipped_duplicate_gets_no_year_lookup(store):
    called = []
    session = _session(
        store,
        Dominance(0.97, 0.30, ("rec-A",)),
        date_fn=lambda _rid: called.append(1) or (1996, None, None),
    )
    task = _task(["rec-A"])
    task.skip = True
    session.choose_item(task)
    outcomes = session.finalize_outcomes()

    assert outcomes[-1].action == "skipped"
    assert called == []  # a track that didn't land gets no year call


# --- T-009: acquire-time duplicate handling (choose_item + the real library) --
#
# The song already exists in the library. Detection is by MusicBrainz recording id
# via a DIRECT query against a real (in-memory) beets library — not beets' import
# duplicate stage, which can't see our duplicates (its probe carries the recording
# id under `track_id`, before the mb_trackid mapping). R1 is NON-destructive: it
# never deletes an existing file. ADR-009 amendment (2026-08-04): ALL duplicates
# park — the owner always sees the match and can catch AcoustID false positives.
# The prior silent-skip for equal-bitrate duplicates showed a bare "Done" card with
# no info and lost songs on false positives.


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
    # date_fn no-op by default so decision tests never touch MusicBrainz; the
    # year tests inject their own.
    kw.setdefault("date_fn", lambda _rid: (None, None, None))
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

    # The match, accepted — compared by track_id since _accept returns a
    # canonicalized copy of the candidate, not the candidate object (ADR-028).
    assert choice.info.track_id == task.candidates[0].info.track_id
    assert session._accepted  # queued to finalize as landed
    assert store.list_reviews() == []


def test_choose_item_dedup_parks_equal_bitrate(store):
    # The everyday re-paste: same recording already in the library at the same 320
    # bitrate. Always parks (ADR-009 amendment) so the owner can verify the match
    # and catch AcoustID false positives — a silent skip showed "Done" with no
    # feedback, and a wrong match lost the song.
    lib = _lib_with(_lib_item("rec-A", 320000, artist="A", title="T"))
    session = _session_with_lib(store, Dominance(0.96, 0.2, ("rec-A",)), lib)

    choice = session.choose_item(_dup_task(320000))

    assert choice is Action.SKIP
    assert session.outcomes[-1].action == "parked"
    assert session.outcomes[-1].rec == "duplicate"
    assert not session._accepted
    assert len(store.list_reviews()) == 1
    assert store.list_reviews()[0].rec == "duplicate"


def test_choose_item_dedup_parks_higher_bitrate_existing(store):
    # Existing is strictly better (320 vs an incoming 128) → still parks (ADR-009
    # amendment). The owner sees the comparison and clicks "Keep existing".
    lib = _lib_with(_lib_item("rec-A", 320000))
    session = _session_with_lib(store, Dominance(0.96, 0.2, ("rec-A",)), lib)

    choice = session.choose_item(_dup_task(128000))

    assert choice is Action.SKIP
    assert session.outcomes[-1].action == "parked"
    assert session.outcomes[-1].rec == "duplicate"
    assert len(store.list_reviews()) == 1


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


def test_choose_item_dedup_parks_even_with_multiple_existing(store):
    # Two existing copies of the recording (256 + 320). The incoming 320 is covered by
    # the 320, but we still park (ADR-009 amendment) — the owner verifies.
    lib = _lib_with(
        _lib_item("rec-A", 256000, path=b"/lib/a-256.mp3"),
        _lib_item("rec-A", 320000, path=b"/lib/a-320.mp3"),
    )
    session = _session_with_lib(store, Dominance(0.96, 0.2, ("rec-A",)), lib)

    choice = session.choose_item(_dup_task(320000))

    assert choice is Action.SKIP
    assert session.outcomes[-1].action == "parked"
    assert session.outcomes[-1].rec == "duplicate"
    assert len(store.list_reviews()) == 1


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


# --- R1.5 reconcile seam wiring (T-204) -------------------------------------
#
# choose_item now gathers the other senses, builds the augmented candidate list, and
# stashes a validated Verdict — but the land/park decision is still R1's (T-205 rewires
# it). These tests exercise that production with all four seams stubbed, exactly as
# dominance_fn is stubbed. Verdict is imported here to build stub returns.

from app.reconcile import Verdict  # noqa: E402


def _matched_shazam(isrc="GB123"):
    return {
        "matched": True,
        "shazam_artist": "Pa Salieu",
        "shazam_title": "Frontline",
        "isrc": isrc,
        "art_url": None,
        "lyrics": None,
        "error": None,
    }


def test_choose_item_builds_augmented_candidates_with_isrc_entry(store):
    captured = {}

    def reconcile_fn(evidence):
        captured["evidence"] = evidence
        chosen = evidence["candidates"][-1]["n"]  # the appended ISRC entry
        return Verdict(verdict="accept", chosen_candidate=chosen, agreeing_senses=["yt", "sz"])

    session = _session(
        store,
        Dominance(0.3, 0.1, ()),
        shazam_fn=lambda _path: _matched_shazam(),
        isrc_fn=lambda _isrc: SimpleNamespace(mbid="mb-real", artist="Pa Salieu", title="Frontline"),
        reconcile_fn=reconcile_fn,
    )

    session.choose_item(_task(["rec-A"]))

    cands = captured["evidence"]["candidates"]
    assert [c["source"] for c in cands] == ["musicbrainz", "isrc"]
    assert cands[-1]["mbid"] == "mb-real"  # a real MBID, appended last
    assert session.verdict.chosen_candidate == 1  # indexes into that exact list
    assert not hasattr(session.verdict, "confidence")  # confidence can't leave the seam


def test_choose_item_no_isrc_entry_when_isrc_unresolved(store):
    captured = {}

    def reconcile_fn(evidence):
        captured["evidence"] = evidence
        return Verdict(verdict="park", chosen_candidate=None)

    session = _session(
        store,
        Dominance(0.3, 0.1, ()),
        shazam_fn=lambda _path: _matched_shazam(),
        isrc_fn=lambda _isrc: None,  # the ~54% gap — ISRC resolves to nothing
        reconcile_fn=reconcile_fn,
    )

    session.choose_item(_task(["rec-A"]))

    assert [c["source"] for c in captured["evidence"]["candidates"]] == ["musicbrainz"]


def test_choose_item_unmatched_shazam_skips_isrc_lookup(store):
    isrc_calls = []

    session = _session(
        store,
        Dominance(0.3, 0.1, ()),
        shazam_fn=lambda _path: {"matched": False, "error": "timeout"},
        isrc_fn=lambda isrc: isrc_calls.append(isrc),
        reconcile_fn=lambda _ev: Verdict(verdict="park", chosen_candidate=None),
    )

    session.choose_item(_task(["rec-A"]))

    assert isrc_calls == []  # a non-voting Shazam never triggers the ISRC lookup


def test_choose_item_without_reconcile_fn_produces_no_verdict(store):
    # The default (R1) path: no reconcile_fn wired → no sense gathered, verdict stays None.
    session = _session(store, Dominance(0.3, 0.1, ()))
    session.choose_item(_task(["rec-A"]))
    assert session.verdict is None


def test_choose_item_reconcile_failure_parks_adjudication_unavailable(store):
    # T-205: a transient reconcile failure on a wired adjudicator must never crash the
    # gate and never silently land — it parks THIS track with a distinct reason.
    def boom(_evidence):
        raise RuntimeError("anthropic down")

    session = _session(
        store,
        Dominance(0.3, 0.1, ()),
        shazam_fn=lambda _path: {"matched": False, "error": "x"},
        isrc_fn=lambda _isrc: None,
        reconcile_fn=boom,
    )

    choice = session.choose_item(_task(["rec-A"]))  # must not raise

    assert choice is Action.SKIP
    assert len(store.list_reviews()) == 1
    assert session.verdict.verdict == "park"
    assert session.verdict.reason == "adjudication unavailable"


# --- T-205: the 2-of-3 accept gate + degrade (the safety spine) --------------
#
# The gate consumes the Verdict + augmented candidates + the three senses and decides
# land-vs-park, RE-DERIVING agreement in code. Senses are stubbed exactly as dominance_fn
# is; source_signals is built full so the yt vote reads real fields. `_cand`/`_task` above
# carry only a track_id, so these tests use `_rich_task`, whose candidates carry the
# artist/title the loose-match vote compares against.


def _signals(yt_artist, yt_title):
    """A full SourceSignals with the two voting fields set (rest are inert defaults)."""
    return seam.SourceSignals(
        title=f"{yt_artist} - {yt_title}",
        uploader="Uploader",
        channel_is_topic=False,
        description_head="",
        tags=[],
        duration=None,
        video_id="vid",
        yt_artist=yt_artist,
        yt_title=yt_title,
        yt_album=None,
        yt_release_year=None,
    )


def _rich_candidate(track_id, artist, title):
    return TrackMatch(
        Distance(),
        SimpleNamespace(track_id=track_id, artist=artist, title=title),
        None,
    )


def _rich_task(candidates, rec=Recommendation.medium):
    """A task whose candidates carry (track_id, artist, title) — what the vote compares."""
    return SimpleNamespace(
        item=SimpleNamespace(path=b"/staging/song.mp3"),
        candidates=[_rich_candidate(*c) for c in candidates],
        rec=rec,
    )


def _isrc_recording(mbid="mb-real", artist="Pa Salieu", title="Frontline"):
    return SimpleNamespace(mbid=mbid, artist=artist, title=title)


def test_gate_fingerprint_shazam_yt_all_agree_lands(store):
    # The R1 happy path under reconcile: all three senses back the beets candidate → land.
    art_seen: list = []
    session = _session(
        store,
        Dominance(0.95, 0.20, ("rec-A",), ("rel-A",)),
        source_signals=_signals("Pa Salieu", "Frontline"),
        shazam_fn=lambda _p: _matched_shazam(),
        isrc_fn=lambda _isrc: None,  # ISRC didn't resolve; the fp candidate is enough
        reconcile_fn=lambda _ev: Verdict(
            verdict="accept", chosen_candidate=0, agreeing_senses=["yt", "fp", "sz"]
        ),
        art_fn=lambda **kw: art_seen.append(kw.get("release_ids")) or None,
    )

    choice = session.choose_item(_rich_task([("rec-A", "Pa Salieu", "Frontline")]))
    outcomes = session.finalize_outcomes()

    assert choice.info.track_id == "rec-A"
    assert outcomes[-1].action == "landed"
    # fp backs the chosen recording → the real dominance is carried (correct art source).
    assert outcomes[-1].top_score == 0.95
    assert art_seen == [("rel-A",)]  # cover fetched by the landed recording's releases
    assert store.list_reviews() == []


def test_gate_lands_the_isrc_correction_when_fp_dissents(store, monkeypatch):
    # Pa Salieu: the fingerprint points at the WRONG recording, but yt + Shazam both back
    # the ISRC-sourced candidate (a real MBID) → land the correction, not the fp's choice.
    # And the WRONG recording's cover art must NOT be embedded: because the fingerprint
    # dissented, the landed dominance is zeroed so art falls back to artist/title (F2).
    resolved = SimpleNamespace(track_id="mb-real", artist="Pa Salieu", title="Frontline")
    monkeypatch.setattr(seam.metadata_plugins, "track_for_id", lambda *_a, **_k: resolved)
    art_seen: list = []

    session = _session(
        store,
        Dominance(0.95, 0.20, ("rec-wrong",), ("rel-wrong",)),  # fp confident but WRONG
        source_signals=_signals("Pa Salieu", "Frontline"),
        shazam_fn=lambda _p: _matched_shazam(),
        isrc_fn=lambda _isrc: _isrc_recording(),  # resolves to the real recording
        reconcile_fn=lambda ev: Verdict(
            verdict="accept",
            chosen_candidate=ev["candidates"][-1]["n"],  # the appended ISRC entry
            agreeing_senses=["yt", "sz"],
        ),
        art_fn=lambda **kw: art_seen.append(kw.get("release_ids")) or None,
    )

    choice = session.choose_item(_rich_task([("rec-wrong", "Wrong", "Song")]))
    outcomes = session.finalize_outcomes()

    assert choice.info.track_id == "mb-real"  # the ISRC recording, not the fp's
    assert outcomes[-1].action == "landed"
    assert outcomes[-1].track_id == "mb-real"
    assert outcomes[-1].top_score == 0.0  # landed dominance zeroed (fp dissented)
    assert art_seen == [()]  # NO release ids — never rec-wrong's ("rel-wrong")


def test_gate_land_lookup_failure_parks_not_errors(store, monkeypatch):
    # F1: the accept path can hit a LIVE MusicBrainz lookup (track_for_id) for an ISRC
    # candidate absent from beets' candidates. A transient failure must PARK, never crash.
    def boom(*_a, **_k):
        raise RuntimeError("musicbrainz 503")

    monkeypatch.setattr(seam.metadata_plugins, "track_for_id", boom)

    session = _session(
        store,
        Dominance(0.0, 0.0, ()),
        source_signals=_signals("Pa Salieu", "Frontline"),
        shazam_fn=lambda _p: _matched_shazam(),
        isrc_fn=lambda _isrc: _isrc_recording(),
        reconcile_fn=lambda ev: Verdict(
            verdict="accept",
            chosen_candidate=ev["candidates"][-1]["n"],  # ISRC entry, not in candidates
            agreeing_senses=["yt", "sz"],
        ),
    )

    choice = session.choose_item(_rich_task([("rec-other", "Other", "Song")]))  # no raise

    assert choice is Action.SKIP
    assert len(store.list_reviews()) == 1


def test_gate_shazam_alone_never_lands(store):
    # Only Shazam supports the candidate (fp absent, yt disagrees) → 1 sense → park.
    session = _session(
        store,
        Dominance(0.0, 0.0, ()),  # fp absent
        source_signals=_signals("Someone Else", "Other Title"),  # yt disagrees
        shazam_fn=lambda _p: _matched_shazam(),  # matches the candidate
        isrc_fn=lambda _isrc: None,
        reconcile_fn=lambda _ev: Verdict(
            verdict="accept", chosen_candidate=0, agreeing_senses=["sz"]
        ),
    )

    choice = session.choose_item(_rich_task([("rec-A", "Pa Salieu", "Frontline")]))

    assert choice is Action.SKIP
    assert len(store.list_reviews()) == 1


def test_gate_real_but_wrong_isrc_parks(store):
    # Strawberry Swing: yt says "Frank Ocean", the ISRC entry is "Coldplay" (a real but
    # WRONG recording). Only Shazam/ISRC agrees; yt can't (frankocean ⊄ coldplay) → park.
    session = _session(
        store,
        Dominance(0.0, 0.0, ()),  # fp absent
        source_signals=_signals("Frank Ocean", "Strawberry Swing"),
        shazam_fn=lambda _p: {
            "matched": True,
            "shazam_artist": "Coldplay",
            "shazam_title": "Strawberry Swing",
            "isrc": "GB999",
            "error": None,
        },
        isrc_fn=lambda _isrc: _isrc_recording("mb-cold", "Coldplay", "Strawberry Swing"),
        reconcile_fn=lambda ev: Verdict(
            verdict="accept",
            chosen_candidate=ev["candidates"][-1]["n"],  # the Coldplay ISRC entry
            agreeing_senses=["yt", "sz"],  # LLM is generous; the code isn't
        ),
    )

    choice = session.choose_item(_rich_task([("rec-A", "Frank Ocean", "Some Song")]))

    assert choice is Action.SKIP  # < 2 agree on artist AND title
    assert len(store.list_reviews()) == 1


def test_gate_re_derivation_is_load_bearing(store):
    # THE guard test: the LLM claims two senses agree, but the senses themselves support
    # only one (fp is absent — top_recording_ids empty). The gate must park on its OWN
    # count, not the LLM's. Without the code re-derivation this test lands and fails.
    session = _session(
        store,
        Dominance(0.0, 0.0, ()),  # fp ABSENT — it cannot support anything
        source_signals=_signals("Pa Salieu", "Frontline"),  # yt genuinely agrees (1)
        shazam_fn=lambda _p: {"matched": False, "error": "x"},  # sz absent
        isrc_fn=lambda _isrc: None,
        reconcile_fn=lambda _ev: Verdict(
            verdict="accept",
            chosen_candidate=0,
            agreeing_senses=["yt", "fp"],  # over-eager: claims 2, only yt is real
        ),
    )

    choice = session.choose_item(_rich_task([("rec-A", "Pa Salieu", "Frontline")]))

    assert choice is Action.SKIP  # code-validated count is 1 (yt only) → park
    assert len(store.list_reviews()) == 1


def test_gate_park_verdict_parks_even_with_agreement(store):
    # A "park" verdict parks regardless of how many senses agree — accept is required.
    session = _session(
        store,
        Dominance(0.95, 0.20, ("rec-A",)),
        source_signals=_signals("Pa Salieu", "Frontline"),
        shazam_fn=lambda _p: _matched_shazam(),
        isrc_fn=lambda _isrc: None,
        reconcile_fn=lambda _ev: Verdict(
            verdict="park", chosen_candidate=0, agreeing_senses=["yt", "fp", "sz"]
        ),
    )

    choice = session.choose_item(_rich_task([("rec-A", "Pa Salieu", "Frontline")]))

    assert choice is Action.SKIP
    assert len(store.list_reviews()) == 1


def test_gate_rejected_key_degrades_to_r1_gate(store):
    # A rejected/expired key (401) must DEGRADE to the R1 fingerprint gate, not park every
    # track: a dominant fingerprint whose recording is a candidate still lands.
    class _AuthError(Exception):
        status_code = 401

    def boom(_ev):
        raise _AuthError("invalid x-api-key")

    session = _session(
        store,
        Dominance(0.95, 0.20, ("rec-A",)),
        source_signals=_signals("Pa Salieu", "Frontline"),
        shazam_fn=lambda _p: {"matched": False, "error": "x"},
        isrc_fn=lambda _isrc: None,
        reconcile_fn=boom,
    )

    choice = session.choose_item(_rich_task([("rec-A", "Pa Salieu", "Frontline")]))
    outcomes = session.finalize_outcomes()

    assert choice.info.track_id == "rec-A"  # R1 gate landed it
    assert outcomes[-1].action == "landed"
    assert session.verdict is None  # degrade leaves no reconcile verdict


def test_gate_unset_key_falls_back_to_r1_and_parks(store):
    # No reconcile_fn wired (ANTHROPIC_APIKEY unset) → the R1 gate decides. A weak
    # fingerprint parks, exactly as R1 (spec §6 degrade row); no verdict is produced.
    session = _session(store, Dominance(0.80, 0.30, ("rec-A",)))  # below SCORE_MIN

    choice = session.choose_item(_task(["rec-A"]))

    assert choice is Action.SKIP
    assert len(store.list_reviews()) == 1
    assert session.verdict is None


# --- T-206: the park story persists (reason + contradictions + ranked order) --


def test_reconcile_park_persists_story_and_ranked_order_incl_isrc(store):
    # A reconcile PARK (only Shazam agrees → the code count is 1) must still persist the
    # Verdict's story: its reason, its contradictions, and its candidate ranking resolved
    # through the augmented list — so the synthetic ISRC candidate reaches the row (the F6
    # gap T-205 left) and a restart re-hydrates the card in the LLM's ranked order.
    session = _session(
        store,
        Dominance(0.0, 0.0, ()),  # fp absent → this parks
        source_signals=_signals("Frank Ocean", "Strawberry Swing"),
        shazam_fn=lambda _p: {
            "matched": True, "shazam_artist": "Coldplay",
            "shazam_title": "Strawberry Swing", "isrc": "GB999", "error": None,
        },
        isrc_fn=lambda _isrc: _isrc_recording("mb-cold", "Coldplay", "Strawberry Swing"),
        reconcile_fn=lambda ev: Verdict(
            verdict="accept",  # accept, but only sz supports → the gate parks (1 sense)
            chosen_candidate=ev["candidates"][-1]["n"],  # the ISRC entry
            agreeing_senses=["sz"],
            ranking=[ev["candidates"][-1]["n"], 0],  # ISRC first, then the beets candidate
            reason="Only Shazam agrees; YouTube says Frank Ocean.",
            contradictions=["yt: Frank Ocean ≠ Coldplay"],
        ),
    )

    choice = session.choose_item(_rich_task([("rec-A", "Frank Ocean", "Some Song")]))

    assert choice is Action.SKIP
    # A fresh SELECT (list_reviews opens its own connection) — the durable row, not the
    # in-memory session, carries the story.
    [row] = store.list_reviews()
    assert row.reason == "Only Shazam agrees; YouTube says Frank Ocean."
    assert row.contradictions == ["yt: Frank Ocean ≠ Coldplay"]
    # Ranked: the ISRC MBID first (absent from beets' candidates), then the beets one.
    assert row.candidate_ids == ["mb-cold", "rec-A"]
    # The live event (T-013 Outcome.candidates) carries the SAME ranked list, so the owner
    # sees the ISRC option on the first live card — not only after a reload (T-206 review).
    parked = session.outcomes[-1]
    assert [c["candidate_id"] for c in parked.candidates] == ["mb-cold", "rec-A"]
    assert parked.reason == "Only Shazam agrees; YouTube says Frank Ocean."


def test_reconcile_park_ranking_reorders_never_filters(store):
    # A reorder, not a filter: an incomplete `ranking` (naming only one of two beets
    # candidates) must still persist BOTH — the un-ranked one appended, not dropped — so a
    # candidate the owner might pick can never silently vanish from the row.
    session = _session(
        store,
        Dominance(0.0, 0.0, ()),
        source_signals=_signals("Someone", "Else"),  # yt disagrees → parks
        shazam_fn=lambda _p: {"matched": False, "error": "x"},
        isrc_fn=lambda _isrc: None,
        reconcile_fn=lambda _ev: Verdict(
            verdict="park",
            chosen_candidate=None,
            ranking=[1],  # names only the second candidate; the first is omitted
            reason="ambiguous",
        ),
    )

    session.choose_item(
        _rich_task([("rec-A", "A", "one"), ("rec-B", "B", "two")])
    )

    [row] = store.list_reviews()
    assert row.candidate_ids == ["rec-B", "rec-A"]  # ranked first, then the omitted one


def test_r1_park_persists_no_story_and_beets_order(store):
    # The degrade/R1 fingerprint park has no Verdict → no reason/contradictions, and the
    # candidate order stays beets' own (nothing to rank). The control for the test above.
    session = _session(store, Dominance(0.80, 0.30, ("rec-A",)))  # weak fp → parks

    session.choose_item(_task(["rec-A", "rec-B"]))

    [row] = store.list_reviews()
    assert row.reason is None
    assert row.contradictions == []
    assert row.candidate_ids == ["rec-A", "rec-B"]


def test_adjudication_unavailable_park_persists_its_reason(store):
    # A transient reconcile failure parks with reason 'adjudication unavailable' and no
    # ranking — the reason still persists; the order falls back to beets' own.
    def boom(_ev):
        raise RuntimeError("anthropic 503")

    session = _session(
        store,
        Dominance(0.0, 0.0, ()),
        source_signals=_signals("Pa Salieu", "Frontline"),
        shazam_fn=lambda _p: {"matched": False, "error": "x"},
        isrc_fn=lambda _isrc: None,
        reconcile_fn=boom,
    )

    session.choose_item(_rich_task([("rec-A", "Pa Salieu", "Frontline")]))

    [row] = store.list_reviews()
    assert row.reason == "adjudication unavailable"
    assert row.contradictions == []
    assert row.candidate_ids == ["rec-A"]


# --- canonicalize_credit: the ADR-028 write-path fold, match-shaped (T-308) --
#
# The pure string fold is exercised in test_normalize.py; here we pin the
# match-shaped wiring: it folds the credit fields, drives BOTH tag and path via
# a single TrackInfo edit, and NEVER mutates the shared (beets-cached) match.


def _track_match(**info_fields):
    """A minimal TrackMatch carrying the given TrackInfo credit fields."""
    from beets.autotag.hooks import TrackInfo

    info = TrackInfo(**info_fields)
    return TrackMatch(Distance(), info, None)


def test_canonicalize_credit_folds_artist_and_credit_variants():
    match = _track_match(
        artist="JAŸ‐Z",
        artist_credit="JAŸ‐Z",
    )
    out = canonicalize_credit(match)
    assert out.info.artist == "JAY-Z"
    assert out.info.artist_credit == "JAY-Z"


def test_canonicalize_credit_folds_albumartist_when_present():
    # A merged album match carries albumartist / albumartist_credit — both fold.
    match = _track_match(artist="JAŸ‐Z", albumartist="JAŸ‐Z")
    out = canonicalize_credit(match)
    assert out.info.artist == "JAY-Z"
    assert out.info.albumartist == "JAY-Z"


def test_canonicalize_credit_leaves_accented_credit_untouched():
    match = _track_match(artist="Beyoncé", artist_credit="Sigur Rós")
    out = canonicalize_credit(match)
    assert out.info.artist == "Beyoncé"
    assert out.info.artist_credit == "Sigur Rós"


def test_canonicalize_credit_does_not_mutate_the_shared_match():
    # The TrackInfo can be a beets-cached object shared across candidates; the
    # fold deep-copies, so the original is byte-for-byte unchanged (leak guard).
    match = _track_match(artist="JAŸ‐Z")
    out = canonicalize_credit(match)
    assert match.info.artist == "JAŸ‐Z"  # original untouched
    assert out.info.artist == "JAY-Z"  # copy folded
    assert out.info is not match.info


def test_canonicalize_credit_logs_only_when_a_codepoint_changes(caplog):
    import logging

    with caplog.at_level(logging.INFO, logger="cleanmuzik"):
        canonicalize_credit(_track_match(artist="Beyoncé"))
    assert not any("canonicalized artist credit" in r.getMessage() for r in caplog.records)

    caplog.clear()
    with caplog.at_level(logging.INFO, logger="cleanmuzik"):
        canonicalize_credit(_track_match(artist="JAŸ‐Z"))
    assert any("canonicalized artist credit" in r.getMessage() for r in caplog.records)
