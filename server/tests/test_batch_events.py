"""T-305 tests — batch-scoped SSE: one stream per batch, new events, terminal state.

All offline, same fixtures as the T-303 suite (recording fakes, absent Jellyfin, a
REAL temp Store). The ticket's "Done when", one section each:

1. **The DAO** — `count_jobs_by_status`: grouped per playlist, newest attempt per
   position (a re-paste must not double the tally), other playlists/single-songs excluded.
2. **The payload** — `batch_progress_payload`: the bucket mapping and the derived state
   (running / waiting_on_you / done; a failed member never blocks "done" — ADR-002).
3. **The pin** — the long-lived batch channel survives member-channel churn past the
   cap; `unpin` releases the exemption.
4. **Dual-publish** — a member's events ride BOTH channels: the job channel unchanged
   (byte-for-byte R1), the batch channel stamped with `position`/`job_id`; a single-song
   run creates no batch channel at all.
5. **The grind** — a 4-track batch (land / park / fail / skip): the tally matches the
   real outcomes, the forced failure leaves the rest running, terminal state is
   "waiting on you" while parked > 0, and the resolve flips it to "done" and closes
   the batch channel.
6. **The routes** — expansion opens the stream (`batch.queued` + opening tally, pinned,
   fresh episode per paste); `GET /api/playlists/{id}/events` 404s unknown ids and
   closes at once for a settled batch with no resident channel (the eviction lesson).
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import Store
from app.events import (
    EventBus,
    batch_channel,
    batch_progress_payload,
)
from app.import_seam import Outcome
from app.jobs import JobRegistry, run_pipeline, run_resolve
from app.reviews import ResolveRequest
from app.source_signals import SourceSignals
from test_events import _drain  # sibling test module (server/tests on sys.path)


_ABSENT = Settings(jellyfin_url="", jellyfin_api_key="")


def _store(tmp_path):
    store = Store(tmp_path / "jobs.db")
    store.init_schema()
    return store


def _batch(store, video_ids, *, yt_id="PLbatch", title="Batch Mix"):
    """A playlist row plus one queued member job per video id, positions 1..N."""
    playlist = store.upsert_playlist(yt_id, title)
    members = [
        store.create_job(
            f"https://www.youtube.com/watch?v={vid}",
            playlist_id=playlist.id,
            position=position,
            youtube_video_id=vid,
        )
        for position, vid in enumerate(video_ids, start=1)
    ]
    return playlist, members


def _recording_download(calls):
    def download(url, staging_dir):
        calls.append(url)
        path = staging_dir / "song.webm"
        path.write_bytes(b"audio")
        return path, SourceSignals.from_info({"id": "vid", "title": "Song"})

    return download


def _fake_transcode(source):
    mp3 = source.with_suffix(".mp3")
    mp3.write_bytes(b"mp3")
    return mp3


_LANDED = [
    Outcome(
        "landed", 0.95, 0.5, track_id="rec-A",
        landed_path="/lib/Band/Song.mp3", tags={"artist": "Band"},
    )
]


def _run_member(store, job, tmp_path, *, bus, calls=None, **overrides):
    """One member through the pipeline: recording fakes, absent Jellyfin, shared bus."""
    kwargs = dict(
        store=store, registry=JobRegistry(), settings=_ABSENT, staging_root=tmp_path,
        bus=bus,
        download_fn=_recording_download(calls if calls is not None else []),
        transcode_fn=_fake_transcode,
        import_fn=lambda *a, **k: list(_LANDED),
        scan_fn=lambda **k: True,
    )
    kwargs.update(overrides)
    return run_pipeline(job.id, job.url, **kwargs)


def _batch_events(bus, key):
    """The batch channel's buffered (event, payload) pairs, closed or not.

    `_drain` only terminates once a channel is closed, and a live batch's channel is
    deliberately never closed mid-grind — so these assertions read the replay buffer
    directly, the same way the T-013 suite inspects `bus._channels` for eviction.
    """
    return list(bus._channels[key].events)


# --- 1. the DAO --------------------------------------------------------------


class TestCountJobsByStatus:
    def test_groups_this_playlists_statuses(self, tmp_path):
        store = _store(tmp_path)
        playlist, members = _batch(store, ["v1", "v2", "v3", "v4"])
        for job, status in zip(members, ["done", "review", "error", "skipped"]):
            store.update_job_status(job.id, status)
        assert store.count_jobs_by_status(playlist.id) == {
            "done": 1, "review": 1, "error": 1, "skipped": 1,
        }

    def test_newest_attempt_per_position_wins(self, tmp_path):
        # A re-paste writes a second generation of rows against the same slots; the
        # tally must describe THIS grind, not double the batch (50 tracks read as 100).
        store = _store(tmp_path)
        playlist, first = _batch(store, ["v1", "v2"])
        for job in first:
            store.update_job_status(job.id, "done")
        _, second = _batch(store, ["v1", "v2"])  # re-paste: same playlist, same positions
        for job in second:
            store.update_job_status(job.id, "skipped")
        assert store.count_jobs_by_status(playlist.id) == {"skipped": 2}

    def test_other_playlists_and_single_songs_are_excluded(self, tmp_path):
        store = _store(tmp_path)
        playlist, _ = _batch(store, ["v1"])
        other, _ = _batch(store, ["v9"], yt_id="PLother")
        store.create_job("https://youtu.be/solo")  # R1 single-song, playlist_id NULL
        assert store.count_jobs_by_status(playlist.id) == {"queued": 1}
        assert store.count_jobs_by_status(other.id) == {"queued": 1}


# --- 2. the payload ----------------------------------------------------------


class TestProgressPayload:
    def test_buckets_and_running_folds_into_queued(self):
        payload = batch_progress_payload("pl", {
            "done": 2, "review": 1, "error": 1, "skipped": 3, "queued": 2, "running": 1,
        })
        assert payload == {
            "playlist_id": "pl", "landed": 2, "in_review": 1, "failed": 1,
            "skipped": 3, "queued": 3, "total": 10, "state": "running",
        }

    def test_waiting_on_you_while_parked_outranks_done(self):
        # The load-bearing derivation (US17): a finished grind with parked tracks is
        # the owner's turn — never "done".
        payload = batch_progress_payload("pl", {"done": 4, "review": 1})
        assert payload["state"] == "waiting_on_you"

    def test_failures_never_block_done(self):
        # ADR-002: one failure continues the batch — and doesn't poison its terminal.
        payload = batch_progress_payload("pl", {"done": 3, "error": 2})
        assert payload["state"] == "done"
        assert payload["failed"] == 2


# --- 3. the pin --------------------------------------------------------------


def test_pinned_batch_channel_survives_member_churn():
    bus = EventBus(cap=2)
    key = batch_channel("pl")
    bus.pin(key)
    bus.publish(key, "batch.queued", {"playlist_id": "pl", "title": "T", "total": 50})
    # Churn far more member channels than the cap holds — each one created and closed,
    # exactly the lifecycle of a batch's short per-job channels.
    for n in range(6):
        bus.publish(f"member-{n}", "job.queued", {"job_id": f"member-{n}", "url": "u"})
        bus.close(f"member-{n}")
    assert key in bus._channels, "the pinned batch channel must never be evicted"
    assert _batch_events(bus, key) == [
        ("batch.queued", {"playlist_id": "pl", "title": "T", "total": 50})
    ], "the replay buffer must survive the churn intact"
    # Control: an unpinned channel of the same vintage was evicted by the same churn.
    assert "member-0" not in bus._channels


def test_unpin_releases_the_exemption():
    bus = EventBus(cap=1)
    key = batch_channel("pl")
    bus.pin(key)
    bus.publish(key, "batch.queued", {"total": 1})
    bus.unpin(key)
    bus.publish("newer", "job.queued", {"job_id": "newer", "url": "u"})  # over cap
    assert key not in bus._channels, "an unpinned channel ages out like any other"


# --- 4. dual-publish ---------------------------------------------------------


def test_member_events_dual_publish_with_the_stamp(tmp_path):
    store = _store(tmp_path)
    # Position 1 would be indistinguishable from an accidental constant; use a 3-track
    # batch and run the third so the stamp provably carries the member's own slot.
    playlist, members = _batch(store, ["v1", "v2", "v3"], yt_id="PLstamp")
    job = members[2]
    bus = EventBus()
    state = _run_member(store, job, tmp_path, bus=bus)
    assert state.status == "done"

    # The job channel: the R1 sequence, byte-for-byte — no stamp, no batch events.
    job_events = _drain(bus, job.id)
    assert [name for name, _ in job_events] == [
        "job.queued", "track.downloading", "track.transcoding", "track.identifying",
        "track.tagging", "track.done",
    ]
    assert all("position" not in data for _, data in job_events), (
        "the per-job stream must be unchanged by batch scoping"
    )

    # The batch channel: the same events, each stamped, plus the terminal tally.
    key = batch_channel(playlist.id)
    batch = _batch_events(bus, key)
    assert [name for name, _ in batch[:-1]] == [name for name, _ in job_events]
    for name, data in batch[:-1]:
        assert data["position"] == 3
        assert data["job_id"] == job.id
    name, tally = batch[-1]
    assert name == "batch.progress"
    assert tally["landed"] == 1 and tally["queued"] == 2 and tally["state"] == "running"


def test_single_song_r1_run_creates_no_batch_channel(tmp_path):
    store = _store(tmp_path)
    job = store.create_job("https://youtu.be/solo")
    bus = EventBus()
    state = _run_member(store, job, tmp_path, bus=bus)
    assert state.status == "done"
    assert list(bus._channels) == [job.id], (
        "a NULL-playlist paste must touch only its own channel (acceptance item 11)"
    )


def test_skip_rides_the_batch_stream_with_the_stamp(tmp_path):
    # The T-303 idempotent re-paste view: `track.skipped` must reach the batch card too.
    store = _store(tmp_path)
    owned = tmp_path / "lib" / "Song.mp3"
    owned.parent.mkdir(parents=True)
    owned.write_bytes(b"owned-mp3")
    prior = store.create_job("https://youtu.be/prior", youtube_video_id="vidX")
    store.update_job_status(prior.id, "done")
    store.set_landed_path(prior.id, str(owned))

    playlist, members = _batch(store, ["vidX", "vidY"])
    bus = EventBus()
    calls = []
    state = _run_member(store, members[0], tmp_path, bus=bus, calls=calls)
    assert state.status == "skipped"
    assert calls == [], "an owned video must not be re-downloaded"

    batch = dict(_batch_events(bus, batch_channel(playlist.id)))
    skipped = batch["track.skipped"]
    assert skipped["position"] == 1 and skipped["job_id"] == members[0].id
    assert batch["batch.progress"]["skipped"] == 1


# --- 5. the grind: tally, one-failure-continues, terminal state --------------


def _boom(*a, **k):
    raise RuntimeError("download exploded")


def _parking_import(store):
    """An import that parks with a REAL review row, as the seam does — so the parked
    member is resolvable by `run_resolve` afterwards (the terminal-flip test)."""

    def import_fn(mp3, *, store=store, job_id, query, settings, source_signals):
        review = store.create_review(
            job_id=job_id, staging_path=str(mp3), query=query,
            candidate_ids=["rec-A"], rec="medium",
        )
        return [Outcome("parked", 0.2, 0.0, review_id=review.id)]

    return import_fn


class _FakeLib:
    def items(self, _query):
        return []


def _grind(store, tmp_path, bus):
    """A 4-track batch through the pipeline: land / park / fail / skip, one shared bus.

    Returns (playlist, members). The skip's prior landing is staged first so member 4
    hits the T-303 owned-video gate.
    """
    owned = tmp_path / "lib" / "Owned.mp3"
    owned.parent.mkdir(parents=True, exist_ok=True)
    owned.write_bytes(b"owned-mp3")
    prior = store.create_job("https://youtu.be/prior", youtube_video_id="v4")
    store.update_job_status(prior.id, "done")
    store.set_landed_path(prior.id, str(owned))

    playlist, members = _batch(store, ["v1", "v2", "v3", "v4"])
    per_member = [
        {},  # v1 lands
        {"import_fn": _parking_import(store)},  # v2 parks
        {"download_fn": _boom},  # v3 fails at download
        {},  # v4 skips (owned)
    ]
    calls: list = []
    for job, overrides in zip(members, per_member):
        _run_member(store, job, tmp_path, bus=bus, calls=calls, **overrides)
    return playlist, members, calls


def test_tally_matches_real_outcomes_and_a_failure_continues_the_batch(tmp_path):
    store = _store(tmp_path)
    bus = EventBus()
    playlist, members, calls = _grind(store, tmp_path, bus)

    # ADR-002: the forced v3 failure ended THAT job, not the batch — the members after
    # it still processed (v4 reached its skip gate; v1/v2 downloaded before it).
    assert store.get_job(members[2].id).status == "error"
    assert store.get_job(members[3].id).status == "skipped"
    assert len(calls) == 2, "v1 and v2 downloaded; v3 exploded; v4 skipped the download"

    key = batch_channel(playlist.id)
    tallies = [data for name, data in _batch_events(bus, key) if name == "batch.progress"]
    assert len(tallies) == 4, "one recomputed tally per member terminal"
    assert tallies[-1] == {
        "playlist_id": playlist.id, "landed": 1, "in_review": 1, "failed": 1,
        "skipped": 1, "queued": 0, "total": 4, "state": "waiting_on_you",
    }
    # And the tally is cumulative-correct mid-grind too, because it is recomputed from
    # SQLite each time — never accumulated in memory.
    assert tallies[0]["landed"] == 1 and tallies[0]["queued"] == 3

    # Parked > 0 ⇒ the stream stays open for the resolve tail — never closed as "done".
    assert bus._channels[key].closed is False
    assert key in bus._pinned


def test_resolving_the_park_flips_waiting_on_you_to_done_and_closes(tmp_path):
    store = _store(tmp_path)
    bus = EventBus()
    playlist, members, _ = _grind(store, tmp_path, bus)
    review = store.get_pending_review_for_job(members[1].id)

    state = run_resolve(
        members[1].id, review.id, ResolveRequest("rec-A", recording_id="rec-A"),
        store=store, registry=JobRegistry(), settings=_ABSENT, bus=bus,
        lib=_FakeLib(),
        resolve_fn=lambda *a, **k: list(_LANDED),
        scan_fn=lambda **k: True,
    )
    assert state.status == "done"

    # The resolve tail rode the batch stream, stamped with the member's slot…
    key = batch_channel(playlist.id)
    events = _batch_events(bus, key)
    tail = [data for name, data in events if name == "track.done"]
    assert any(d["position"] == 2 and d["job_id"] == members[1].id for d in tail)
    # …and the terminal tally flipped: nothing parked ⇒ "done", not "waiting on you".
    name, tally = events[-1]
    assert name == "batch.progress"
    assert tally["in_review"] == 0 and tally["landed"] == 2
    assert tally["state"] == "done"
    # A settled batch closes its channel (clean end-of-stream, no eternal pings) and
    # releases the pin; the replay still serves a late subscriber in full.
    assert bus._channels[key].closed is True
    assert key not in bus._pinned
    assert [n for n, _ in _drain(bus, key)][-1] == "batch.progress"


# --- 6. the routes -----------------------------------------------------------


class _FakeWorker:
    def __init__(self):
        self.registry = JobRegistry()
        self.bus = EventBus()
        self.submitted = []

    def submit(self, job_id, url):
        self.submitted.append((job_id, url))


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app.routes import jobs as jobs_routes

    store = _store(tmp_path)
    monkeypatch.setattr(jobs_routes, "get_store", lambda: store)

    app = FastAPI()
    app.include_router(jobs_routes.router, prefix="/api")
    worker = _FakeWorker()
    app.state.worker = worker
    test_client = TestClient(app)
    test_client.store = store
    test_client.worker = worker
    return test_client


def _paste(client, monkeypatch):
    from test_jobs import _stub_expansion  # sibling: the T-302 expansion stubs

    _stub_expansion(monkeypatch, entries=[("v1", "First"), ("v2", "Second")],
                    title="Summer 2026", yt_id="PLsummer")
    resp = client.post(
        "/api/jobs", json={"url": "https://youtube.com/playlist?list=PLsummer"}
    )
    assert resp.status_code == 200
    return resp.json()


def test_expansion_opens_the_batch_stream(client, monkeypatch):
    body = _paste(client, monkeypatch)
    key = batch_channel(body["playlist_id"])
    bus = client.worker.bus

    events = _batch_events(bus, key)
    assert events[0] == ("batch.queued", {
        "playlist_id": body["playlist_id"], "title": "Summer 2026", "total": 2,
    })
    # The opening tally: recomputed from the rows just written — all queued.
    name, tally = events[1]
    assert name == "batch.progress"
    assert tally["queued"] == 2 and tally["total"] == 2 and tally["state"] == "running"
    # Announced BEFORE any member was handed to the worker, so no member event can
    # precede `batch.queued` in the replay; and pinned against the coming churn.
    assert key in bus._pinned
    assert len(client.worker.submitted) == 2


def test_repaste_starts_a_fresh_episode(client, monkeypatch):
    first = _paste(client, monkeypatch)
    key = batch_channel(first["playlist_id"])
    second = _paste(client, monkeypatch)
    assert second["playlist_id"] == first["playlist_id"]  # T-307 idempotent re-paste
    # `reopen` cleared the first paste's episode: a new subscriber replays only this
    # grind's opener + tally, never a stale terminal state from the previous one.
    events = _batch_events(client.worker.bus, key)
    assert [name for name, _ in events] == ["batch.queued", "batch.progress"]


def test_stream_route_404s_an_unknown_playlist(client):
    assert client.get("/api/playlists/nope/events").status_code == 404


def test_stream_route_closes_at_once_for_a_settled_batch_with_no_channel(client):
    # The 2026-07-16 eviction lesson, batch edition: after a restart the channel is
    # gone; a settled batch must replay nothing and end — not fabricate a fresh open
    # channel and ping forever.
    store = client.store
    playlist, members = _batch(store, ["v1", "v2"])
    for job in members:
        store.update_job_status(job.id, "done")
    resp = client.get(f"/api/playlists/{playlist.id}/events")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert resp.text == ""


# --- 7. review-finding regressions ------------------------------------------
# The T-305 review surfaced two paths a member can settle through that bypass
# `_BatchScopedBus` — the worker-loop backstop, and a tally-read failure at the final
# member — either of which could strand the batch channel open + pinned and hang a
# reconnecting client on pings forever. The fix settles the batch through one shared
# helper on the backstop path, and self-heals on reconnect from the durable tally.


def test_backstop_settles_the_batch_when_a_runner_escapes(tmp_path, monkeypatch):
    # run_pipeline is contracted never to raise; if it does anyway (the escape the
    # worker-loop backstop exists for), the backstop must settle the member's BATCH
    # channel too — not just close the raw member channel. A single-member batch makes
    # the escape the LAST terminal, so nothing else could retire the channel afterwards.
    from app import jobs as jobs_mod

    store = _store(tmp_path)

    def boom(job_id, url, **kwargs):
        raise RuntimeError("escaped the never-raises contract")

    monkeypatch.setattr(jobs_mod, "run_pipeline", boom)
    worker = jobs_mod.JobWorker(store)
    worker.start()  # boot reconcile runs first, before any batch row exists
    playlist, members = _batch(store, ["v1"])
    key = batch_channel(playlist.id)
    worker.bus.pin(key)  # as expansion would have
    try:
        worker.submit(members[0].id, members[0].url)
        worker._queue.join()
    finally:
        worker.stop()

    assert store.get_job(members[0].id).status == "error", "backstop error-set the row"
    events = _batch_events(worker.bus, key)
    assert events and events[-1][0] == "batch.progress"
    assert events[-1][1]["state"] == "done", "errored last member ⇒ nothing pending ⇒ done"
    assert worker.bus._channels[key].closed is True
    assert key not in worker.bus._pinned, "a settled batch releases its eviction pin"


def test_stream_route_self_heals_an_orphaned_open_channel(client):
    # The final member settling through a bypass path can leave a resident, OPEN, pinned
    # channel for a batch the durable tally already calls done. A `terminal` hint alone
    # can't retire an existing-but-open channel, so the route closes + unpins it before
    # streaming — the client replays the buffer and ends, instead of pinging forever.
    store = client.store
    playlist, members = _batch(store, ["v1", "v2"])
    for job in members:
        store.update_job_status(job.id, "done")
    bus = client.worker.bus
    key = batch_channel(playlist.id)
    bus.pin(key)  # the orphan: pinned + open, for a durably-settled batch
    bus.publish(key, "batch.progress", {"playlist_id": playlist.id, "state": "running"})
    assert bus._channels[key].closed is False

    resp = client.get(f"/api/playlists/{playlist.id}/events")
    assert resp.status_code == 200  # returned — did not hang on pings
    assert bus._channels[key].closed is True
    assert key not in bus._pinned


def test_payload_bucket_keys_track_the_real_status_constants():
    # batch_progress_payload reads app.jobs' STATUS_* values as local string literals to
    # keep this import-light module off the beets-heavy app.jobs. Couple them here so a
    # rename of a STATUS_* constant can't silently zero a bucket — which would under-report
    # the tally and, worse, could flip a still-open batch to "done" and close its stream.
    from app.jobs import (
        STATUS_DONE,
        STATUS_ERROR,
        STATUS_REVIEW,
        STATUS_RUNNING,
        STATUS_SKIPPED,
    )

    payload = batch_progress_payload("pl", {
        STATUS_DONE: 1, STATUS_REVIEW: 2, STATUS_ERROR: 3,
        STATUS_SKIPPED: 4, STATUS_RUNNING: 5, "queued": 6,
    })
    assert payload["landed"] == 1
    assert payload["in_review"] == 2
    assert payload["failed"] == 3
    assert payload["skipped"] == 4
    assert payload["queued"] == 11, "running folds into queued (5 + 6)"
