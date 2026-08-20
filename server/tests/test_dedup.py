"""T-303 tests — exact-video de-duplication (ADR-027 seam 2, as amended).

All offline. The dedup gate reads one durable store — the `jobs` row's `youtube_video_id`
plus the `landed_path` a landing stamps — and on an exact `status='done'` hit skips the
whole pipeline, adds the owned file to the playlist, and emits `track.skipped`. Never fuzzy;
never the ADR-009 park path; never the single-song R1 path (acceptance item 11).

Layers:
1. **The DAO** — `set_landed_path` / `landed_path_for_video`: the status filter, the
   path-not-null guard, newest-first.
2. **The skip in `run_pipeline`** — a hit skips download and lands `skipped` + `track.skipped`
   + a membership row; a miss / a non-done prior / a different video / a single-song paste all
   process normally.
"""

import asyncio

import pytest

from app.db import Store
from app.config import Settings
from app.events import EventBus
from app.import_seam import Outcome
from app.jobs import JobRegistry, run_pipeline
from app.source_signals import SourceSignals
from test_events import parse_sse  # sibling test module (server/tests on sys.path)


_ABSENT = Settings(jellyfin_url="", jellyfin_api_key="")


def _store(tmp_path):
    store = Store(tmp_path / "jobs.db")
    store.init_schema()
    return store


# --- 1. the DAO -------------------------------------------------------------


class TestLandedPathDAO:
    def test_done_job_with_path_is_found(self, tmp_path):
        store = _store(tmp_path)
        job = store.create_job("u", youtube_video_id="vidA")
        store.update_job_status(job.id, "done")
        store.set_landed_path(job.id, "/lib/A/x.mp3")
        assert store.landed_path_for_video("vidA") == "/lib/A/x.mp3"

    def test_non_done_status_is_not_owned(self, tmp_path):
        # The status='done' filter is load-bearing: a parked/failed never-landed entry
        # must NOT read as owned, or a re-paste skips it forever.
        store = _store(tmp_path)
        for status in ("queued", "running", "review", "error"):
            job = store.create_job("u", youtube_video_id=f"vid-{status}")
            store.update_job_status(job.id, status)
            store.set_landed_path(job.id, "/lib/x.mp3")  # even if a path got stamped
            assert store.landed_path_for_video(f"vid-{status}") is None

    def test_done_but_pathless_is_unlocatable(self, tmp_path):
        # Owned-but-unlocatable (a REPLACE-resolve null-path landing, or a pre-migration
        # row) returns None → the caller re-processes rather than skipping into a dead row.
        store = _store(tmp_path)
        job = store.create_job("u", youtube_video_id="vidA")
        store.update_job_status(job.id, "done")  # no set_landed_path
        assert store.landed_path_for_video("vidA") is None

    def test_unknown_video_is_none(self, tmp_path):
        assert _store(tmp_path).landed_path_for_video("nope") is None

    def test_newest_landing_wins(self, tmp_path):
        # Same video landed twice → the freshest known location is returned.
        store = _store(tmp_path)
        for path in ("/lib/old.mp3", "/lib/new.mp3"):
            job = store.create_job("u", youtube_video_id="vidA")
            store.update_job_status(job.id, "done")
            store.set_landed_path(job.id, path)
        assert store.landed_path_for_video("vidA") == "/lib/new.mp3"


# --- 2. the skip in run_pipeline --------------------------------------------


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


def _run_member(store, job, tmp_path, *, calls, import_fn=None, bus=None):
    """Run one member job through the pipeline with a recording download and absent Jellyfin."""
    return run_pipeline(
        job.id, job.url,
        store=store, registry=JobRegistry(), settings=_ABSENT, staging_root=tmp_path,
        bus=bus or EventBus(),
        download_fn=_recording_download(calls),
        transcode_fn=_fake_transcode,
        import_fn=import_fn or (lambda *a, **k: [
            Outcome("landed", 0.95, 0.5, track_id="rec-A",
                    landed_path="/lib/Band/Song.mp3", tags={"artist": "Band"})
        ]),
        scan_fn=lambda **k: True,
    )


def _own_video(store, video_id, tmp_path, name="Song.mp3"):
    """Simulate a prior landing of `video_id`: a done job carrying its canonical path,
    with the file actually present on disk (the skip existence-checks it)."""
    path = tmp_path / "lib" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"owned-mp3")
    prior = store.create_job("https://youtu.be/prior", youtube_video_id=video_id)
    store.update_job_status(prior.id, "done")
    store.set_landed_path(prior.id, str(path))
    return str(path)


class TestSkip:
    def test_exact_owned_video_skips_pipeline_and_adds_to_playlist(self, tmp_path):
        store = _store(tmp_path)
        path = _own_video(store, "vidX", tmp_path)
        pl = store.upsert_playlist("PL", "P")
        job = store.create_job(
            "https://youtu.be/x", playlist_id=pl.id, position=3, youtube_video_id="vidX",
        )
        calls = []
        bus = EventBus()
        state = _run_member(store, job, tmp_path, calls=calls, bus=bus)

        assert state.status == "skipped"
        assert calls == [], "an owned video must NOT be downloaded"
        # The owned file was added to THIS playlist, carrying its path (pending append).
        (m,) = store.list_members(pl.id)
        assert m.youtube_video_id == "vidX"
        assert m.landed_path == path
        # track.skipped was emitted (and no track.review_required — not the park path).
        names = [name for name, _ in parse_sse(asyncio.run(_drain(bus, job.id)))]
        assert "track.skipped" in names
        assert "track.review_required" not in names
        assert "track.downloading" not in names

    def test_non_done_prior_is_reprocessed_not_skipped(self, tmp_path):
        # A parked/failed prior entry with the same video-ID must be re-processed.
        store = _store(tmp_path)
        prior = store.create_job("u", youtube_video_id="vidX")
        store.update_job_status(prior.id, "error")
        store.set_landed_path(prior.id, "/lib/x.mp3")
        pl = store.upsert_playlist("PL", "P")
        job = store.create_job(
            "https://youtu.be/x", playlist_id=pl.id, position=1, youtube_video_id="vidX",
        )
        calls = []
        state = _run_member(store, job, tmp_path, calls=calls)
        assert state.status == "done"
        assert calls == ["https://youtu.be/x"], "a non-owned video must be downloaded"

    def test_different_video_processes_as_new(self, tmp_path):
        # A genuinely different upload (different id) misses — no fuzzy match attempted.
        store = _store(tmp_path)
        _own_video(store, "vidOwned", tmp_path)
        pl = store.upsert_playlist("PL", "P")
        job = store.create_job(
            "https://youtu.be/y", playlist_id=pl.id, position=1, youtube_video_id="vidOther",
        )
        calls = []
        state = _run_member(store, job, tmp_path, calls=calls)
        assert state.status == "done"
        assert calls == ["https://youtu.be/y"]

    def test_owned_but_pathless_is_reprocessed(self, tmp_path):
        # Owned (done) but no recorded path → re-process, never a skip into a dead row.
        store = _store(tmp_path)
        prior = store.create_job("u", youtube_video_id="vidX")
        store.update_job_status(prior.id, "done")  # no path stamped
        pl = store.upsert_playlist("PL", "P")
        job = store.create_job(
            "https://youtu.be/x", playlist_id=pl.id, position=1, youtube_video_id="vidX",
        )
        calls = []
        state = _run_member(store, job, tmp_path, calls=calls)
        assert state.status == "done"
        assert calls == ["https://youtu.be/x"]

    def test_owned_but_file_gone_is_reprocessed(self, tmp_path):
        # The path is recorded, but the file was deleted or moved by the migrate/clean job.
        # A stale path can never resolve, so the skip must NOT fire — re-acquire instead, or
        # the song is stranded (neither downloaded nor a working playlist entry) under a
        # `skipped` status that reads as success.
        store = _store(tmp_path)
        prior = store.create_job("u", youtube_video_id="vidX")
        store.update_job_status(prior.id, "done")
        store.set_landed_path(prior.id, str(tmp_path / "lib" / "gone.mp3"))  # never written
        pl = store.upsert_playlist("PL", "P")
        job = store.create_job(
            "https://youtu.be/x", playlist_id=pl.id, position=1, youtube_video_id="vidX",
        )
        calls = []
        state = _run_member(store, job, tmp_path, calls=calls)
        assert state.status == "done"
        assert calls == ["https://youtu.be/x"], "a stale-path video must be re-acquired"

    def test_single_song_paste_is_never_skipped(self, tmp_path):
        # R1 non-regression (acceptance item 11): a null-playlist job never enters the
        # dedup gate even when the exact video is already owned — it processes as R1.
        store = _store(tmp_path)
        _own_video(store, "vidX", tmp_path)
        job = store.create_job("https://youtu.be/x", youtube_video_id="vidX")  # playlist_id NULL
        calls = []
        state = _run_member(store, job, tmp_path, calls=calls)
        assert state.status == "done"
        assert calls == ["https://youtu.be/x"]
        with store._connect() as conn:  # noqa: SLF001 — white-box count, offline test
            (count,) = conn.execute("SELECT COUNT(*) FROM playlist_members").fetchone()
        assert count == 0

    def test_re_add_to_same_playlist_does_not_double_add(self, tmp_path):
        # A re-paste of an already-in-THIS-playlist owned video: the membership UNIQUE guard
        # makes the second skip a no-op (ADR-027 seam 4 — membership-check).
        store = _store(tmp_path)
        _own_video(store, "vidX", tmp_path)
        pl = store.upsert_playlist("PL", "P")
        for _ in range(2):
            job = store.create_job(
                "https://youtu.be/x", playlist_id=pl.id, position=1, youtube_video_id="vidX",
            )
            _run_member(store, job, tmp_path, calls=[])
        assert len(store.list_members(pl.id)) == 1


# --- 3. the re-paste composition (T-307) ------------------------------------


def _lands_each_video_to_disk(tmp_path):
    """An `import_fn` that lands every job to its OWN real file under `tmp_path/lib`,
    keyed by the per-job staging directory.

    The default `_run_member` import lands every video to one fixed path that is never
    written to disk — fine for a single skip test, but useless for a re-paste scenario:
    the T-303 skip existence-checks the recorded path, so a first run's tracks are only
    genuinely "owned" on the second run if their canonical files actually exist and differ
    per job. This closes both gaps.
    """
    def import_fn(mp3, *a, **k):
        # The video id is not passed to the import seam, so key the landing on the mp3's
        # PARENT dir name — the per-job mkdtemp staging dir, which IS unique per job. The
        # mp3's own name is `song.mp3` for every job (see `_fake_transcode`) and would
        # collide, so `mp3.parent.name` is load-bearing, not interchangeable with `mp3.name`.
        dest = tmp_path / "lib" / f"{mp3.parent.name}.mp3"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"landed-mp3")
        return [
            Outcome("landed", 0.95, 0.5, track_id=mp3.parent.name,
                    landed_path=str(dest), tags={"artist": "Band"})
        ]

    return import_fn


def _run_gen(store, playlist, entries, tmp_path, *, calls):
    """One expansion generation: create + run a member job per (video_id, url) entry,
    exactly as `_expand_and_enqueue` → the worker does. Returns the run states in order.

    Models a re-paste by being called twice against the SAME `playlist` (the row a re-paste
    reuses via `upsert_playlist`), with a fresh job row per entry each time — the second
    generation the newest-attempt tally and the T-303 skip are built to expect.
    """
    states = []
    import_fn = _lands_each_video_to_disk(tmp_path)
    for position, (video_id, url) in enumerate(entries, start=1):
        job = store.create_job(
            url, playlist_id=playlist.id, position=position, youtube_video_id=video_id,
        )
        states.append(
            _run_member(store, job, tmp_path, calls=calls, import_fn=import_fn)
        )
    return states


class TestRepasteScenario:
    """T-307's `Done when`, composed: run a playlist, then re-paste it grown by one entry.

    The idempotent-re-paste behaviour is not new code — it emerges from the shipped seams
    (playlist-row reuse, the T-303 skip, the membership UNIQUE guard). This proves they
    compose into the acceptance scenario: skips don't re-download, the new entry processes,
    an already-owned entry new to the playlist is added exactly once, nothing double-adds.
    """

    def test_repaste_grown_by_one_skips_landed_and_adds_only_the_new(self, tmp_path):
        store = _store(tmp_path)
        # A song already owned from an EARLIER, unrelated paste — landed, not yet in this
        # playlist. Its file must exist so the re-paste skip can locate and append it.
        owned_elsewhere = _own_video(store, "vidOld", tmp_path, name="Old.mp3")

        pl = store.upsert_playlist("PLsummer", "Summer 2026")

        # --- first paste: two fresh tracks, both land -----------------------
        gen1_calls = []
        gen1 = _run_gen(
            store, pl,
            [("vidA", "https://youtu.be/a"), ("vidB", "https://youtu.be/b")],
            tmp_path, calls=gen1_calls,
        )
        assert [s.status for s in gen1] == ["done", "done"]
        assert gen1_calls == ["https://youtu.be/a", "https://youtu.be/b"]  # both downloaded
        assert {m.youtube_video_id for m in store.list_members(pl.id)} == {"vidA", "vidB"}

        # --- re-paste: same two, plus one genuinely new, plus the owned-elsewhere song ----
        # The playlist row is REUSED (never a second upsert to a new id).
        again = store.upsert_playlist("PLsummer", "Summer 2026")
        assert again.id == pl.id

        gen2_calls = []
        gen2 = _run_gen(
            store, pl,
            [
                ("vidA", "https://youtu.be/a"),      # already landed → skip
                ("vidB", "https://youtu.be/b"),      # already landed → skip
                ("vidOld", "https://youtu.be/old"),  # owned elsewhere, new to THIS list → skip+add
                ("vidC", "https://youtu.be/c"),      # genuinely new → process
            ],
            tmp_path, calls=gen2_calls,
        )
        assert [s.status for s in gen2] == ["skipped", "skipped", "skipped", "done"]
        # Only the genuinely-new entry was downloaded; the three owned ones never hit yt-dlp.
        assert gen2_calls == ["https://youtu.be/c"]

        # Every distinct video is in the playlist exactly once — the owned-elsewhere song is
        # now added (item 11), and no video double-added despite vidA/vidB re-appearing.
        members = store.list_members(pl.id)
        assert sorted(m.youtube_video_id for m in members) == [
            "vidA", "vidB", "vidC", "vidOld",
        ]
        assert len(members) == 4

        # The tally reads THIS grind (newest attempt per position), not both generations:
        # four positions, all terminal, none double-counted.
        counts = store.count_jobs_by_status(pl.id)
        assert counts.get("skipped") == 3 and counts.get("done") == 1
        assert sum(counts.values()) == 4

    def test_repaste_of_an_unchanged_playlist_downloads_nothing(self, tmp_path):
        # The common case — a re-paste with no new entries — is a quiet all-skip: nothing
        # re-downloaded, membership unchanged, no duplicate playlist row.
        store = _store(tmp_path)
        pl = store.upsert_playlist("PLsame", "Same")
        entries = [("vidA", "https://youtu.be/a"), ("vidB", "https://youtu.be/b")]

        _run_gen(store, pl, entries, tmp_path, calls=[])
        assert {m.youtube_video_id for m in store.list_members(pl.id)} == {"vidA", "vidB"}

        repaste_calls = []
        gen2 = _run_gen(store, pl, entries, tmp_path, calls=repaste_calls)
        assert [s.status for s in gen2] == ["skipped", "skipped"]
        assert repaste_calls == []  # nothing re-downloaded
        assert len(store.list_members(pl.id)) == 2  # no double-add


async def _drain(bus, job_id):
    return "".join([frame async for frame in bus.stream(job_id)])
