"""T-012 tests — the pipeline orchestration + job routes, all offline.

Two layers:

1. `run_pipeline` walks the stages in order and reacts correctly to each outcome:
   a landed song triggers a scan and cleans staging; a parked song records the
   review and *retains* staging; every stage failure records the failing stage and
   cleans staging. The real stage functions (download/transcode/import/scan) are
   injected fakes — no yt-dlp, ffmpeg, beets, or network — against a REAL temp
   Store so the durable status is a real row.
2. The routes: a playlist URL is refused with 422, a good URL creates a job and
   hands it to the worker, and the snapshot overlays the live registry. Driven with
   a minimal app (no lifespan → no beets) and a fake worker on app.state.
"""

import asyncio

import acoustid
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.jobs as jobs
from app.db import Store
from app.events import EventBus
from app.import_seam import Outcome
from app.jellyfin import JellyfinScanError
from app.jobs import JobRegistry, JobWorker, run_pipeline
from app.reviews import ResolveRequest
from test_events import parse_sse  # sibling test module (server/tests on sys.path)


# --- helpers ----------------------------------------------------------------


def _store(tmp_path):
    store = Store(tmp_path / "jobs.db")
    store.init_schema()
    return store


def _fake_download(record):
    """A download that writes a staging file and records the staging dir it got."""

    def download(url, staging_dir):
        record["staging_dir"] = staging_dir
        path = staging_dir / "song.webm"
        path.write_bytes(b"audio")
        return path

    return download


def _fake_transcode(source):
    mp3 = source.with_suffix(".mp3")
    mp3.write_bytes(b"mp3")
    return mp3


def _run(tmp_path, url="https://youtu.be/abc", **overrides):
    """Create a job row and run the pipeline with injected fakes; return (state, rec).

    Staging is rooted under `tmp_path` so pytest cleans it — the parked path retains
    its staging dir by design, which would otherwise leak real /tmp dirs.
    """
    record = {}
    store = _store(tmp_path)
    job = store.create_job(url)
    registry = JobRegistry()
    kwargs = dict(
        store=store,
        registry=registry,
        staging_root=tmp_path,
        download_fn=_fake_download(record),
        transcode_fn=_fake_transcode,
        import_fn=lambda *a, **k: [Outcome("landed", 0.95, 0.5, track_id="rec-A")],
        scan_fn=lambda **k: True,
    )
    kwargs.update(overrides)
    state = run_pipeline(job.id, url, **kwargs)
    record["registry"] = registry
    record["job_id"] = job.id
    record["store"] = store
    return state, record


# --- run_pipeline: the happy paths ------------------------------------------


def test_landed_song_scans_and_cleans_staging(tmp_path):
    scans = []
    state, rec = _run(tmp_path, scan_fn=lambda **k: scans.append(k) or True)
    assert state.status == "done"
    assert scans, "a landed track must trigger a Jellyfin scan"
    assert not rec["staging_dir"].exists(), "landed staging must be cleaned"


def test_landed_status_is_durable(tmp_path):
    state, rec = _run(tmp_path)
    assert rec["store"].get_job(rec["job_id"]).status == "done"


def test_scan_degraded_is_not_a_failure(tmp_path):
    # trigger_scan returns False when the Jellyfin config is absent — the track
    # still landed, so the job is done, not errored (T-010 contract).
    state, rec = _run(tmp_path, scan_fn=lambda **k: False)
    assert state.status == "done"
    assert state.error is None
    assert not rec["staging_dir"].exists()


def test_parked_song_records_review_and_retains_staging(tmp_path):
    state, rec = _run(
        tmp_path,
        import_fn=lambda *a, **k: [Outcome("parked", 0.2, 0.0, review_id="rev-9")],
    )
    assert state.status == "review"
    assert state.review_id == "rev-9"
    assert rec["staging_dir"].exists(), "a parked song keeps its staging copy"


def test_skipped_duplicate_is_done_without_scan(tmp_path):
    scans = []
    state, rec = _run(
        tmp_path,
        import_fn=lambda *a, **k: [Outcome("skipped", 0.95, 0.5)],
        scan_fn=lambda **k: scans.append(k) or True,
    )
    assert state.status == "done"
    assert scans == [], "a duplicate-skip lands nothing new — no scan"
    assert not rec["staging_dir"].exists()


# --- run_pipeline: every stage failure names its stage and cleans staging ----


def _boom(*a, **k):
    raise RuntimeError("stage exploded")


def test_download_failure_names_download_and_cleans(tmp_path):
    record = {}

    def failing_download(url, staging_dir):
        record["staging_dir"] = staging_dir
        raise RuntimeError("yt-dlp died")

    store = _store(tmp_path)
    job = store.create_job("u")
    state = run_pipeline(
        job.id, "u", store=store, registry=JobRegistry(), staging_root=tmp_path,
        download_fn=failing_download, transcode_fn=_fake_transcode,
        import_fn=lambda *a, **k: [], scan_fn=lambda **k: True,
    )
    assert state.status == "error"
    assert state.stage == "download"
    assert not record["staging_dir"].exists()
    assert store.get_job(job.id).status == "error"


def test_transcode_failure_names_transcode(tmp_path):
    state, rec = _run(tmp_path, transcode_fn=_boom)
    assert state.status == "error"
    assert state.stage == "transcode"
    assert not rec["staging_dir"].exists()


def test_missing_fingerprint_backend_names_identify(tmp_path):
    def no_backend(*a, **k):
        raise acoustid.NoBackendError("fpcalc gone")

    state, rec = _run(tmp_path, import_fn=no_backend)
    assert state.status == "error"
    assert state.stage == "identify"
    assert not rec["staging_dir"].exists()


def test_beets_apply_failure_names_land(tmp_path):
    state, rec = _run(tmp_path, import_fn=_boom)
    assert state.status == "error"
    assert state.stage == "land"


def test_scan_error_on_landed_names_scan_and_cleans(tmp_path):
    def scan_fails(**k):
        raise JellyfinScanError("401 from a stale key")

    state, rec = _run(tmp_path, scan_fn=scan_fails)
    assert state.status == "error"
    assert state.stage == "scan"
    # The file already landed in the library; only the staging copy is cleaned.
    assert not rec["staging_dir"].exists()


def test_empty_outcome_is_an_error_not_a_false_done(tmp_path):
    # A song that neither landed nor parked (beets skipped the task before the gate)
    # must not report success — it silently vanished.
    state, rec = _run(tmp_path, import_fn=lambda *a, **k: [])
    assert state.status == "error"
    assert state.stage == "identify"
    assert not rec["staging_dir"].exists()


def test_park_then_raise_keeps_staging_and_reports_review(tmp_path):
    # choose_item parks a review (writing the row) and then a later beets stage
    # raises. The staging file the review points at must NOT be deleted.
    store = _store(tmp_path)
    job = store.create_job("u")

    def park_then_boom(staging_path, *, store, job_id, query, settings=None):
        store.create_review(
            job_id=job_id, staging_path=str(staging_path), query=query,
            candidate_ids=["rec-A"], rec="medium",
        )
        raise RuntimeError("beets organize blew up after the park")

    record = {}
    registry = JobRegistry()
    state = run_pipeline(
        job.id, "u", store=store, registry=registry, staging_root=tmp_path,
        download_fn=_fake_download(record), transcode_fn=_fake_transcode,
        import_fn=park_then_boom, scan_fn=lambda **k: True,
    )
    assert state.status == "review"
    assert state.review_id is not None
    assert record["staging_dir"].exists(), "the parked review's file must survive"


# --- run_pipeline: the SSE event sequence emitted through the stages (T-013) --
#
# The pipeline emits each spec §6 event at its stage transition. These drive the
# REAL run_pipeline with a real EventBus (no subscribers, so publishing just buffers)
# and then read the buffered stream back — proving the ordered sequence and payloads
# without a socket. The rich payloads (chosen / tags / candidates) are set on the
# injected Outcome, exactly as the seam would fill them at land / park time.


def _events_after_run(tmp_path, **overrides):
    """Run the pipeline with a real bus, then drain its (now-closed) stream to the
    ordered (event, payload) list a subscriber would have seen."""
    bus = EventBus()
    state, rec = _run(tmp_path, bus=bus, **overrides)

    async def drain():
        return "".join([frame async for frame in bus.stream(rec["job_id"])])

    return state, parse_sse(asyncio.run(drain()))


def test_sse_landed_emits_full_ordered_sequence(tmp_path):
    landed = Outcome(
        "landed", 0.95, 0.5, track_id="rec-A",
        chosen={"title": "Song", "artist": "Band", "album": "LP", "year": 2020},
        tags={
            "title": "Song", "artist": "Band", "album": "LP", "year": 2020,
            "genre": "Rock", "has_art": True, "has_lyrics": True,
        },
        landed_path="/lib/Band/Song.mp3",
    )
    state, events = _events_after_run(tmp_path, import_fn=lambda *a, **k: [landed])
    assert state.status == "done"
    assert [name for name, _ in events] == [
        "job.queued",
        "track.downloading",
        "track.transcoding",
        "track.identifying",
        "track.tagging",
        "track.done",
    ]
    payloads = dict(events)
    assert payloads["job.queued"]["url"] == "https://youtu.be/abc"
    assert payloads["track.tagging"]["chosen"]["title"] == "Song"
    done = payloads["track.done"]
    assert done["path"] == "/lib/Band/Song.mp3"
    assert done["tags"]["genre"] == "Rock"
    assert done["tags"]["has_art"] is True
    assert done["tags"]["has_lyrics"] is True


def test_sse_parked_emits_review_required_with_candidates(tmp_path):
    # Build the candidate through the one canonical shaper so this test can't drift
    # from the contract (ADR-010: candidate == candidate_id/title/artist/score, no
    # album/year/art_url — those were removed, not left null).
    from app.events import candidate_row

    candidates = [candidate_row("rec-A", title="Song", artist="Band", score=0.8)]
    parked = Outcome("parked", 0.2, 0.0, review_id="rev-9", candidates=candidates)
    state, events = _events_after_run(tmp_path, import_fn=lambda *a, **k: [parked])
    assert state.status == "review"
    assert [name for name, _ in events] == [
        "job.queued",
        "track.downloading",
        "track.transcoding",
        "track.identifying",
        "track.review_required",
    ]
    rr = dict(events)["track.review_required"]
    assert rr["review_id"] == "rev-9"
    assert rr["query"] == ""  # a 3-byte fake mp3 has no readable title → empty query
    assert rr["candidates"][0]["candidate_id"] == "rec-A"
    assert rr["candidates"][0]["score"] == 0.8
    assert set(rr["candidates"][0]) == {"candidate_id", "title", "artist", "score"}


def test_sse_error_names_the_failing_stage(tmp_path):
    state, events = _events_after_run(tmp_path, transcode_fn=_boom)
    assert state.status == "error"
    assert [name for name, _ in events] == [
        "job.queued",
        "track.downloading",
        "track.transcoding",
        "track.error",
    ]
    err = dict(events)["track.error"]
    assert err["stage"] == "transcode"
    assert err["message"]  # a human-readable message rides along


def test_sse_download_error_names_download_stage(tmp_path):
    def failing_download(url, staging_dir):
        (staging_dir / "x").write_bytes(b"")
        raise RuntimeError("yt-dlp died")

    state, events = _events_after_run(tmp_path, download_fn=failing_download)
    assert dict(events)["track.error"]["stage"] == "download"


def test_sse_skipped_duplicate_emits_no_terminal_event_but_closes(tmp_path):
    # A duplicate skip lands nothing, so no §6 event fits — the stream still closes
    # (drain returns), and the client falls back to the GET /api/jobs snapshot.
    state, events = _events_after_run(
        tmp_path, import_fn=lambda *a, **k: [Outcome("skipped", 0.95, 0.5)]
    )
    assert state.status == "done"
    assert [name for name, _ in events] == [
        "job.queued",
        "track.downloading",
        "track.transcoding",
        "track.identifying",
    ]  # no track.done — nothing landed


# --- boot reconciliation: no job is left 'running' after a restart ----------


def test_worker_start_fails_orphaned_jobs(tmp_path):
    store = _store(tmp_path)
    stuck = store.create_job("u")  # created as "queued"
    store.update_job_status(stuck.id, "running")
    done = store.create_job("v")
    store.update_job_status(done.id, "done")

    worker = JobWorker(store)
    worker.start()  # reconciles on startup
    worker.stop()

    assert store.get_job(stuck.id).status == "error"
    assert store.get_job(done.id).status == "done"  # terminal rows untouched


# --- JobWorker: one at a time, in order -------------------------------------


def test_worker_runs_jobs_sequentially_in_order(tmp_path, monkeypatch):
    seen = []

    def fake_pipeline(job_id, url, **kwargs):
        seen.append(job_id)

    monkeypatch.setattr(jobs, "run_pipeline", fake_pipeline)
    worker = JobWorker(_store(tmp_path))
    worker.start()
    worker.submit("job-1", "u1")
    worker.submit("job-2", "u2")
    worker._queue.join()  # both drained
    worker.stop()
    assert seen == ["job-1", "job-2"]


def test_submit_resolve_rolls_back_its_own_state_if_the_enqueue_fails(tmp_path):
    # submit_resolve flips the job to `running` before the `put`, so a resume client can
    # connect to a live stream by construction. If the `put` then fails, that flip must
    # be undone here — the route only knows to release the *review*, not what this method
    # did to the *job*. Left as-is the job strands at `running` with a reopened-but-silent
    # channel: GET /api/jobs shows it working forever and the EventSource waits on an
    # event that never comes.
    store = _store(tmp_path)
    job = store.create_job("https://youtu.be/abc")
    store.update_job_status(job.id, "review")  # parked, as a resume finds it
    worker = JobWorker(store)  # not started — drive submit_resolve directly

    def put_boom(item):
        raise RuntimeError("queue is wedged")

    worker._queue.put = put_boom
    with pytest.raises(RuntimeError, match="queue is wedged"):
        worker.submit_resolve(job.id, "rev-1", ResolveRequest("reject"))

    assert store.get_job(job.id).status == "review", (
        "a failed enqueue must restore the prior status, not strand the job at `running`"
    )


# --- routes -----------------------------------------------------------------


class _FakeWorker:
    def __init__(self):
        self.registry = JobRegistry()
        self.bus = EventBus()  # T-013: the /events route reaches the stream through this
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


def test_post_playlist_url_rejected_422(client):
    resp = client.post("/api/jobs", json={"url": "https://youtube.com/playlist?list=PL1"})
    assert resp.status_code == 422
    assert "playlist" in resp.json()["detail"].lower()


def test_post_missing_url_rejected_422(client):
    assert client.post("/api/jobs", json={}).status_code == 422


def test_post_song_url_creates_job_and_submits(client):
    resp = client.post("/api/jobs", json={"url": "https://youtu.be/abc123"})
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]
    # The job is a real durable row, and it was handed to the worker exactly once.
    assert client.store.get_job(job_id) is not None
    assert client.worker.submitted == [(job_id, "https://youtu.be/abc123")]


def test_get_unknown_job_404(client):
    assert client.get("/api/jobs/nope").status_code == 404


def test_get_job_overlays_live_stage(client):
    job = client.store.create_job("https://youtu.be/x")
    client.worker.registry.start(job.id)
    client.worker.registry.set_stage(job.id, "transcode")

    body = client.get(f"/api/jobs/{job.id}").json()
    assert body["job_id"] == job.id
    assert body["url"] == "https://youtu.be/x"
    assert body["status"] == "queued"  # durable row (worker hasn't finished it)
    assert body["stage"] == "transcode"  # live overlay


def test_get_job_overlays_error_and_review(client):
    job = client.store.create_job("u")
    reg = client.worker.registry
    reg.start(job.id)
    reg.finish(job.id, status="error", stage="download", error="yt-dlp died")

    body = client.get(f"/api/jobs/{job.id}").json()
    assert body["stage"] == "download"
    assert body["error"] == "yt-dlp died"


def test_get_review_id_recovered_after_cold_registry(client):
    # Simulate a restart: the durable job + review survive, but the registry is
    # empty. The snapshot must still recover the review id from SQLite.
    job = client.store.create_job("u")
    client.store.update_job_status(job.id, "review")
    review = client.store.create_review(
        job_id=job.id, staging_path="/tmp/x.mp3", query="q",
        candidate_ids=["rec-A"], rec="medium",
    )
    # registry has no entry for this job (cold).
    body = client.get(f"/api/jobs/{job.id}").json()
    assert body["status"] == "review"
    assert body["review_id"] == review.id


# --- the /events route: early-connect replay, headers, 404 ------------------


def test_events_route_replays_everything_emitted_before_connect(client):
    # The T-016 case: the worker emits the whole sequence and closes BEFORE the card
    # opens the stream. Connecting late must replay all of it — nothing lost.
    job = client.store.create_job("https://youtu.be/x")
    bus = client.worker.bus
    bus.publish(job.id, "job.queued", {"job_id": job.id, "url": "https://youtu.be/x"})
    bus.publish(job.id, "track.downloading", {"job_id": job.id})
    bus.publish(job.id, "track.transcoding", {"job_id": job.id})
    bus.publish(job.id, "track.identifying", {"job_id": job.id})
    bus.publish(job.id, "track.done", {"job_id": job.id, "path": "/x.mp3", "tags": {}})
    bus.close(job.id)

    resp = client.get(f"/api/jobs/{job.id}/events")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert resp.headers["cache-control"] == "no-cache"
    assert [name for name, _ in parse_sse(resp.text)] == [
        "job.queued",
        "track.downloading",
        "track.transcoding",
        "track.identifying",
        "track.done",
    ]


def test_events_route_unknown_job_404(client):
    assert client.get("/api/jobs/nope/events").status_code == 404
