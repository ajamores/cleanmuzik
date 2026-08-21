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
   uncreated container is created-if-missing (T-306) then drained, or deferred if the create
   still fails; a failed append is left pending; the drain is idempotent.
4. **Land-path integration** — a landed member records a pending membership with its path
   (item id NULL); a single-song R1 land records nothing (acceptance item 11).
"""

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
import requests

from app.config import Settings
from app.db import Store
from app.import_seam import Outcome
from app.jellyfin import (
    JellyfinAppendError,
    PlaylistProbe,
    PlaylistProbeStatus,
    ResolveResult,
    ResolveStatus,
    append_to_playlist,
    get_playlist_item_ids,
    resolve_item_id,
    resolve_user_id,
)
from app.jobs import JobRegistry, reconcile_pending_appends, run_pipeline
from app.source_signals import SourceSignals


def _resolved(item_id):
    """A resolve_fn that always RESOLVES to `item_id` (T-313 3-state test helper)."""
    return lambda path, settings=None: ResolveResult(ResolveStatus.RESOLVED, item_id)


def _resolve_status(status):
    """A resolve_fn that always returns `status` with no item id (NOT_INDEXED / UNREACHABLE)."""
    return lambda path, settings=None: ResolveResult(status)


def _readable(*item_ids):
    """A precheck_fn for a reachable playlist holding `item_ids` (empty = the common case)."""
    return lambda pl_id, settings=None: PlaylistProbe(
        PlaylistProbeStatus.READABLE, set(item_ids)
    )


_empty_precheck = _readable()  # reachable, currently-empty playlist — the common case


def _probe_status(status):
    """A precheck_fn that always returns `status` (ABSENT / UNREADABLE) with no member set."""
    return lambda pl_id, settings=None: PlaylistProbe(status)


def _http_error(status_code):
    """A `requests.HTTPError` carrying a response with `status_code` (for a 404 pre-check)."""
    resp = requests.Response()
    resp.status_code = status_code
    return requests.HTTPError(f"{status_code}", response=resp)


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


# A single admin user, served for GET /Users so playlist ops resolve a user id (T-311).
_ADMIN_USERS = [{"Id": "user-1", "Policy": {"IsAdministrator": True}}]


class _Http:
    """Records the last get/post call and returns a canned response.

    GET /Users (the T-311 user-id lookup, made internally by append/pre-check) is routed
    separately: by default it serves one admin user, so those ops can resolve `user-1`; pass
    `users_resp` to simulate a lookup failure. The operation's own GET/POST is recorded in
    `get_call`/`post_call` as before.
    """

    def __init__(self, *, get_resp=None, post_resp=None, users_resp="default"):
        self._get_resp = get_resp
        self._post_resp = post_resp
        self._users_resp = (
            _Resp(json_body=_ADMIN_USERS) if users_resp == "default" else users_resp
        )
        self.get_call = None
        self.post_call = None
        self.users_call = None

    def get(self, endpoint, **kw):
        if "/Users" in endpoint:
            self.users_call = (endpoint, kw)
            return self._users_resp
        self.get_call = (endpoint, kw)
        return self._get_resp

    def post(self, endpoint, **kw):
        self.post_call = (endpoint, kw)
        return self._post_resp


# --- 1. seam functions ------------------------------------------------------


class TestResolveItemId:
    """The 3-state resolve (T-313, repair 2). Every current `None` path maps to exactly one
    of RESOLVED / NOT_INDEXED / UNREACHABLE — the split that lets the reconcile pass tell
    'wait for the index' from 'Jellyfin is down' and stops an outage stranding healthy rows."""

    def test_exact_path_match_returns_resolved(self):
        # The live server ignores Path=, so we list audio items and match Path ourselves.
        http = _Http(get_resp=_Resp(json_body={"Items": [
            {"Id": "other", "Path": "/lib/A/y.mp3"},
            {"Id": "item-9", "Path": "/lib/A/x.mp3"},
        ]}))
        result = resolve_item_id("/lib/A/x.mp3", settings=_cfg(), http=http)
        assert result == ResolveResult(ResolveStatus.RESOLVED, "item-9")
        endpoint, kw = http.get_call
        assert endpoint == "http://jf:8096/Items"
        assert kw["params"]["IncludeItemTypes"] == "Audio"
        assert "Path" not in kw["params"]  # no longer relies on the ignored server-side filter
        assert kw["headers"]["X-Emby-Token"] == "key"

    def test_wsl_landed_path_matches_windows_jellyfin_path(self, monkeypatch):
        # T-316 live finding: the pipeline lands POSIX paths under LIBRARY_DIRECTORY
        # (/mnt/c/…, '/') but Jellyfin (Windows host) reports the same file as C:\…, '\'.
        # A raw `==` never matched → every landed track NOT_INDEXED forever. The bridge
        # matches on the library-relative tail across both format gaps.
        import app.beets_engine as beets_engine

        monkeypatch.setattr(
            beets_engine, "LIBRARY_DIRECTORY", "/mnt/c/Users/aj/Music/CleanMuzik"
        )
        http = _Http(get_resp=_Resp(json_body={"Items": [
            {"Id": "root", "Path": r"C:\Users\aj\Music\CleanMuzik"},
            {"Id": "hit", "Path": r"C:\Users\aj\Music\CleanMuzik\Nas\Illmatic\N.Y. State of Mind.mp3"},
        ]}))
        landed = "/mnt/c/Users/aj/Music/CleanMuzik/Nas/Illmatic/N.Y. State of Mind.mp3"
        result = resolve_item_id(landed, settings=_cfg(), http=http)
        assert result == ResolveResult(ResolveStatus.RESOLVED, "hit")

    def test_bridge_does_not_match_a_different_file_with_a_shorter_tail(self, monkeypatch):
        # The tail match is anchored on a separator + the FULL library-relative path, so a
        # same-titled track under a different album must not be a false positive.
        import app.beets_engine as beets_engine

        monkeypatch.setattr(
            beets_engine, "LIBRARY_DIRECTORY", "/mnt/c/Users/aj/Music/CleanMuzik"
        )
        http = _Http(get_resp=_Resp(json_body={"Items": [
            {"Id": "wrong", "Path": r"C:\Users\aj\Music\CleanMuzik\Nas\Other\N.Y. State of Mind.mp3"},
        ]}))
        landed = "/mnt/c/Users/aj/Music/CleanMuzik/Nas/Illmatic/N.Y. State of Mind.mp3"
        result = resolve_item_id(landed, settings=_cfg(), http=http)
        assert result.status is ResolveStatus.NOT_INDEXED

    def test_bridge_does_not_cross_match_another_library_with_the_same_tail(self, monkeypatch):
        # /Items is unscoped across every Jellyfin library, so a same Artist/Album/Title tail
        # under a DIFFERENT library folder (e.g. this verify run's temp library beside the real
        # one) must not resolve — the anchor includes the library folder name (T-316 review F1).
        import app.beets_engine as beets_engine

        monkeypatch.setattr(
            beets_engine, "LIBRARY_DIRECTORY", "/mnt/c/Users/aj/Music/CleanMuzik"
        )
        http = _Http(get_resp=_Resp(json_body={"Items": [
            {"Id": "otherlib", "Path": r"C:\Users\aj\Music\OtherLibrary\Nas\Illmatic\N.Y. State of Mind.mp3"},
        ]}))
        landed = "/mnt/c/Users/aj/Music/CleanMuzik/Nas/Illmatic/N.Y. State of Mind.mp3"
        result = resolve_item_id(landed, settings=_cfg(), http=http)
        assert result.status is ResolveStatus.NOT_INDEXED

    def test_bridge_is_case_insensitive_across_the_ntfs_boundary(self, monkeypatch):
        # The bridged boundary is a case-insensitive NTFS mount; a component whose case differs
        # between beets' path and Jellyfin's report must still match (T-316 review F2).
        import app.beets_engine as beets_engine

        monkeypatch.setattr(
            beets_engine, "LIBRARY_DIRECTORY", "/mnt/c/Users/aj/Music/CleanMuzik"
        )
        http = _Http(get_resp=_Resp(json_body={"Items": [
            {"Id": "hit", "Path": r"C:\Users\aj\Music\CleanMuzik\NAS\illmatic\N.Y. State of Mind.mp3"},
        ]}))
        landed = "/mnt/c/Users/aj/Music/CleanMuzik/Nas/Illmatic/N.Y. State of Mind.mp3"
        result = resolve_item_id(landed, settings=_cfg(), http=http)
        assert result == ResolveResult(ResolveStatus.RESOLVED, "hit")

    def test_no_matching_path_is_not_indexed(self):
        http = _Http(get_resp=_Resp(json_body={"Items": [{"Id": "z", "Path": "/lib/A/other.mp3"}]}))
        result = resolve_item_id("/lib/A/x.mp3", settings=_cfg(), http=http)
        assert result.status is ResolveStatus.NOT_INDEXED and result.item_id is None

    def test_empty_items_is_not_indexed(self):
        http = _Http(get_resp=_Resp(json_body={"Items": []}))
        result = resolve_item_id("/lib/A/x.mp3", settings=_cfg(), http=http)
        assert result.status is ResolveStatus.NOT_INDEXED

    def test_absent_config_is_not_indexed_without_calling(self):
        http = _Http(get_resp=_Resp(json_body={"Items": [{"Id": "no", "Path": "/lib/A/x.mp3"}]}))
        result = resolve_item_id("/lib/A/x.mp3", settings=_ABSENT, http=http)
        assert result.status is ResolveStatus.NOT_INDEXED
        assert http.get_call is None  # never touched the network

    def test_request_failure_is_unreachable(self):
        http = _Http(get_resp=_Resp(raise_exc=requests.RequestException("boom")))
        result = resolve_item_id("/lib/A/x.mp3", settings=_cfg(), http=http)
        assert result.status is ResolveStatus.UNREACHABLE

    def test_non_json_body_is_unreachable(self):
        http = _Http(get_resp=_Resp(json_body=ValueError("not json")))
        result = resolve_item_id("/lib/A/x.mp3", settings=_cfg(), http=http)
        assert result.status is ResolveStatus.UNREACHABLE

    def test_non_dict_body_is_unreachable(self):
        http = _Http(get_resp=_Resp(json_body=["not", "a", "dict"]))
        result = resolve_item_id("/lib/A/x.mp3", settings=_cfg(), http=http)
        assert result.status is ResolveStatus.UNREACHABLE

    def test_items_not_a_list_is_unreachable(self):
        http = _Http(get_resp=_Resp(json_body={"Items": "nope"}))
        result = resolve_item_id("/lib/A/x.mp3", settings=_cfg(), http=http)
        assert result.status is ResolveStatus.UNREACHABLE

    def test_matched_but_idless_is_unreachable_never_resolved_none(self):
        """The load-bearing case: a path match whose Id is missing must NOT become
        RESOLVED(None) (that would POST Ids=None → 400 → re-enter the retry burn, bug 3)."""
        http = _Http(get_resp=_Resp(json_body={"Items": [{"Path": "/lib/A/x.mp3"}]}))
        result = resolve_item_id("/lib/A/x.mp3", settings=_cfg(), http=http)
        assert result.status is ResolveStatus.UNREACHABLE

    def test_matched_but_empty_string_id_is_unreachable(self):
        http = _Http(get_resp=_Resp(json_body={"Items": [{"Id": "", "Path": "/lib/A/x.mp3"}]}))
        result = resolve_item_id("/lib/A/x.mp3", settings=_cfg(), http=http)
        assert result.status is ResolveStatus.UNREACHABLE

    def test_resolved_none_is_unconstructible(self):
        """The invariant behind the whole repair — enforced at construction."""
        with pytest.raises(ValueError):
            ResolveResult(ResolveStatus.RESOLVED, None)
        with pytest.raises(ValueError):
            ResolveResult(ResolveStatus.NOT_INDEXED, "leaked-id")


class TestGetPlaylistItemIds:
    """The 3-state pre-check GET (T-313 repair 3; T-315 un-collapses its `None`). Every current
    failure maps to exactly one of READABLE / ABSENT / UNREADABLE — the split that lets the
    reconcile pass tell 'deleted, re-create it' from 'unreachable, defer untouched'."""

    def test_returns_the_set_of_library_item_ids(self):
        http = _Http(get_resp=_Resp(json_body={"Items": [{"Id": "a"}, {"Id": "b"}]}))
        got = get_playlist_item_ids("pl-1", settings=_cfg(), http=http)
        assert got == PlaylistProbe(PlaylistProbeStatus.READABLE, {"a", "b"})
        endpoint, kw = http.get_call
        assert endpoint == "http://jf:8096/Playlists/pl-1/Items"
        assert kw["params"] == {"userId": "user-1"}  # T-311: the read is user-scoped

    def test_empty_playlist_is_readable_empty_not_a_failure(self):
        """A valid answer distinct from failure — an empty playlist means 'append freely'."""
        http = _Http(get_resp=_Resp(json_body={"Items": []}))
        got = get_playlist_item_ids("pl-1", settings=_cfg(), http=http)
        assert got.status is PlaylistProbeStatus.READABLE and got.items == set()

    def test_deleted_playlist_404_is_absent(self):
        """T-315: a 404 is a positive 'this playlist is gone' — distinct from unreachable, so
        the reconcile pass may safely re-create it."""
        http = _Http(get_resp=_Resp(raise_exc=_http_error(404)))
        got = get_playlist_item_ids("pl-1", settings=_cfg(), http=http)
        assert got.status is PlaylistProbeStatus.ABSENT and got.items is None

    def test_non_404_http_error_is_unreadable_not_absent(self):
        """A 500 (or 401) is an outage/auth failure, NOT a deletion — must NOT trigger a
        re-create (that would orphan a still-live playlist)."""
        http = _Http(get_resp=_Resp(raise_exc=_http_error(500)))
        assert get_playlist_item_ids("pl-1", settings=_cfg(), http=http).status is (
            PlaylistProbeStatus.UNREADABLE
        )

    def test_absent_config_is_unreadable(self):
        http = _Http(get_resp=_Resp(json_body={"Items": []}))
        assert get_playlist_item_ids("pl-1", settings=_ABSENT, http=http).status is (
            PlaylistProbeStatus.UNREADABLE
        )
        assert http.get_call is None

    def test_unresolvable_user_id_is_unreadable(self):
        """No user id → can't scope the read → UNREADABLE → reconcile defers (never blind-append)."""
        http = _Http(get_resp=_Resp(json_body={"Items": []}), users_resp=_Resp(json_body=[]))
        assert get_playlist_item_ids("pl-1", settings=_cfg(), http=http).status is (
            PlaylistProbeStatus.UNREADABLE
        )
        assert http.get_call is None  # never reached the playlist read

    def test_request_failure_is_unreadable(self):
        http = _Http(get_resp=_Resp(raise_exc=requests.RequestException("boom")))
        assert get_playlist_item_ids("pl-1", settings=_cfg(), http=http).status is (
            PlaylistProbeStatus.UNREADABLE
        )

    def test_non_dict_body_is_unreadable(self):
        http = _Http(get_resp=_Resp(json_body=["nope"]))
        assert get_playlist_item_ids("pl-1", settings=_cfg(), http=http).status is (
            PlaylistProbeStatus.UNREADABLE
        )

    def test_malformed_items_entries_are_skipped(self):
        http = _Http(get_resp=_Resp(
            json_body={"Items": [{"Id": "a"}, {"Name": "no id"}, "junk", {"Id": ""}]}
        ))
        got = get_playlist_item_ids("pl-1", settings=_cfg(), http=http)
        assert got.status is PlaylistProbeStatus.READABLE and got.items == {"a"}

    def test_probe_invariant_rejects_a_non_readable_with_items(self):
        """The load-bearing invariant: an ABSENT/UNREADABLE probe can't smuggle a member set."""
        with pytest.raises(ValueError):
            PlaylistProbe(PlaylistProbeStatus.ABSENT, set())
        with pytest.raises(ValueError):
            PlaylistProbe(PlaylistProbeStatus.READABLE, None)


class _UsersHttp:
    """Serves GET /Users a canned response and counts how many times it was called."""

    def __init__(self, resp):
        self._resp = resp
        self.calls = 0

    def get(self, endpoint, **kw):
        assert "/Users" in endpoint
        self.calls += 1
        return self._resp


class TestResolveUserId:
    """The auto-discovered Jellyfin user id every playlist op is scoped to (T-311)."""

    def test_prefers_an_admin_user(self):
        http = _UsersHttp(_Resp(json_body=[
            {"Id": "viewer", "Policy": {"IsAdministrator": False}},
            {"Id": "boss", "Policy": {"IsAdministrator": True}},
        ]))
        assert resolve_user_id(settings=_cfg(), http=http) == "boss"

    def test_falls_back_to_first_user_when_no_admin(self):
        http = _UsersHttp(_Resp(json_body=[{"Id": "only", "Policy": {}}]))
        assert resolve_user_id(settings=_cfg(), http=http) == "only"

    def test_absent_config_is_none_without_calling(self):
        http = _UsersHttp(_Resp(json_body=[{"Id": "x"}]))
        assert resolve_user_id(settings=_ABSENT, http=http) is None
        assert http.calls == 0

    def test_request_failure_is_none(self):
        http = _UsersHttp(_Resp(raise_exc=requests.RequestException("boom")))
        assert resolve_user_id(settings=_cfg(), http=http) is None

    def test_empty_user_list_is_none(self):
        assert resolve_user_id(settings=_cfg(), http=_UsersHttp(_Resp(json_body=[]))) is None

    def test_result_is_cached_per_url_key(self):
        http = _UsersHttp(_Resp(json_body=[{"Id": "boss", "Policy": {"IsAdministrator": True}}]))
        assert resolve_user_id(settings=_cfg(), http=http) == "boss"
        assert resolve_user_id(settings=_cfg(), http=http) == "boss"
        assert http.calls == 1  # second call served from cache, no re-hit of /Users


class TestAppendToPlaylist:
    def test_success_posts_the_right_playlist_item_and_user(self):
        http = _Http(post_resp=_Resp())
        assert append_to_playlist("pl-1", "item-9", settings=_cfg(), http=http) is True
        endpoint, kw = http.post_call
        assert endpoint == "http://jf:8096/Playlists/pl-1/Items"
        assert kw["params"] == {"Ids": "item-9", "userId": "user-1"}  # T-311: scoped to a user

    def test_absent_config_degrades_to_false(self):
        http = _Http(post_resp=_Resp())
        assert append_to_playlist("pl-1", "item-9", settings=_ABSENT, http=http) is False
        assert http.post_call is None

    def test_present_but_failed_post_raises(self):
        http = _Http(post_resp=_Resp(raise_exc=requests.RequestException("503")))
        with pytest.raises(JellyfinAppendError):
            append_to_playlist("pl-1", "item-9", settings=_cfg(), http=http)

    def test_unresolvable_user_id_raises_so_reconcile_retries(self):
        """Config present but /Users can't resolve a user → present-but-broken Jellyfin, so
        raise (reconcile leaves it pending, no penalty), not a silent False that looks absent."""
        http = _Http(post_resp=_Resp(), users_resp=_Resp(json_body=[]))
        with pytest.raises(JellyfinAppendError):
            append_to_playlist("pl-1", "item-9", settings=_cfg(), http=http)
        assert http.post_call is None  # never reached the append POST


# --- 2. pending-append DAO --------------------------------------------------


class TestMigration:
    def test_alter_adds_t313_columns_to_a_shipped_t300_playlist_members(self, tmp_path):
        """`landed_path` (T-304) + `stuck_since` (T-313) land on a T-300-era table via ALTER.

        The table shipped in T-300 without these columns and is on the owner's live DB, so
        they must arrive via `_ADDED_COLUMNS`'s ALTER — not the `CREATE TABLE IF NOT EXISTS`,
        which no-ops on the existing table. `append_attempts` is NOT added — it was retired by
        T-313 and only survives as a dead column on DBs that already had it (below).
        """
        db_path = tmp_path / "jobs.db"
        conn = sqlite3.connect(db_path)
        conn.executescript(
            "CREATE TABLE jobs (id TEXT PRIMARY KEY, url TEXT, status TEXT, created_at TEXT);"
            "CREATE TABLE playlists (id TEXT PRIMARY KEY, youtube_playlist_id TEXT UNIQUE,"
            " title TEXT, jellyfin_playlist_id TEXT, created_at TEXT);"
            # T-300 shape: NO landed_path, NO append_attempts, NO stuck_since.
            "CREATE TABLE playlist_members (id TEXT PRIMARY KEY, playlist_id TEXT,"
            " youtube_video_id TEXT, position INTEGER, jellyfin_item_id TEXT, created_at TEXT,"
            " UNIQUE(playlist_id, youtube_video_id));"
        )
        conn.commit()
        conn.close()

        store = Store(db_path)
        store.init_schema()  # must ALTER landed_path + stuck_since in

        cols = {row[1] for row in  # PRAGMA table_info: col 1 is the name
                sqlite3.connect(db_path).execute("PRAGMA table_info(playlist_members)")}
        assert {"landed_path", "stuck_since"} <= cols
        assert "append_attempts" not in cols  # retired — never added on a fresh/T-300 DB

        pl = store.upsert_playlist("PL", "P")
        store.add_member(pl.id, "vidA", position=1, landed_path="/lib/a.mp3")
        (m,) = store.list_pending_appends(10)
        assert m.landed_path == "/lib/a.mp3" and m.stuck_since is None

    def test_migration_leaves_a_pre_t313_append_attempts_column_as_a_dead_column(self, tmp_path):
        """A T-304-era DB (already has append_attempts) keeps it — no DROP — and gains
        stuck_since. The old column is simply never read again."""
        db_path = tmp_path / "jobs.db"
        conn = sqlite3.connect(db_path)
        conn.executescript(
            "CREATE TABLE jobs (id TEXT PRIMARY KEY, url TEXT, status TEXT, created_at TEXT);"
            "CREATE TABLE playlists (id TEXT PRIMARY KEY, youtube_playlist_id TEXT UNIQUE,"
            " title TEXT, jellyfin_playlist_id TEXT, created_at TEXT);"
            # T-304 shape: HAS landed_path + append_attempts, NO stuck_since.
            "CREATE TABLE playlist_members (id TEXT PRIMARY KEY, playlist_id TEXT,"
            " youtube_video_id TEXT, position INTEGER, jellyfin_item_id TEXT, created_at TEXT,"
            " landed_path TEXT, append_attempts INTEGER NOT NULL DEFAULT 0,"
            " UNIQUE(playlist_id, youtube_video_id));"
        )
        conn.commit()
        conn.close()

        store = Store(db_path)
        store.init_schema()  # must ALTER stuck_since in, leave append_attempts alone

        cols = {row[1] for row in
                sqlite3.connect(db_path).execute("PRAGMA table_info(playlist_members)")}
        assert "stuck_since" in cols
        assert "append_attempts" in cols  # dead, not dropped — a rebuild would be needless risk


class TestPendingAppendDAO:
    def test_add_member_persists_landed_path(self, tmp_path):
        store = _store(tmp_path)
        pl = store.upsert_playlist("PL", "P")
        store.add_member(pl.id, "vidA", position=1, landed_path="/lib/A/x.mp3")
        (m,) = store.list_pending_appends(10)
        assert (m.landed_path, m.jellyfin_item_id, m.stuck_since) == (
            "/lib/A/x.mp3", None, None,
        )

    def test_queue_excludes_resolved_and_pathless_only(self, tmp_path):
        """Drainable = pending + has a path. No give-up ceiling any more (T-313)."""
        store = _store(tmp_path)
        pl = store.upsert_playlist("PL", "P")
        store.add_member(pl.id, "vidPending", position=1, landed_path="/lib/p.mp3")
        # already appended → excluded
        store.add_member(pl.id, "vidDone", position=2,
                         jellyfin_item_id="it", landed_path="/lib/d.mp3")
        # no path → unresolvable, excluded (never handed to the drainer)
        store.add_member(pl.id, "vidNoPath", position=3)

        pending = store.list_pending_appends(10)
        assert [m.youtube_video_id for m in pending] == ["vidPending"]

    def test_a_stuck_row_is_still_drainable(self, tmp_path):
        """'Stuck' is visibility, not benching — the row stays in the pending set (bug 1/3)."""
        store = _store(tmp_path)
        pl = store.upsert_playlist("PL", "P")
        store.add_member(pl.id, "vidStuck", position=1, landed_path="/lib/s.mp3")
        (m,) = store.list_pending_appends(10)
        store.mark_member_stuck(m.id)
        still = store.list_pending_appends(10)
        assert [x.youtube_video_id for x in still] == ["vidStuck"]
        assert still[0].stuck_since is not None

    def test_legacy_capped_row_resurrects_when_the_filter_is_gone(self, tmp_path):
        """Bug-1 backfill regression: a row the OLD cap benched (append_attempts high) must
        re-enter the pending set now the counter filter is deleted — it was an outage victim,
        not a genuine give-up. Simulated on a DB that carries the dead append_attempts column."""
        db_path = tmp_path / "jobs.db"
        conn = sqlite3.connect(db_path)
        conn.executescript(
            "CREATE TABLE jobs (id TEXT PRIMARY KEY, url TEXT, status TEXT, created_at TEXT);"
            "CREATE TABLE playlists (id TEXT PRIMARY KEY, youtube_playlist_id TEXT UNIQUE,"
            " title TEXT, jellyfin_playlist_id TEXT, created_at TEXT);"
            "CREATE TABLE playlist_members (id TEXT PRIMARY KEY, playlist_id TEXT,"
            " youtube_video_id TEXT, position INTEGER, jellyfin_item_id TEXT, created_at TEXT,"
            " landed_path TEXT, append_attempts INTEGER NOT NULL DEFAULT 0,"
            " UNIQUE(playlist_id, youtube_video_id));"
        )
        conn.execute(
            "INSERT INTO playlists (id, youtube_playlist_id, title, created_at) "
            "VALUES ('pl', 'PL', 'P', '2026-01-01T00:00:00+00:00')"
        )
        conn.execute(
            "INSERT INTO playlist_members "
            "(id, playlist_id, youtube_video_id, position, jellyfin_item_id, created_at,"
            " landed_path, append_attempts) "
            "VALUES ('m', 'pl', 'vidBenched', 1, NULL, '2026-01-01T00:00:00+00:00',"
            " '/lib/benched.mp3', 999)"
        )
        conn.commit()
        conn.close()

        store = Store(db_path)
        store.init_schema()
        pending = store.list_pending_appends(10)
        assert [m.youtube_video_id for m in pending] == ["vidBenched"]  # resurrected

    def test_queue_is_oldest_first_and_limited(self, tmp_path):
        store = _store(tmp_path)
        pl = store.upsert_playlist("PL", "P")
        for i in range(3):
            store.add_member(pl.id, f"vid{i}", position=i, landed_path=f"/lib/{i}.mp3")
        first_two = store.list_pending_appends(2)
        assert [m.youtube_video_id for m in first_two] == ["vid0", "vid1"]

    def test_mark_appended_removes_from_queue_and_clears_stuck(self, tmp_path):
        store = _store(tmp_path)
        pl = store.upsert_playlist("PL", "P")
        store.add_member(pl.id, "vidA", position=1, landed_path="/lib/a.mp3")
        (m,) = store.list_pending_appends(10)
        store.mark_member_stuck(m.id)  # flagged stuck first...
        store.mark_member_appended(m.id, "item-1")  # ...then finally appends
        assert store.list_pending_appends(10) == []
        assert store.list_members(pl.id)[0].stuck_since is None  # flag cleared

    def test_mark_member_stuck_preserves_the_first_breach_time(self, tmp_path):
        store = _store(tmp_path)
        pl = store.upsert_playlist("PL", "P")
        store.add_member(pl.id, "vidA", position=1, landed_path="/lib/a.mp3")
        (m,) = store.list_pending_appends(10)
        store.mark_member_stuck(m.id)
        first = store.list_members(pl.id)[0].stuck_since
        store.mark_member_stuck(m.id)  # a later pass notices it's still stuck
        assert store.list_members(pl.id)[0].stuck_since == first  # first time kept, not bumped

    def test_repend_appended_members_requeues_only_appended_rows(self, tmp_path):
        """T-315: rebuild after a container deletion re-queues the stamped-done rows (clearing
        their item id + stuck flag) and leaves already-pending rows alone. Idempotent."""
        store = _store(tmp_path)
        pl = store.upsert_playlist("PL", "P")
        store.add_member(pl.id, "vidA", position=1,
                         jellyfin_item_id="itA", landed_path="/lib/a.mp3")  # appended
        store.add_member(pl.id, "vidB", position=2, landed_path="/lib/b.mp3")  # already pending
        n = store.repend_appended_members(pl.id)
        assert n == 1  # only the appended row was re-queued
        pending = {m.youtube_video_id for m in store.list_pending_appends(10)}
        assert pending == {"vidA", "vidB"}  # A re-queued, B still pending
        assert store.repend_appended_members(pl.id) == 0  # idempotent once nothing is appended


# --- 3. reconcile orchestration ---------------------------------------------


def _playlist_with_pending(tmp_path, *, jellyfin_playlist_id="jf-pl"):
    store = _store(tmp_path)
    pl = store.upsert_playlist("PL", "P")
    if jellyfin_playlist_id is not None:
        store.set_jellyfin_playlist_id(pl.id, jellyfin_playlist_id)
    store.add_member(pl.id, "vidA", position=1, landed_path="/lib/A/x.mp3")
    return store, pl


def _backdate(store, member_id, *, minutes):
    """Push a member's created_at into the past so the wall-clock stuck ceiling is crossed."""
    old = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
    with store._connect() as conn:  # noqa: SLF001 — white-box test setup
        conn.execute(
            "UPDATE playlist_members SET created_at = ? WHERE id = ?", (old, member_id)
        )


class TestReconcile:
    def test_hit_appends_with_stored_jellyfin_playlist_id_and_stamps(self, tmp_path):
        store, _ = _playlist_with_pending(tmp_path)
        appends = []
        n = reconcile_pending_appends(
            store, limit=10,
            resolve_fn=_resolved("item-42"),
            append_fn=lambda pl_id, item_id, settings=None: (
                appends.append((pl_id, item_id)) or True
            ),
            precheck_fn=_empty_precheck,
        )
        assert n == 1
        assert appends == [("jf-pl", "item-42")]  # the id T-302 stored
        assert store.list_pending_appends(10) == []  # stamped → drained

    def test_not_indexed_defers_without_dropping_or_flagging(self, tmp_path):
        store, _ = _playlist_with_pending(tmp_path)
        n = reconcile_pending_appends(
            store, limit=10,
            resolve_fn=_resolve_status(ResolveStatus.NOT_INDEXED),
            append_fn=lambda *a, **k: pytest.fail("must not append on a miss"),
            precheck_fn=_empty_precheck,
        )
        assert n == 0
        (m,) = store.list_pending_appends(10)
        assert m.jellyfin_item_id is None and m.stuck_since is None  # pending, not yet stuck

    def test_uncreated_container_is_created_then_drained(self, tmp_path):
        """T-306 create-if-missing: a NULL-id container is created now, its id persisted, and
        the member appends — not skipped forever."""
        store, pl = _playlist_with_pending(tmp_path, jellyfin_playlist_id=None)
        creates, appends = [], []
        n = reconcile_pending_appends(
            store, limit=10,
            create_fn=lambda name, settings=None: creates.append(name) or "jf-new",
            resolve_fn=_resolved("item-42"),
            append_fn=lambda pl_id, item_id, settings=None: (
                appends.append((pl_id, item_id)) or True
            ),
            precheck_fn=_empty_precheck,
        )
        assert n == 1
        assert creates == ["P"]  # created under the playlist's derived title
        assert appends == [("jf-new", "item-42")]  # appended to the just-created container
        assert store.get_playlist(pl.id).jellyfin_playlist_id == "jf-new"  # id persisted
        assert store.list_pending_appends(10) == []  # stamped → drained

    def test_uncreated_container_create_still_failing_defers_untouched(self, tmp_path):
        """Jellyfin still absent/flaky at drain time → create returns None → defer, no stuck,
        no resolve/append attempted (the container's fault, not the member's)."""
        store, _ = _playlist_with_pending(tmp_path, jellyfin_playlist_id=None)
        n = reconcile_pending_appends(
            store, limit=10,
            create_fn=lambda name, settings=None: None,  # create still failing
            resolve_fn=lambda *a, **k: pytest.fail("must not resolve without a container"),
            append_fn=lambda *a, **k: pytest.fail("must not append"),
            precheck_fn=lambda *a, **k: pytest.fail("must not pre-check a container-less row"),
        )
        assert n == 0
        (m,) = store.list_pending_appends(10)
        assert m.stuck_since is None  # the container's fault, not the member's (T-306)

    def test_two_members_of_an_uncreated_container_create_it_once(self, tmp_path):
        """The double-create guard: two pending members of the same NULL-id playlist create
        exactly one Jellyfin container (the per-pass cache refresh), and both append to it."""
        store = _store(tmp_path)
        pl = store.upsert_playlist("PL", "P")  # no jellyfin_playlist_id
        store.add_member(pl.id, "vidA", position=1, landed_path="/lib/a.mp3")
        store.add_member(pl.id, "vidB", position=2, landed_path="/lib/b.mp3")
        creates, appends = [], []
        n = reconcile_pending_appends(
            store, limit=10,
            create_fn=lambda name, settings=None: creates.append(name) or "jf-once",
            resolve_fn=lambda path, settings=None: ResolveResult(
                ResolveStatus.RESOLVED, f"item-{path[-5]}"
            ),
            append_fn=lambda pl_id, item_id, settings=None: (
                appends.append((pl_id, item_id)) or True
            ),
            precheck_fn=_empty_precheck,
        )
        assert n == 2
        assert creates == ["P"]  # created ONCE, not once per member
        assert {pl_id for pl_id, _ in appends} == {"jf-once"}
        assert store.get_playlist(pl.id).jellyfin_playlist_id == "jf-once"

    # --- T-315: a created-then-deleted container is re-created, not deferred forever ---

    def _absent_then_readable(self, dead_id):
        """A precheck_fn: ABSENT for the stale id, READABLE-empty for the re-created one."""
        def fn(pl_id, settings=None):
            if pl_id == dead_id:
                return PlaylistProbe(PlaylistProbeStatus.ABSENT)
            return PlaylistProbe(PlaylistProbeStatus.READABLE, set())
        return fn

    def test_deleted_container_is_recreated_and_drained(self, tmp_path):
        """A non-null-but-deleted jellyfin id (Jellyfin 404s it) is re-created, its new id
        persisted, and the pending member appends to the NEW container — the T-306 gap where a
        stale id deferred every pass forever."""
        store, pl = _playlist_with_pending(tmp_path, jellyfin_playlist_id="jf-dead")
        creates, appends = [], []
        n = reconcile_pending_appends(
            store, limit=10,
            create_fn=lambda name, settings=None: creates.append(name) or "jf-fresh",
            resolve_fn=_resolved("item-42"),
            append_fn=lambda pl_id, item_id, settings=None: (
                appends.append((pl_id, item_id)) or True
            ),
            precheck_fn=self._absent_then_readable("jf-dead"),
        )
        assert n == 1
        assert creates == ["P"]  # re-created under the playlist's title
        assert appends == [("jf-fresh", "item-42")]  # appended to the NEW container, not the dead one
        assert store.get_playlist(pl.id).jellyfin_playlist_id == "jf-fresh"  # id re-pointed
        assert store.list_pending_appends(10) == []  # drained

    def test_deleted_container_recreated_once_for_two_members(self, tmp_path):
        """Double-create guard on the recovery path: two members of one deleted playlist
        re-create exactly one container and both append to it (the per-pass cache refresh)."""
        store = _store(tmp_path)
        pl = store.upsert_playlist("PL", "P")
        store.set_jellyfin_playlist_id(pl.id, "jf-dead")
        store.add_member(pl.id, "vidA", position=1, landed_path="/lib/a.mp3")
        store.add_member(pl.id, "vidB", position=2, landed_path="/lib/b.mp3")
        creates, appends = [], []
        n = reconcile_pending_appends(
            store, limit=10,
            create_fn=lambda name, settings=None: creates.append(name) or "jf-fresh",
            resolve_fn=lambda path, settings=None: ResolveResult(
                ResolveStatus.RESOLVED, f"item-{path[-5]}"
            ),
            append_fn=lambda pl_id, item_id, settings=None: (
                appends.append((pl_id, item_id)) or True
            ),
            precheck_fn=self._absent_then_readable("jf-dead"),
        )
        assert n == 2
        assert creates == ["P"]  # re-created ONCE, not once per member
        assert {pl_id for pl_id, _ in appends} == {"jf-fresh"}
        assert store.get_playlist(pl.id).jellyfin_playlist_id == "jf-fresh"

    def test_deleted_container_recreate_still_failing_defers_untouched(self, tmp_path):
        """ABSENT but the re-create POST still fails (Jellyfin flaky) → defer untouched, no
        stuck, nothing resolved/appended (the container's fault, not the member's)."""
        store, pl = _playlist_with_pending(tmp_path, jellyfin_playlist_id="jf-dead")
        (m0,) = store.list_pending_appends(10)
        _backdate(store, m0.id, minutes=120)  # would be 'stuck' if we mistook this for unindexed
        n = reconcile_pending_appends(
            store, limit=10,
            create_fn=lambda name, settings=None: None,  # re-create still failing
            resolve_fn=lambda *a, **k: pytest.fail("must not resolve without a live container"),
            append_fn=lambda *a, **k: pytest.fail("must not append"),
            precheck_fn=self._absent_then_readable("jf-dead"),
        )
        assert n == 0
        (m,) = store.list_pending_appends(10)
        assert m.stuck_since is None  # the container's fault, not the member's
        assert store.get_playlist(pl.id).jellyfin_playlist_id == "jf-dead"  # unchanged

    def test_transiently_unreachable_container_is_not_recreated(self, tmp_path):
        """The safety half of T-315: an UNREADABLE pre-check (outage / down Jellyfin, NOT a 404)
        must NOT re-create — that would orphan a still-live playlist with a duplicate. Defer
        untouched, no create, no append, no stuck."""
        store, pl = _playlist_with_pending(tmp_path, jellyfin_playlist_id="jf-live")
        (m0,) = store.list_pending_appends(10)
        _backdate(store, m0.id, minutes=120)
        n = reconcile_pending_appends(
            store, limit=10,
            create_fn=lambda *a, **k: pytest.fail("must not re-create a merely-unreachable playlist"),
            resolve_fn=lambda *a, **k: pytest.fail("must not resolve when membership unreadable"),
            append_fn=lambda *a, **k: pytest.fail("must not blind-append"),
            precheck_fn=_probe_status(PlaylistProbeStatus.UNREADABLE),
        )
        assert n == 0
        (m,) = store.list_pending_appends(10)
        assert m.jellyfin_item_id is None and m.stuck_since is None  # untouched
        assert store.get_playlist(pl.id).jellyfin_playlist_id == "jf-live"  # NOT re-pointed

    def test_deleted_container_rebuilds_previously_appended_members(self, tmp_path):
        """The recovered playlist rebuilds from playlist_members (source of truth), not just the
        rows that were still pending at deletion: a member already appended to the DELETED
        container is re-queued and re-drains into the NEW one — no silent track loss."""
        store = _store(tmp_path)
        pl = store.upsert_playlist("PL", "P")
        store.set_jellyfin_playlist_id(pl.id, "jf-dead")
        store.add_member(pl.id, "vidA", position=1,
                         jellyfin_item_id="old-A", landed_path="/lib/a.mp3")  # appended to jf-dead
        store.add_member(pl.id, "vidB", position=2, landed_path="/lib/b.mp3")  # still pending

        appends = []

        def resolve(path, settings=None):
            return ResolveResult(
                ResolveStatus.RESOLVED, "item-A" if path == "/lib/a.mp3" else "item-B"
            )

        kw = dict(
            create_fn=lambda name, settings=None: "jf-fresh",
            resolve_fn=resolve,
            append_fn=lambda pl_id, item_id, settings=None: appends.append((pl_id, item_id)) or True,
            precheck_fn=self._absent_then_readable("jf-dead"),
        )
        # pass 1: B (pending) lands in the re-created container; A is re-queued by the rebuild
        reconcile_pending_appends(store, limit=10, **kw)
        # pass 2: A now re-drains into the new container too
        reconcile_pending_appends(store, limit=10, **kw)

        assert set(appends) == {("jf-fresh", "item-A"), ("jf-fresh", "item-B")}  # both, on jf-fresh
        assert store.list_pending_appends(10) == []  # fully rebuilt, nothing left pending
        assert store.get_playlist(pl.id).jellyfin_playlist_id == "jf-fresh"

    # --- bug 3: an outage strands nothing and spends no budget, on BOTH organs ---------

    def test_resolve_unreachable_defers_untouched(self, tmp_path):
        """Jellyfin down on the resolve path: no append, no stuck — even past the ceiling."""
        store, _ = _playlist_with_pending(tmp_path)
        (m0,) = store.list_pending_appends(10)
        _backdate(store, m0.id, minutes=120)  # would be 'stuck' if we mistook down for unindexed
        n = reconcile_pending_appends(
            store, limit=10,
            resolve_fn=_resolve_status(ResolveStatus.UNREACHABLE),
            append_fn=lambda *a, **k: pytest.fail("must not append during an outage"),
            precheck_fn=_empty_precheck,
        )
        assert n == 0
        (m,) = store.list_pending_appends(10)
        assert m.jellyfin_item_id is None and m.stuck_since is None  # untouched

    def test_precheck_unreachable_defers_the_whole_playlist_never_blind_appends(self, tmp_path):
        """Can't read current members → never append. The read is what makes it idempotent."""
        store, _ = _playlist_with_pending(tmp_path)
        n = reconcile_pending_appends(
            store, limit=10,
            resolve_fn=lambda *a, **k: pytest.fail("must not resolve when membership unreadable"),
            append_fn=lambda *a, **k: pytest.fail("must not blind-append"),
            precheck_fn=_probe_status(PlaylistProbeStatus.UNREADABLE),  # can't read
        )
        assert n == 0
        (m,) = store.list_pending_appends(10)
        assert m.jellyfin_item_id is None and m.stuck_since is None

    def test_precheck_unreadable_never_flags_stuck_even_past_ceiling(self, tmp_path):
        """Pre-check None is indistinguishable from an outage, so it must NOT flag stuck (that
        would paint a whole backlog stuck on any multi-minute outage — the conflation the reframe
        kills). Pure defer, consistent with resolve-UNREACHABLE; a missing container is T-306's."""
        store, _ = _playlist_with_pending(tmp_path)
        (m0,) = store.list_pending_appends(10)
        _backdate(store, m0.id, minutes=61)
        n = reconcile_pending_appends(
            store, limit=10,
            resolve_fn=lambda *a, **k: pytest.fail("must not resolve when membership unreadable"),
            append_fn=lambda *a, **k: pytest.fail("must not blind-append"),
            precheck_fn=_probe_status(PlaylistProbeStatus.UNREADABLE),  # unreadable / outage
        )
        assert n == 0
        (m,) = store.list_pending_appends(10)  # still pending + retryable...
        assert m.stuck_since is None           # ...and NOT flagged stuck on an unreadable pass

    def test_failed_append_leaves_it_pending_no_penalty(self, tmp_path):
        store, _ = _playlist_with_pending(tmp_path)

        def boom(pl_id, item_id, settings=None):
            raise JellyfinAppendError("503")

        n = reconcile_pending_appends(
            store, limit=10,
            resolve_fn=_resolved("item-42"), append_fn=boom, precheck_fn=_empty_precheck,
        )
        assert n == 0
        (m,) = store.list_pending_appends(10)
        assert m.jellyfin_item_id is None and m.stuck_since is None  # pending, unpenalised

    def test_degraded_append_is_not_stamped_as_done(self, tmp_path):
        """append_fn returning False (degraded) must leave the member pending, not stamped."""
        store, _ = _playlist_with_pending(tmp_path)
        n = reconcile_pending_appends(
            store, limit=10,
            resolve_fn=_resolved("item-42"),
            append_fn=lambda pl_id, item_id, settings=None: False,  # degraded no-op
            precheck_fn=_empty_precheck,
        )
        assert n == 0
        (m,) = store.list_pending_appends(10)
        assert m.jellyfin_item_id is None and m.stuck_since is None  # pending, unpenalised

    # --- bug 2: idempotent append across a crash between POST and stamp ----------------

    def test_already_in_playlist_stamps_without_reposting(self, tmp_path):
        """The POST landed on a prior pass but its stamp was lost to a crash — the pre-check
        sees the item already present, so we stamp WITHOUT a second POST (no double-add)."""
        store, _ = _playlist_with_pending(tmp_path)
        n = reconcile_pending_appends(
            store, limit=10,
            resolve_fn=_resolved("item-42"),
            append_fn=lambda *a, **k: pytest.fail("must not re-POST an already-present item"),
            precheck_fn=_readable("item-42"),  # already there
        )
        assert n == 1
        assert store.list_pending_appends(10) == []  # stamped

    def test_two_rows_same_item_in_one_pass_post_once(self, tmp_path):
        """The per-pass set refresh: two members resolving to the same item must POST once."""
        store = _store(tmp_path)
        pl = store.upsert_playlist("PL", "P")
        store.set_jellyfin_playlist_id(pl.id, "jf-pl")
        store.add_member(pl.id, "vidA", position=1, landed_path="/lib/a.mp3")
        store.add_member(pl.id, "vidB", position=2, landed_path="/lib/b.mp3")
        posts = []
        n = reconcile_pending_appends(
            store, limit=10,
            resolve_fn=_resolved("same-item"),  # both rows resolve to the same library item
            append_fn=lambda pl_id, item_id, settings=None: posts.append(item_id) or True,
            precheck_fn=_empty_precheck,
        )
        assert posts == ["same-item"]  # POSTed exactly once...
        assert n == 2  # ...but both rows stamped
        assert store.list_pending_appends(10) == []

    # --- bug 5: a genuinely never-indexable file surfaces as visible-stuck, not dropped -

    def test_past_ceiling_not_indexed_flags_stuck_but_keeps_retrying(self, tmp_path):
        store, _ = _playlist_with_pending(tmp_path)
        (m0,) = store.list_pending_appends(10)
        _backdate(store, m0.id, minutes=61)  # waited past the 45-min ceiling, Jellyfin reachable
        n = reconcile_pending_appends(
            store, limit=10,
            resolve_fn=_resolve_status(ResolveStatus.NOT_INDEXED),
            append_fn=lambda *a, **k: pytest.fail("nothing to append yet"),
            precheck_fn=_empty_precheck,
        )
        assert n == 0
        (m,) = store.list_pending_appends(10)  # STILL pending — visible, not benched
        assert m.stuck_since is not None

    def test_fresh_not_indexed_is_not_flagged_stuck(self, tmp_path):
        store, _ = _playlist_with_pending(tmp_path)  # created just now, well under the ceiling
        reconcile_pending_appends(
            store, limit=10,
            resolve_fn=_resolve_status(ResolveStatus.NOT_INDEXED),
            append_fn=lambda *a, **k: None,
            precheck_fn=_empty_precheck,
        )
        (m,) = store.list_pending_appends(10)
        assert m.stuck_since is None

    def test_a_stuck_row_appends_and_clears_when_jellyfin_recovers(self, tmp_path):
        store, _ = _playlist_with_pending(tmp_path)
        (m0,) = store.list_pending_appends(10)
        _backdate(store, m0.id, minutes=61)
        # pass 1: still not indexed, past ceiling → flagged stuck, still pending
        reconcile_pending_appends(
            store, limit=10,
            resolve_fn=_resolve_status(ResolveStatus.NOT_INDEXED),
            append_fn=lambda *a, **k: None, precheck_fn=_empty_precheck,
        )
        assert store.list_pending_appends(10)[0].stuck_since is not None
        # pass 2: Jellyfin finally indexed it → appends, drains, clears the flag
        n = reconcile_pending_appends(
            store, limit=10,
            resolve_fn=_resolved("item-late"),
            append_fn=lambda *a, **k: True, precheck_fn=_empty_precheck,
        )
        assert n == 1
        assert store.list_pending_appends(10) == []
        assert store.list_members(store.get_playlist(m0.playlist_id).id)[0].stuck_since is None

    # --- ADR-003 isolation + idempotency across passes --------------------------------

    def test_one_bad_member_does_not_abort_the_pass(self, tmp_path):
        """A store error on one member is isolated — the others still drain (never-raises)."""
        store = _store(tmp_path)
        pl = store.upsert_playlist("PL", "P")
        store.set_jellyfin_playlist_id(pl.id, "jf-pl")
        store.add_member(pl.id, "vidA", position=1, landed_path="/lib/a.mp3")
        store.add_member(pl.id, "vidB", position=2, landed_path="/lib/b.mp3")
        appended = []

        def resolve(path, settings=None):
            return ResolveResult(
                ResolveStatus.RESOLVED, "item-A" if path == "/lib/a.mp3" else "item-B"
            )

        def append(pl_id, item_id, settings=None):
            if item_id == "item-A":
                raise RuntimeError("unexpected store/edge blow-up")
            appended.append(item_id)
            return True

        n = reconcile_pending_appends(
            store, limit=10, resolve_fn=resolve, append_fn=append, precheck_fn=_empty_precheck,
        )
        assert n == 1 and appended == ["item-B"]  # vidB drained despite vidA blowing up

    def test_drain_is_idempotent_across_passes(self, tmp_path):
        store, _ = _playlist_with_pending(tmp_path)
        calls = []
        kw = dict(
            resolve_fn=_resolved("item-42"),
            append_fn=lambda pl_id, item_id, settings=None: calls.append(item_id) or True,
            precheck_fn=_empty_precheck,
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
