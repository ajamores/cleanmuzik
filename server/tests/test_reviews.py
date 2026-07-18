"""T-014 tests — the review queue's list + resolve + resume, all offline.

Four layers, mirroring how the ticket is built:

1. **Validation** (pure, no engine): a body is checked against the row's `rec`, and a
   mismatch 400s rather than being guessed at. Plus the `keep_both` suffix bounds.
2. **Re-hydration**: `GET /api/reviews` degrades a failed MusicBrainz lookup to an
   id-only row instead of blanking the queue, and never re-hydrates a duplicate row's
   `candidate_ids` as candidate choices (they're the EXISTING copy's recording ids).
3. **`run_resolve`**: each of the five branches does what it claims, on a REAL temp
   Store with an injected `resolve_fn` — no beets, no network. The staging-cleanup
   contract (spec §5) and the reopened SSE tail are asserted here.
4. **The routes**: the two body shapes over real HTTP via `TestClient`, the claim
   race, and the reopen ordering that T-017 depends on.

`_replace_existing` gets its own section: the assertion that it REFUSES to delete when
the new copy can't be confirmed is the one guarding ADR-009's data-loss window, and it
matters more than any happy path here.
"""

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.jobs as jobs_mod
import app.reviews as reviews_mod
from app.db import Store
from app.events import EventBus
from app.import_seam import Outcome
from app.jellyfin import JellyfinScanError
from app.jobs import JobRegistry, run_resolve
from app.reviews import (
    ResolveRequest,
    ResolveValidationError,
    sanitize_suffix,
    validate_resolve_body,
)
from test_events import parse_sse  # sibling test module (server/tests on sys.path)


# --- helpers ----------------------------------------------------------------


def _store(tmp_path):
    store = Store(tmp_path / "jobs.db")
    store.init_schema()
    return store


def _parked(store, tmp_path, *, rec="medium", candidate_ids=("rec-A", "rec-B")):
    """A real parked review whose staging dir exists, exactly as a park leaves it."""
    job = store.create_job("https://youtu.be/abc")
    store.update_job_status(job.id, "review")
    staging_dir = tmp_path / "cleanmuzik-xyz"
    staging_dir.mkdir(exist_ok=True)
    (staging_dir / "song.webm").write_bytes(b"source")
    mp3 = staging_dir / "song.mp3"
    mp3.write_bytes(b"mp3")
    review = store.create_review(
        job_id=job.id, staging_path=str(mp3), query="artist title",
        candidate_ids=list(candidate_ids), rec=rec,
    )
    return job, review, staging_dir


class _FakeItem:
    """Stand-in for a beets library Item — the few attributes the code reads."""

    def __init__(self, item_id, path, *, bitrate=320000, title="Song", artist="Band"):
        self.id = item_id
        self.path = str(path).encode()
        self.bitrate = bitrate
        self.title = title
        self.artist = artist
        self.album = "LP"
        self.removed = False
        self.moved = False

    def remove(self, delete=False):
        self.removed = True
        if delete:
            from pathlib import Path

            Path(self.path.decode()).unlink(missing_ok=True)

    def move(self):
        self.moved = True


# --- 1. validation: the body must answer the question the row is asking ------


def _review(rec, candidate_ids=("rec-A",)):
    from app.db import Review

    return Review(
        id="rev-1", job_id="job-1", staging_path="/tmp/x.mp3", query="q",
        candidate_ids=list(candidate_ids), rec=rec, status="pending",
    )


def test_weak_match_accepts_a_known_candidate():
    req = validate_resolve_body(_review("medium", ("rec-A", "rec-B")), {"choice": "rec-B"})
    assert req == ResolveRequest("rec-B", recording_id="rec-B")
    assert req.lands


def test_weak_match_accepts_reject_and_lands_nothing():
    req = validate_resolve_body(_review("medium"), {"choice": "reject"})
    assert req.choice == "reject"
    assert not req.lands


def test_weak_match_rejects_an_unknown_candidate():
    with pytest.raises(ResolveValidationError, match="not a candidate"):
        validate_resolve_body(_review("medium", ("rec-A",)), {"choice": "rec-ZZZ"})


def test_weak_match_rejects_a_duplicate_choice():
    # The load-bearing 400: a duplicate answer sent to a weak-match row must not be
    # guessed at — 'replace' would mean deleting a file for a row that names none.
    with pytest.raises(ResolveValidationError, match="duplicate review"):
        validate_resolve_body(_review("medium"), {"choice": "replace"})


def test_empty_candidate_park_says_so_rather_than_implying_a_typo():
    with pytest.raises(ResolveValidationError, match="parked with no candidates"):
        validate_resolve_body(_review("none", ()), {"choice": "rec-A"})


def test_duplicate_rejects_a_candidate_id_choice():
    with pytest.raises(ResolveValidationError, match="does not answer a duplicate"):
        validate_resolve_body(_review("duplicate"), {"choice": "rec-A"})


def test_duplicate_keep_existing_lands_nothing():
    req = validate_resolve_body(_review("duplicate"), {"choice": "keep_existing"})
    assert req.choice == "keep_existing"
    assert not req.lands


def test_duplicate_replace_targets_the_existing_recording():
    # The duplicate row's candidate_ids hold the EXISTING copy's recording id — the
    # same recording as the incoming file, which is exactly what to tag it with.
    req = validate_resolve_body(_review("duplicate", ("rec-EXIST",)), {"choice": "replace"})
    assert req == ResolveRequest("replace", recording_id="rec-EXIST")


def test_duplicate_keep_both_requires_a_suffix():
    with pytest.raises(ResolveValidationError, match="requires a 'suffix'"):
        validate_resolve_body(_review("duplicate"), {"choice": "keep_both"})


def test_duplicate_keep_both_carries_the_sanitized_suffix():
    req = validate_resolve_body(
        _review("duplicate", ("rec-EXIST",)),
        {"choice": "keep_both", "suffix": "  (2015 Remaster) "},
    )
    assert req.suffix == "(2015 Remaster)"
    assert req.recording_id == "rec-EXIST"


def test_replace_refuses_a_stray_suffix():
    with pytest.raises(ResolveValidationError, match="'keep_both' only"):
        validate_resolve_body(_review("duplicate"), {"choice": "replace", "suffix": "x"})


def test_missing_choice_is_a_validation_error():
    with pytest.raises(ResolveValidationError, match="Missing 'choice'"):
        validate_resolve_body(_review("medium"), {})


# --- suffix bounds (spec §6: it reaches a filesystem path via the title tag) --


def test_suffix_rejects_empty_and_whitespace_only():
    for raw in ["", "   ", "\t\n"]:
        with pytest.raises(ResolveValidationError, match="empty or whitespace-only"):
            sanitize_suffix(raw)


def test_suffix_rejects_path_separators():
    # A '/' in a title turns beets' single path component into two, filing the song
    # where the owner will never look.
    for raw in ["a/b", "a\\b"]:
        with pytest.raises(ResolveValidationError, match="path separator"):
            sanitize_suffix(raw)


def test_suffix_strips_control_characters():
    assert sanitize_suffix("(Live\x00\x1f Version)") == "(Live Version)"


def test_suffix_caps_length():
    with pytest.raises(ResolveValidationError, match="at most 60"):
        sanitize_suffix("x" * 61)


def test_suffix_rejects_a_non_string():
    with pytest.raises(ResolveValidationError, match="must be a string"):
        sanitize_suffix(123)


# --- 2. re-hydration --------------------------------------------------------


def test_hydration_degrades_a_failed_lookup_to_an_id_only_row(tmp_path, monkeypatch):
    # One merged/removed MBID (documented MusicBrainz drift) must not 500 the queue.
    store = _store(tmp_path)
    _parked(store, tmp_path, candidate_ids=("rec-GOOD", "rec-GONE"))

    def fake_track_for_id(mbid, source):
        if mbid == "rec-GONE":
            raise RuntimeError("503 from MusicBrainz")
        return type("TI", (), {"title": "Song", "artist": "Band"})()

    monkeypatch.setattr(reviews_mod, "_hydration_cache", {})
    import beets.metadata_plugins as mp

    monkeypatch.setattr(mp, "track_for_id", fake_track_for_id)

    rows = reviews_mod.hydrate_reviews(store)
    assert len(rows) == 1
    good, gone = rows[0]["candidates"]
    assert good["candidate_id"] == "rec-GOOD" and good["title"] == "Song"
    # The degraded row keeps the SAME key set — the UI never branches on which path
    # produced it (events.candidate_row is the single shape).
    assert gone["candidate_id"] == "rec-GONE" and gone["title"] is None
    assert good.keys() == gone.keys()
    # Lock ADR-010: a candidate is EXACTLY these four keys. album / year / art_url were
    # removed because a recording lookup can't fill them; this asserts a future change
    # can't silently re-add the structural-null fields the ADR deleted.
    # Lock ADR-010 at the re-hydration output (the builder's shape is locked in
    # test_events): a candidate is EXACTLY these four keys, so a future change can't
    # silently re-add the structural-null album/year/art_url the ADR deleted.
    assert set(good) == {"candidate_id", "title", "artist", "score"}
    assert "album" not in good and "year" not in good and "art_url" not in good


def test_hydration_does_not_treat_a_duplicate_rows_ids_as_candidates(tmp_path, monkeypatch):
    # _park_duplicate stores the EXISTING library copy's recording ids. Rendering
    # them as "which of these is it?" would be a nonsense UI.
    store = _store(tmp_path)
    _parked(store, tmp_path, rec="duplicate", candidate_ids=("rec-EXIST",))
    called = []

    monkeypatch.setattr(
        reviews_mod, "_duplicate_detail",
        lambda r, lib=None: called.append(r) or {"existing": [], "incoming": {}},
    )
    rows = reviews_mod.hydrate_reviews(store)
    assert rows[0]["rec"] == "duplicate"
    assert rows[0]["candidates"] == []      # never candidate choices
    assert "duplicate" in rows[0]           # the keep-which payload instead
    assert len(called) == 1


def test_hydration_caches_so_a_re_render_costs_nothing(tmp_path, monkeypatch):
    store = _store(tmp_path)
    _parked(store, tmp_path, candidate_ids=("rec-A",))
    calls = []
    monkeypatch.setattr(reviews_mod, "_hydration_cache", {})
    import beets.metadata_plugins as mp

    monkeypatch.setattr(
        mp, "track_for_id",
        lambda mbid, src: calls.append(mbid) or type("TI", (), {"title": "S", "artist": "B"})(),
    )
    reviews_mod.hydrate_reviews(store)
    reviews_mod.hydrate_reviews(store)
    assert calls == ["rec-A"], "a cached candidate must not be looked up twice"


def test_hydration_does_not_cache_a_failure(tmp_path, monkeypatch):
    # A rate-limited lookup comes back; remembering the miss would make a transient
    # blip permanent for the life of the process.
    store = _store(tmp_path)
    _parked(store, tmp_path, candidate_ids=("rec-A",))
    calls = []
    monkeypatch.setattr(reviews_mod, "_hydration_cache", {})
    import beets.metadata_plugins as mp

    monkeypatch.setattr(mp, "track_for_id", lambda mbid, src: calls.append(mbid) or None)
    reviews_mod.hydrate_reviews(store)
    reviews_mod.hydrate_reviews(store)
    assert calls == ["rec-A", "rec-A"]


def test_only_pending_reviews_list(tmp_path, monkeypatch):
    store = _store(tmp_path)
    _, review, _ = _parked(store, tmp_path, candidate_ids=())
    assert len(reviews_mod.hydrate_reviews(store)) == 1
    store.update_review_status(review.id, "resolved")
    assert reviews_mod.hydrate_reviews(store) == []


# --- 3. run_resolve: the five branches --------------------------------------


def _run_resolve(store, review, request, **overrides):
    """Drive run_resolve with a real bus + registry and an injected resolve_fn."""
    bus = EventBus()
    registry = JobRegistry()
    kwargs = dict(
        store=store,
        registry=registry,
        bus=bus,
        lib=_FakeLib([]),
        resolve_fn=lambda *a, **k: [
            Outcome("landed", 0.0, 0.0, track_id="rec-A",
                    chosen={"title": "Song"}, tags={"title": "Song"},
                    landed_path="/lib/Band/Song.mp3")
        ],
        scan_fn=lambda **k: True,
    )
    kwargs.update(overrides)
    state = run_resolve(review.job_id, review.id, request, **kwargs)
    return state, bus


class _FakeLib:
    def __init__(self, items):
        self._items = items

    def items(self, _query):
        return list(self._items)


def _events(bus, job_id):
    async def drain():
        return "".join([f async for f in bus.stream(job_id)])

    return parse_sse(asyncio.run(drain()))


def test_reject_discards_staging_and_marks_rejected(tmp_path):
    store = _store(tmp_path)
    job, review, staging_dir = _parked(store, tmp_path)
    state, _ = _run_resolve(store, review, ResolveRequest("reject"))
    assert state.status == "done"
    assert store.get_review(review.id).status == "rejected"
    assert not staging_dir.exists(), "a rejected song's staging must be cleaned (spec §5)"


def test_keep_existing_discards_the_download_and_resolves(tmp_path):
    store = _store(tmp_path)
    job, review, staging_dir = _parked(store, tmp_path, rec="duplicate")
    state, _ = _run_resolve(store, review, ResolveRequest("keep_existing"))
    assert state.status == "done"
    assert store.get_review(review.id).status == "resolved"
    assert not staging_dir.exists()


def test_accepting_a_candidate_lands_scans_and_cleans_staging(tmp_path):
    store = _store(tmp_path)
    job, review, staging_dir = _parked(store, tmp_path)
    scans = []
    state, bus = _run_resolve(
        store, review, ResolveRequest("rec-A", recording_id="rec-A"),
        scan_fn=lambda **k: scans.append(k) or True,
    )
    assert state.status == "done"
    assert store.get_review(review.id).status == "resolved"
    assert scans, "a landed resolve must trigger a Jellyfin scan"
    assert not staging_dir.exists(), "an accepted song's staging must be cleaned (spec §5)"
    assert [n for n, _ in _events(bus, job.id)] == ["track.tagging", "track.done"]


def test_keep_both_passes_the_suffix_to_the_import(tmp_path):
    store = _store(tmp_path)
    job, review, _ = _parked(store, tmp_path, rec="duplicate", candidate_ids=("rec-E",))
    seen = {}

    def capture(path, **kwargs):
        seen.update(kwargs)
        return [Outcome("landed", 0.0, 0.0, landed_path="/lib/x.mp3", tags={}, chosen={})]

    state, _ = _run_resolve(
        store, review,
        ResolveRequest("keep_both", recording_id="rec-E", suffix="(Remaster)"),
        resolve_fn=capture,
    )
    assert state.status == "done"
    assert seen["suffix"] == "(Remaster)"
    assert seen["recording_id"] == "rec-E"


def test_a_failed_resolve_returns_the_review_to_the_queue_and_keeps_staging(tmp_path):
    # The song must stay resolvable: deleting its file would strand the row forever.
    store = _store(tmp_path)
    job, review, staging_dir = _parked(store, tmp_path)
    store.claim_review(review.id)

    def boom(*a, **k):
        raise RuntimeError("beets organize blew up")

    state, bus = _run_resolve(
        store, review, ResolveRequest("rec-A", recording_id="rec-A"), resolve_fn=boom
    )
    assert state.status == "error"
    assert state.stage == "land"
    assert store.get_review(review.id).status == "pending", "a failed resolve is retryable"
    assert staging_dir.exists(), "a failed resolve must keep the file it needs to retry"
    assert dict(_events(bus, job.id))["track.error"]["stage"] == "land"


def test_a_scan_failure_after_landing_does_not_requeue_the_committed_resolve(tmp_path):
    # Once the upgrade is on disk (and for `replace`, the old copy already gone), the
    # resolve is COMMITTED. A Jellyfin scan failing afterward must be reported as an
    # error but must NOT return the review to `pending`: re-queueing a landing that
    # already happened leaves the queue contradicting the library (the ADR-009-class
    # inconsistency the review caught). The song landed; only the refresh failed.
    store = _store(tmp_path)
    job, review, staging_dir = _parked(store, tmp_path)

    def scan_boom(**k):
        raise JellyfinScanError("jellyfin is restarting")

    state, bus = _run_resolve(
        store, review, ResolveRequest("rec-A", recording_id="rec-A"),
        scan_fn=scan_boom,
    )
    assert state.status == "error"
    assert state.stage == "scan"
    assert store.get_review(review.id).status == "resolved", (
        "a scan failure must not re-queue a landing that already committed"
    )
    assert not staging_dir.exists(), "the song landed — its staging is spent, not retained"
    assert dict(_events(bus, job.id))["track.error"]["stage"] == "scan"


def test_a_vanished_review_row_still_closes_the_stream(tmp_path):
    # If the row is torn between the route's claim and the worker picking it up,
    # run_resolve must still reach _finish — and therefore bus.close — or the channel
    # submit_resolve reopened hangs at `running`, pinging forever. `job_id` is a
    # parameter precisely so this path can name and close the right channel without a
    # review row to read it from. Draining under a timeout is the closure assertion:
    # if the bug regressed, the stream never ends and this times out instead of hanging
    # the whole suite.
    store = _store(tmp_path)
    job = store.create_job("https://youtu.be/abc")
    bus = EventBus()
    bus.reopen(job.id)  # what submit_resolve does before enqueueing
    bus.publish(job.id, "job.queued", {"job_id": job.id, "url": "u"})

    state = run_resolve(
        job.id, "no-such-review", ResolveRequest("reject"),
        store=store, registry=JobRegistry(), bus=bus,
    )
    assert state.status == "error"
    assert "no review" in (state.error or "")

    async def drain():
        return "".join([f async for f in bus.stream(job.id)])

    frames = asyncio.run(asyncio.wait_for(drain(), timeout=2.0))
    assert "track.error" in frames, "the torn-row path must emit a terminal event and close"


def test_a_vanished_staging_file_names_the_cause(tmp_path):
    # Staging lives under the system temp dir; an OS sweep can take it while the row
    # survives. The error must say so rather than surface a beets "no such file".
    store = _store(tmp_path)
    job, review, staging_dir = _parked(store, tmp_path)
    import shutil

    shutil.rmtree(staging_dir)
    state, _ = _run_resolve(store, review, ResolveRequest("rec-A", recording_id="rec-A"))
    assert state.status == "error"
    assert "staging copy for this review is gone" in state.error


def test_a_resolve_that_lands_nothing_is_an_error_not_a_false_done(tmp_path):
    store = _store(tmp_path)
    job, review, _ = _parked(store, tmp_path)
    state, _ = _run_resolve(
        store, review, ResolveRequest("rec-A", recording_id="rec-A"),
        resolve_fn=lambda *a, **k: [],
    )
    assert state.status == "error"


def test_staging_outside_a_cleanmuzik_dir_is_not_rmtreed(tmp_path):
    # A malformed staging_path must cost us the one file, never a recursive delete
    # of whatever directory it happens to name.
    store = _store(tmp_path)
    job = store.create_job("u")
    precious = tmp_path / "not-staging"
    precious.mkdir()
    (precious / "keep-me.txt").write_text("important")
    mp3 = precious / "song.mp3"
    mp3.write_bytes(b"mp3")
    review = store.create_review(
        job_id=job.id, staging_path=str(mp3), query="q", candidate_ids=[], rec="medium",
    )
    _run_resolve(store, review, ResolveRequest("reject"))
    assert not mp3.exists(), "the file itself is still removed"
    assert (precious / "keep-me.txt").exists(), "its parent must survive"


# --- _replace_existing: the ADR-009 guard -----------------------------------
#
# These are the tests that matter most in this file. ADR-009 exists because beets'
# DuplicateAction.REMOVE deletes the old file BEFORE copying the new one, so a copy
# failure loses both. `replace` inverts that order — and these assert the inversion
# actually holds under failure, which is the only condition that can prove it.


def test_replace_refuses_to_delete_when_the_new_copy_is_not_in_the_library(tmp_path):
    old_file = tmp_path / "old.mp3"
    old_file.write_bytes(b"old")
    old = _FakeItem(1, old_file, bitrate=192000)
    lib = _FakeLib([old])  # the import landed nothing new

    with pytest.raises(jobs_mod._StageFailure, match="never leave zero copies"):
        jobs_mod._replace_existing(lib, "rec-E", {1}, Outcome("landed", 0.0, 0.0))

    assert not old.removed, "the owner's file must survive an unconfirmed replace"
    assert old_file.exists()


def test_replace_refuses_to_delete_when_the_new_copy_is_not_on_disk(tmp_path):
    # The library row exists but the file doesn't — beets recorded it and the copy
    # failed. Deleting the old one here is exactly ADR-009's data-loss window.
    old_file = tmp_path / "old.mp3"
    old_file.write_bytes(b"old")
    old = _FakeItem(1, old_file, bitrate=192000)
    ghost = _FakeItem(2, tmp_path / "never-written.mp3", bitrate=320000)
    lib = _FakeLib([old, ghost])

    with pytest.raises(jobs_mod._StageFailure, match="not on disk"):
        jobs_mod._replace_existing(lib, "rec-E", {1}, Outcome("landed", 0.0, 0.0))

    assert not old.removed, "the owner's file must survive an unconfirmed replace"
    assert old_file.exists()


def test_replace_deletes_the_old_copy_only_after_the_new_one_is_confirmed(tmp_path):
    old_file = tmp_path / "old.mp3"
    old_file.write_bytes(b"old")
    new_file = tmp_path / "new.1.mp3"
    new_file.write_bytes(b"new")
    old = _FakeItem(1, old_file, bitrate=192000)
    new = _FakeItem(2, new_file, bitrate=320000)
    lib = _FakeLib([old, new])

    path = jobs_mod._replace_existing(lib, "rec-E", {1}, Outcome("landed", 0.0, 0.0))

    assert old.removed and not old_file.exists(), "the superseded copy is gone"
    assert new_file.exists(), "the upgrade is still there"
    assert new.moved, "the new copy reclaims the canonical path once it is free"
    assert path == str(new_file)


def test_replace_never_leaves_zero_copies_even_if_reorganize_fails(tmp_path):
    old_file = tmp_path / "old.mp3"
    old_file.write_bytes(b"old")
    new_file = tmp_path / "new.1.mp3"
    new_file.write_bytes(b"new")
    old = _FakeItem(1, old_file, bitrate=192000)
    new = _FakeItem(2, new_file, bitrate=320000)

    def bad_move():
        raise OSError("permission denied")

    new.move = bad_move
    path = jobs_mod._replace_existing(lib := _FakeLib([old, new]), "rec-E", {1}, Outcome("landed", 0.0, 0.0))
    # A tidy-up failure must not fail an otherwise-complete replace.
    assert new_file.exists()
    assert path == str(new_file)


def test_replace_refuses_when_two_library_files_share_the_recording_id(tmp_path):
    # Caught by /verify, not by review: `keep_both` is what CREATES this state (two
    # files, one recording id, different titles — a remaster shares a recording id).
    # A later `replace` used to delete BOTH, destroying the copy the owner had
    # deliberately kept. Spec §6 says replace deletes "THE existing file", singular,
    # and doesn't say which when there are two — so refuse rather than pick.
    store = _store(tmp_path)
    job, review, staging_dir = _parked(store, tmp_path, rec="duplicate", candidate_ids=("rec-E",))
    a = tmp_path / "orig.mp3"
    a.write_bytes(b"a")
    b = tmp_path / "orig (Remaster).mp3"
    b.write_bytes(b"b")
    kept_both = [_FakeItem(1, a, title="Song"), _FakeItem(2, b, title="Song (Remaster)")]
    landed = []

    state, _ = _run_resolve(
        store, review, ResolveRequest("replace", recording_id="rec-E"),
        lib=_FakeLib(kept_both),
        resolve_fn=lambda *a, **k: landed.append(1) or [Outcome("landed", 0.0, 0.0)],
    )

    assert state.status == "error"
    assert "share this recording id" in state.error
    assert not landed, "it must refuse BEFORE the import lands anything to unwind"
    assert not any(i.removed for i in kept_both), "neither copy may be deleted"
    assert a.exists() and b.exists()
    assert store.get_review(review.id).status == "pending", "still resolvable another way"
    assert staging_dir.exists()


def test_replace_still_works_for_the_ordinary_single_copy_case(tmp_path):
    # The guard above must not break the everyday path it protects.
    store = _store(tmp_path)
    job, review, staging_dir = _parked(store, tmp_path, rec="duplicate", candidate_ids=("rec-E",))
    old_file = tmp_path / "old.mp3"
    old_file.write_bytes(b"old")
    new_file = tmp_path / "new.mp3"
    new_file.write_bytes(b"new")
    old = _FakeItem(1, old_file, bitrate=192000)
    new = _FakeItem(2, new_file, bitrate=320000)
    lib = _FakeLib([old])

    def land(*a, **k):
        lib._items.append(new)  # the import adds the upgrade to the library
        return [Outcome("landed", 0.0, 0.0, landed_path=str(new_file), tags={}, chosen={})]

    state, _ = _run_resolve(
        store, review, ResolveRequest("replace", recording_id="rec-E"),
        lib=lib, resolve_fn=land,
    )
    assert state.status == "done"
    assert old.removed and not old_file.exists()
    assert new_file.exists()
    assert store.get_review(review.id).status == "resolved"


# --- 4. the routes ----------------------------------------------------------


class _FakeWorker:
    def __init__(self, store):
        self.registry = JobRegistry()
        self.bus = EventBus()
        self._store = store
        self.resolved = []

    def submit_resolve(self, job_id, review_id, request):
        # Mirror the real pre-flight: the ordering is what the route contract promises.
        self.bus.reopen(job_id)
        self.bus.publish(job_id, "job.queued", {"job_id": job_id, "url": "u"})
        self._store.update_job_status(job_id, "running")
        self.resolved.append((job_id, review_id, request))


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app.routes import reviews as reviews_routes

    store = _store(tmp_path)
    monkeypatch.setattr(reviews_routes, "get_store", lambda: store)

    app = FastAPI()
    app.include_router(reviews_routes.router, prefix="/api")
    worker = _FakeWorker(store)
    app.state.worker = worker
    c = TestClient(app)
    c.store = store
    c.worker = worker
    c.tmp_path = tmp_path
    return c


def test_get_reviews_lists_a_parked_song_with_its_shape(client, monkeypatch):
    _parked(client.store, client.tmp_path, candidate_ids=("rec-A",))
    monkeypatch.setattr(reviews_mod, "_hydration_cache", {})
    import beets.metadata_plugins as mp

    monkeypatch.setattr(
        mp, "track_for_id", lambda mbid, src: type("TI", (), {"title": "S", "artist": "B"})()
    )
    body = client.get("/api/reviews").json()
    assert len(body) == 1
    row = body[0]
    assert set(row) == {"review_id", "job_id", "query", "rec", "candidates"}
    assert row["rec"] == "medium"
    assert row["query"] == "artist title"
    assert row["candidates"][0]["candidate_id"] == "rec-A"


def test_resolve_unknown_review_404(client):
    assert client.post("/api/reviews/nope/resolve", json={"choice": "reject"}).status_code == 404


def test_resolve_body_mismatch_is_400_not_a_guess(client):
    _, review, _ = _parked(client.store, client.tmp_path)
    resp = client.post(f"/api/reviews/{review.id}/resolve", json={"choice": "replace"})
    assert resp.status_code == 400
    assert "duplicate review" in resp.json()["detail"]
    # A rejected body must leave the row untouched so the owner can just re-send.
    assert client.store.get_review(review.id).status == "pending"
    assert client.worker.resolved == []


def test_resolve_hands_the_decision_to_the_worker_and_claims_the_row(client):
    job, review, _ = _parked(client.store, client.tmp_path)
    resp = client.post(f"/api/reviews/{review.id}/resolve", json={"choice": "rec-A"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert client.store.get_review(review.id).status == "resolving"
    assert client.worker.resolved == [(job.id, review.id, ResolveRequest("rec-A", recording_id="rec-A"))]


def test_a_failed_hand_off_releases_the_claim_so_the_owner_can_retry(client, monkeypatch):
    # claim_review flips the row to `resolving`. If submit_resolve then raises, the row
    # must go back to `pending` — otherwise it is stranded: invisible to GET /api/reviews
    # and un-retryable (a second POST 409s on the claim) until a full restart.
    job, review, _ = _parked(client.store, client.tmp_path)

    def boom(*a, **k):
        raise RuntimeError("worker hand-off blew up")

    monkeypatch.setattr(client.worker, "submit_resolve", boom)
    resp = client.post(f"/api/reviews/{review.id}/resolve", json={"choice": "rec-A"})
    assert resp.status_code == 500
    assert client.store.get_review(review.id).status == "pending", (
        "a failed hand-off must leave the review retryable, not stranded in `resolving`"
    )


def test_double_click_resolve_is_409_and_enqueues_once(client):
    # The real case: a double-clicked button must not land the song twice.
    job, review, _ = _parked(client.store, client.tmp_path)
    first = client.post(f"/api/reviews/{review.id}/resolve", json={"choice": "rec-A"})
    second = client.post(f"/api/reviews/{review.id}/resolve", json={"choice": "rec-A"})
    assert first.status_code == 200
    assert second.status_code == 409
    assert len(client.worker.resolved) == 1, "exactly one resolve reaches the worker"


def test_resolve_reopens_the_stream_and_flips_status_before_returning(client):
    # The T-017 contract: the card closed its EventSource on track.review_required and
    # opens a FRESH one after this POST returns. If the channel were still closed, or
    # the row still said 'review', that new stream would be dead on arrival.
    job, review, _ = _parked(client.store, client.tmp_path)
    bus = client.worker.bus
    bus.publish(job.id, "track.review_required", {"job_id": job.id})
    bus.close(job.id)
    assert client.store.get_job(job.id).status == "review"

    client.post(f"/api/reviews/{review.id}/resolve", json={"choice": "rec-A"})

    assert client.store.get_job(job.id).status == "running", "terminal= would kill the new stream"

    async def drain():
        # Not terminal any more, so stream() subscribes rather than replay-and-return.
        return [f async for f in bus.stream(job.id, terminal=False, ping_interval=0.01)]

    async def run():
        task = asyncio.ensure_future(drain())
        await asyncio.sleep(0.05)
        bus.publish(job.id, "track.done", {"job_id": job.id})
        bus.close(job.id)
        return await task

    frames = parse_sse("".join(asyncio.run(run())))
    names = [n for n, _ in frames if n != "ping"]
    # The acquire episode is GONE from the replay — replaying track.review_required
    # would make T-016's card close itself instantly and hang at "Needs review".
    assert "track.review_required" not in names
    assert names == ["job.queued", "track.done"]
