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

import acoustid
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.jobs as jobs
from app.db import Store
from app.import_seam import Outcome
from app.jellyfin import JellyfinScanError
from app.jobs import JobRegistry, JobWorker, run_pipeline


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


# --- routes -----------------------------------------------------------------


class _FakeWorker:
    def __init__(self):
        self.registry = JobRegistry()
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
