"""T-304 tests — the Jellyfin playlist output seam (ADR-027 seam 1, as amended).

All offline: the Jellyfin edge is stubbed (a fake `http` for the seam functions, injected
`resolve_fn`/`append_fn` for the reconcile orchestration). The real playlist appearing in a
real Jellyfin is T-311. One class per "Done when" clause:

1. **Seam functions** — `resolve_item_id` finds an item by path (hit/miss/degrade) and
   `append_to_playlist` POSTs the right (playlist, item) or degrades/raises correctly.
2. **Pending-append DAO** — `add_member` persists the `landed_path` handle; the drain
   queue filters and orders correctly; a resolved member leaves the queue; a bounded
   give-up drops a never-indexable one.
3. **Reconcile orchestration** — resolve→append→stamp; a miss defers (no silent drop); an
   uncreated container is skipped without burning the give-up budget; a failed append is
   left pending; the drain is idempotent.
4. **Land-path integration** — a landed member records a pending membership with its path
   (item id NULL); a single-song R1 land records nothing (acceptance item 11).
"""

import sqlite3

import pytest
import requests

from app.config import Settings
from app.db import MAX_APPEND_ATTEMPTS, Store
from app.import_seam import Outcome
from app.jellyfin import (
    JellyfinAppendError,
    append_to_playlist,
    resolve_item_id,
)
from app.jobs import JobRegistry, reconcile_pending_appends, run_pipeline
from app.source_signals import SourceSignals


def _store(tmp_path):
    store = Store(tmp_path / "jobs.db")
    store.init_schema()
    return store


def _cfg(**over):
    """Settings that DON'T read the real .env — jellyfin present unless overridden empty."""
    base = dict(jellyfin_url="http://jf:8096", jellyfin_api_key="key")
    base.update(over)
    return Settings(**base)


_ABSENT = Settings(jellyfin_url="", jellyfin_api_key="")


class _Resp:
    def __init__(self, *, json_body=None, raise_exc=None):
        self._json = json_body
        self._raise = raise_exc

    def raise_for_status(self):
        if self._raise is not None:
            raise self._raise

    def json(self):
        if isinstance(self._json, Exception):
            raise self._json
        return self._json


class _Http:
    """Records the last get/post call and returns a canned response."""

    def __init__(self, *, get_resp=None, post_resp=None):
        self._get_resp = get_resp
        self._post_resp = post_resp
        self.get_call = None
        self.post_call = None

    def get(self, endpoint, **kw):
        self.get_call = (endpoint, kw)
        return self._get_resp

    def post(self, endpoint, **kw):
        self.post_call = (endpoint, kw)
        return self._post_resp


# --- 1. seam functions ------------------------------------------------------


class TestResolveItemId:
    def test_hit_returns_first_item_id(self):
        http = _Http(get_resp=_Resp(json_body={"Items": [{"Id": "item-9"}]}))
        assert resolve_item_id("/lib/A/x.mp3", settings=_cfg(), http=http) == "item-9"
        endpoint, kw = http.get_call
        assert endpoint == "http://jf:8096/Items"
        assert kw["params"]["Path"] == "/lib/A/x.mp3"
        assert kw["headers"]["X-Emby-Token"] == "key"

    def test_miss_empty_items_is_none_not_error(self):
        http = _Http(get_resp=_Resp(json_body={"Items": []}))
        assert resolve_item_id("/lib/A/x.mp3", settings=_cfg(), http=http) is None

    def test_absent_config_degrades_to_none_without_calling(self):
        http = _Http(get_resp=_Resp(json_body={"Items": [{"Id": "no"}]}))
        assert resolve_item_id("/lib/A/x.mp3", settings=_ABSENT, http=http) is None
        assert http.get_call is None  # never touched the network

    def test_request_failure_degrades_to_none(self):
        http = _Http(get_resp=_Resp(raise_exc=requests.RequestException("boom")))
        assert resolve_item_id("/lib/A/x.mp3", settings=_cfg(), http=http) is None


class TestAppendToPlaylist:
    def test_success_posts_the_right_playlist_and_item(self):
        http = _Http(post_resp=_Resp())
        assert append_to_playlist("pl-1", "item-9", settings=_cfg(), http=http) is True
        endpoint, kw = http.post_call
        assert endpoint == "http://jf:8096/Playlists/pl-1/Items"
        assert kw["params"] == {"Ids": "item-9"}

    def test_absent_config_degrades_to_false(self):
        http = _Http(post_resp=_Resp())
        assert append_to_playlist("pl-1", "item-9", settings=_ABSENT, http=http) is False
        assert http.post_call is None

    def test_present_but_failed_post_raises(self):
        http = _Http(post_resp=_Resp(raise_exc=requests.RequestException("503")))
        with pytest.raises(JellyfinAppendError):
            append_to_playlist("pl-1", "item-9", settings=_cfg(), http=http)


# --- 2. pending-append DAO --------------------------------------------------


class TestMigration:
    def test_alter_adds_columns_to_a_shipped_t300_playlist_members(self, tmp_path):
        """The two T-304 columns land on a T-300-era `playlist_members` (no CREATE change).

        The table shipped in T-300 without these columns and is on the owner's live DB, so
        they must arrive via `_ADDED_COLUMNS`'s ALTER — not the `CREATE TABLE IF NOT
        EXISTS`, which no-ops on the existing table. Simulate that DB: create the table in
        its shipped shape, then `init_schema` must ALTER the columns in and `add_member`
        with a `landed_path` must work.
        """
        db_path = tmp_path / "jobs.db"
        conn = sqlite3.connect(db_path)
        conn.executescript(
            "CREATE TABLE jobs (id TEXT PRIMARY KEY, url TEXT, status TEXT, created_at TEXT);"
            "CREATE TABLE playlists (id TEXT PRIMARY KEY, youtube_playlist_id TEXT UNIQUE,"
            " title TEXT, jellyfin_playlist_id TEXT, created_at TEXT);"
            # T-300 shape: NO landed_path, NO append_attempts.
            "CREATE TABLE playlist_members (id TEXT PRIMARY KEY, playlist_id TEXT,"
            " youtube_video_id TEXT, position INTEGER, jellyfin_item_id TEXT, created_at TEXT,"
            " UNIQUE(playlist_id, youtube_video_id));"
        )
        conn.commit()
        conn.close()

        store = Store(db_path)
        store.init_schema()  # must ALTER the two columns in

        cols = {row[1] for row in  # PRAGMA table_info: col 1 is the name
                sqlite3.connect(db_path).execute("PRAGMA table_info(playlist_members)")}
        assert {"landed_path", "append_attempts"} <= cols

        pl = store.upsert_playlist("PL", "P")
        store.add_member(pl.id, "vidA", position=1, landed_path="/lib/a.mp3")
        (m,) = store.list_pending_appends(10)
        assert m.landed_path == "/lib/a.mp3" and m.append_attempts == 0


class TestPendingAppendDAO:
    def test_add_member_persists_landed_path(self, tmp_path):
        store = _store(tmp_path)
        pl = store.upsert_playlist("PL", "P")
        store.add_member(pl.id, "vidA", position=1, landed_path="/lib/A/x.mp3")
        (m,) = store.list_pending_appends(10)
        assert (m.landed_path, m.jellyfin_item_id, m.append_attempts) == (
            "/lib/A/x.mp3", None, 0,
        )

    def test_queue_excludes_resolved_pathless_and_capped(self, tmp_path):
        store = _store(tmp_path)
        pl = store.upsert_playlist("PL", "P")
        # drainable
        store.add_member(pl.id, "vidPending", position=1, landed_path="/lib/p.mp3")
        # already appended → excluded
        store.add_member(pl.id, "vidDone", position=2,
                         jellyfin_item_id="it", landed_path="/lib/d.mp3")
        # no path → unresolvable, excluded (never handed to the drainer)
        store.add_member(pl.id, "vidNoPath", position=3)
        # at the give-up ceiling → excluded
        store.add_member(pl.id, "vidCapped", position=4, landed_path="/lib/c.mp3")
        capped = [m for m in store.list_pending_appends(10)
                  if m.youtube_video_id == "vidCapped"][0]
        for _ in range(MAX_APPEND_ATTEMPTS):
            store.bump_append_attempt(capped.id)

        pending = store.list_pending_appends(10)
        assert [m.youtube_video_id for m in pending] == ["vidPending"]

    def test_queue_is_oldest_first_and_limited(self, tmp_path):
        store = _store(tmp_path)
        pl = store.upsert_playlist("PL", "P")
        for i in range(3):
            store.add_member(pl.id, f"vid{i}", position=i, landed_path=f"/lib/{i}.mp3")
        first_two = store.list_pending_appends(2)
        assert [m.youtube_video_id for m in first_two] == ["vid0", "vid1"]

    def test_mark_appended_removes_from_queue(self, tmp_path):
        store = _store(tmp_path)
        pl = store.upsert_playlist("PL", "P")
        store.add_member(pl.id, "vidA", position=1, landed_path="/lib/a.mp3")
        (m,) = store.list_pending_appends(10)
        store.mark_member_appended(m.id, "item-1")
        assert store.list_pending_appends(10) == []

    def test_bump_returns_running_total(self, tmp_path):
        store = _store(tmp_path)
        pl = store.upsert_playlist("PL", "P")
        store.add_member(pl.id, "vidA", position=1, landed_path="/lib/a.mp3")
        (m,) = store.list_pending_appends(10)
        assert store.bump_append_attempt(m.id) == 1
        assert store.bump_append_attempt(m.id) == 2


# --- 3. reconcile orchestration ---------------------------------------------


def _playlist_with_pending(tmp_path, *, jellyfin_playlist_id="jf-pl"):
    store = _store(tmp_path)
    pl = store.upsert_playlist("PL", "P")
    if jellyfin_playlist_id is not None:
        store.set_jellyfin_playlist_id(pl.id, jellyfin_playlist_id)
    store.add_member(pl.id, "vidA", position=1, landed_path="/lib/A/x.mp3")
    return store, pl


class TestReconcile:
    def test_hit_appends_with_stored_jellyfin_playlist_id_and_stamps(self, tmp_path):
        store, _ = _playlist_with_pending(tmp_path)
        appends = []
        n = reconcile_pending_appends(
            store, limit=10,
            resolve_fn=lambda path, settings=None: "item-42",
            append_fn=lambda pl_id, item_id, settings=None: (
                appends.append((pl_id, item_id)) or True
            ),
        )
        assert n == 1
        assert appends == [("jf-pl", "item-42")]  # the id T-302 stored
        assert store.list_pending_appends(10) == []  # stamped → drained

    def test_miss_defers_without_dropping(self, tmp_path):
        store, _ = _playlist_with_pending(tmp_path)
        n = reconcile_pending_appends(
            store, limit=10,
            resolve_fn=lambda path, settings=None: None,  # not indexed yet
            append_fn=lambda *a, **k: pytest.fail("must not append on a miss"),
        )
        assert n == 0
        (m,) = store.list_pending_appends(10)
        assert m.append_attempts == 1  # counted, still pending — no silent drop

    def test_uncreated_container_is_skipped_without_burning_attempts(self, tmp_path):
        store, _ = _playlist_with_pending(tmp_path, jellyfin_playlist_id=None)
        n = reconcile_pending_appends(
            store, limit=10,
            resolve_fn=lambda *a, **k: pytest.fail("must not resolve a container-less row"),
            append_fn=lambda *a, **k: pytest.fail("must not append"),
        )
        assert n == 0
        (m,) = store.list_pending_appends(10)
        assert m.append_attempts == 0  # the container's fault, not the member's (T-306)

    def test_failed_append_leaves_it_pending(self, tmp_path):
        store, _ = _playlist_with_pending(tmp_path)

        def boom(pl_id, item_id, settings=None):
            raise JellyfinAppendError("503")

        n = reconcile_pending_appends(
            store, limit=10,
            resolve_fn=lambda path, settings=None: "item-42",
            append_fn=boom,
        )
        assert n == 0
        (m,) = store.list_pending_appends(10)
        assert m.jellyfin_item_id is None and m.append_attempts == 1

    def test_degraded_append_is_not_stamped_as_done(self, tmp_path):
        """append_fn returning False (degraded) must leave the member pending, not stamped."""
        store, _ = _playlist_with_pending(tmp_path)
        n = reconcile_pending_appends(
            store, limit=10,
            resolve_fn=lambda path, settings=None: "item-42",
            append_fn=lambda pl_id, item_id, settings=None: False,  # degraded no-op
        )
        assert n == 0
        (m,) = store.list_pending_appends(10)
        assert m.jellyfin_item_id is None and m.append_attempts == 1  # pending, counted

    def test_one_bad_member_does_not_abort_the_pass(self, tmp_path):
        """A store error on one member is isolated — the others still drain (never-raises)."""
        store = _store(tmp_path)
        pl = store.upsert_playlist("PL", "P")
        store.set_jellyfin_playlist_id(pl.id, "jf-pl")
        store.add_member(pl.id, "vidA", position=1, landed_path="/lib/a.mp3")
        store.add_member(pl.id, "vidB", position=2, landed_path="/lib/b.mp3")
        appended = []

        def resolve(path, settings=None):
            # vidA's path resolves fine; simulate a transient blow-up only for vidA's append
            return "item-A" if path == "/lib/a.mp3" else "item-B"

        def append(pl_id, item_id, settings=None):
            if item_id == "item-A":
                raise RuntimeError("unexpected store/edge blow-up")
            appended.append(item_id)
            return True

        n = reconcile_pending_appends(store, limit=10, resolve_fn=resolve, append_fn=append)
        assert n == 1 and appended == ["item-B"]  # vidB drained despite vidA blowing up

    def test_drain_is_idempotent_across_passes(self, tmp_path):
        store, _ = _playlist_with_pending(tmp_path)
        calls = []
        kw = dict(
            resolve_fn=lambda path, settings=None: "item-42",
            append_fn=lambda pl_id, item_id, settings=None: calls.append(item_id) or True,
        )
        reconcile_pending_appends(store, limit=10, **kw)
        reconcile_pending_appends(store, limit=10, **kw)  # second pass: nothing pending
        assert calls == ["item-42"]  # appended exactly once


# --- 4. land-path integration -----------------------------------------------


def _fake_download(url, staging_dir):
    path = staging_dir / "song.webm"
    path.write_bytes(b"audio")
    return path, SourceSignals.from_info({"id": "vid", "title": "Song"})


def _fake_transcode(source):
    mp3 = source.with_suffix(".mp3")
    mp3.write_bytes(b"mp3")
    return mp3


def _land_pipeline(store, job, tmp_path):
    """Run one landing pipeline for `job` with a stubbed Jellyfin (absent → no network)."""
    return run_pipeline(
        job.id, job.url,
        store=store, registry=JobRegistry(), settings=_ABSENT, staging_root=tmp_path,
        download_fn=_fake_download, transcode_fn=_fake_transcode,
        import_fn=lambda *a, **k: [
            Outcome("landed", 0.95, 0.5, track_id="rec-A",
                    landed_path="/lib/Band/Song.mp3", tags={"artist": "Band"})
        ],
        scan_fn=lambda **k: True,
    )


class TestLandPathIntegration:
    def test_member_land_records_a_pending_membership_with_its_path(self, tmp_path):
        store = _store(tmp_path)
        pl = store.upsert_playlist("PL", "P")
        job = store.create_job(
            "https://youtu.be/x", playlist_id=pl.id, position=1, youtube_video_id="vidX",
        )
        state = _land_pipeline(store, job, tmp_path)
        assert state.status == "done"

        (m,) = store.list_members(pl.id)
        assert m.youtube_video_id == "vidX"
        assert m.landed_path == "/lib/Band/Song.mp3"
        assert m.jellyfin_item_id is None  # pending — the reconcile pass owns it

    def test_member_land_with_no_path_records_no_unresolvable_row(self, tmp_path):
        """A pathless member landing must NOT write a dead-letter pending row (silent loss)."""
        store = _store(tmp_path)
        pl = store.upsert_playlist("PL", "P")
        job = store.create_job(
            "https://youtu.be/x", playlist_id=pl.id, position=1, youtube_video_id="vidX",
        )
        state = run_pipeline(
            job.id, job.url,
            store=store, registry=JobRegistry(), settings=_ABSENT, staging_root=tmp_path,
            download_fn=_fake_download, transcode_fn=_fake_transcode,
            import_fn=lambda *a, **k: [  # landed, but with no canonical path
                Outcome("landed", 0.95, 0.5, track_id="rec-A", landed_path=None)
            ],
            scan_fn=lambda **k: True,
        )
        assert state.status == "done"  # the track still landed
        assert store.list_members(pl.id) == []  # but no undrainable membership row

    def test_single_song_land_records_no_membership(self, tmp_path):
        """R1 non-regression (acceptance item 11): a null-playlist job touches no membership."""
        store = _store(tmp_path)
        job = store.create_job("https://youtu.be/solo")  # playlist_id defaults to NULL
        state = _land_pipeline(store, job, tmp_path)
        assert state.status == "done"
        # No playlist exists, and nothing was written to the membership store.
        with store._connect() as conn:  # noqa: SLF001 — white-box count, offline test
            (count,) = conn.execute("SELECT COUNT(*) FROM playlist_members").fetchone()
        assert count == 0
