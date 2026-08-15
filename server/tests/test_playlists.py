"""T-300 tests — the R2 batch/backfill data model (ADR-027), all offline.

The ticket's "Done when", one class each:

1. **Migration** — the two new tables + three `jobs` columns apply cleanly to a
   **pre-existing** DB (tables via `_SCHEMA`'s `CREATE TABLE IF NOT EXISTS`, columns via
   `_ADDED_COLUMNS`'s ALTER), and `init_schema` is idempotent on re-run.
2. **Round-trip across a restart** — a playlist + a member track-job written by one
   `Store`, read back by a fresh `Store` on the same path (the process-restart proof).
3. **UNIQUE constraints hold** — the `playlists` create-or-reuse upsert is idempotent,
   and a double-add to membership is a structural no-op.
4. **The R1 switch** — a single-song `create_job` still writes `playlist_id = NULL`.
"""

import sqlite3

from app.db import Store


def _store(tmp_path):
    store = Store(tmp_path / "jobs.db")
    store.init_schema()
    return store


# --- 1. migration on a pre-existing DB --------------------------------------


class TestMigration:
    def test_new_tables_and_columns_apply_to_a_preexisting_r1_db(self, tmp_path):
        """A DB that predates R2 gains the tables + columns on the next init_schema.

        Simulate the owner's live DB: only the R1-shape `jobs`/`reviews` tables exist,
        with no batch columns. `init_schema` must create `playlists`/`playlist_members`
        (via `_SCHEMA`) and ALTER the three `jobs` columns in (via `_ADDED_COLUMNS`)
        without disturbing the existing row.
        """
        db_path = tmp_path / "jobs.db"
        conn = sqlite3.connect(db_path)
        conn.executescript(
            "CREATE TABLE jobs (id TEXT PRIMARY KEY, url TEXT NOT NULL, "
            "status TEXT NOT NULL, created_at TEXT NOT NULL);"
        )
        conn.execute(
            "INSERT INTO jobs (id, url, status, created_at) VALUES "
            "('old', 'https://youtu.be/pre', 'done', '2026-01-01T00:00:00+00:00')"
        )
        conn.commit()
        conn.close()

        Store(db_path).init_schema()

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        tables = {
            r["name"]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert {"playlists", "playlist_members"} <= tables
        job_cols = {r["name"] for r in conn.execute("PRAGMA table_info(jobs)")}
        assert {"playlist_id", "position", "youtube_video_id"} <= job_cols
        # The two hot-path indexes (created after _migrate, over the ALTERed columns).
        indexes = {
            r["name"]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
        }
        assert {"idx_jobs_youtube_video_id", "idx_jobs_playlist_id"} <= indexes
        # The pre-existing row survives, and reads its new columns as NULL (= single-song).
        old = conn.execute("SELECT * FROM jobs WHERE id = 'old'").fetchone()
        assert old["playlist_id"] is None
        conn.close()

    def test_init_schema_is_idempotent(self, tmp_path):
        """Re-running init_schema on a fully-migrated DB is a no-op, not an error."""
        store = _store(tmp_path)
        store.init_schema()  # second call must not raise (IF NOT EXISTS / column guard)
        pl = store.upsert_playlist("yt-list-1", "Summer")
        assert store.get_playlist(pl.id) is not None


# --- 2. round-trip across a process restart ---------------------------------


class TestRoundTripAcrossRestart:
    def test_playlist_and_member_job_survive_a_new_store(self, tmp_path):
        """Write with one Store, read back with a fresh Store on the same file.

        A `Store` holds only a path, not a connection, so a new `Store` on the same DB
        IS a process restart for the durability that matters here (ADR-027 seam 5).
        """
        db_path = tmp_path / "jobs.db"
        writer = Store(db_path)
        writer.init_schema()

        playlist = writer.upsert_playlist("yt-list-42", "Monthly — August")
        writer.set_jellyfin_playlist_id(playlist.id, "jf-playlist-99")
        job = writer.create_job(
            "https://youtu.be/trackA",
            playlist_id=playlist.id,
            position=0,
            youtube_video_id="vidA",
        )
        writer.add_member(playlist.id, "vidA", position=0, jellyfin_item_id="jf-item-1")

        # --- restart: a brand-new Store, no shared connection or in-memory state ---
        reader = Store(db_path)

        got_playlist = reader.get_playlist(playlist.id)
        assert got_playlist is not None
        assert got_playlist.youtube_playlist_id == "yt-list-42"
        assert got_playlist.title == "Monthly — August"
        assert got_playlist.jellyfin_playlist_id == "jf-playlist-99"

        got_job = reader.get_job(job.id)
        assert got_job is not None
        assert got_job.playlist_id == playlist.id
        assert got_job.position == 0
        assert got_job.youtube_video_id == "vidA"

        members = reader.list_members(playlist.id)
        assert [(m.youtube_video_id, m.position, m.jellyfin_item_id) for m in members] == [
            ("vidA", 0, "jf-item-1")
        ]

    def test_lookup_by_youtube_playlist_id(self, tmp_path):
        store = _store(tmp_path)
        created = store.upsert_playlist("yt-list-7", "Focus")
        found = store.get_playlist_by_youtube_id("yt-list-7")
        assert found is not None and found.id == created.id
        assert store.get_playlist_by_youtube_id("nope") is None

    def test_pending_append_member_has_null_jellyfin_item(self, tmp_path):
        """ADR-027 seam 1: a resolve-timeout writes membership with a NULL item id."""
        store = _store(tmp_path)
        pl = store.upsert_playlist("yt-list-8", "Drive")
        store.add_member(pl.id, "vidPending", position=3)  # no jellyfin_item_id
        (member,) = store.list_members(pl.id)
        assert member.jellyfin_item_id is None


# --- 3. UNIQUE constraints hold ---------------------------------------------


class TestUniqueConstraints:
    def test_upsert_playlist_is_idempotent_create_or_reuse(self, tmp_path):
        """A re-paste (ADR-027 seam 6) reuses the original row, never a duplicate.

        The second upsert must return the SAME id and keep the original title/jellyfin
        id — `ON CONFLICT DO NOTHING` then SELECT, not a clobbering re-insert.
        """
        store = _store(tmp_path)
        first = store.upsert_playlist("yt-list-dup", "Original Title")
        store.set_jellyfin_playlist_id(first.id, "jf-1")

        second = store.upsert_playlist("yt-list-dup", "A Different Title")
        assert second.id == first.id
        assert second.title == "Original Title"  # not clobbered
        assert second.jellyfin_playlist_id == "jf-1"  # preserved across the re-upsert

    def test_add_member_double_add_is_a_no_op(self, tmp_path):
        """ADR-027 seam 4: UNIQUE(playlist_id, video) makes a double-add impossible."""
        store = _store(tmp_path)
        pl = store.upsert_playlist("yt-list-9", "Repeat")
        assert store.add_member(pl.id, "vidX", position=0) is True
        assert store.add_member(pl.id, "vidX", position=0) is False  # no-op, not a raise
        assert len(store.list_members(pl.id)) == 1

    def test_same_video_in_two_playlists_is_allowed(self, tmp_path):
        """Uniqueness is per (playlist, video) — a July song reappearing in August is fine."""
        store = _store(tmp_path)
        july = store.upsert_playlist("yt-july", "July")
        august = store.upsert_playlist("yt-august", "August")
        assert store.add_member(july.id, "vidShared", position=0) is True
        assert store.add_member(august.id, "vidShared", position=0) is True

    def test_raw_unique_insert_on_playlists_raises(self, tmp_path):
        """The DB-level UNIQUE on youtube_playlist_id is real, not only enforced in Python."""
        store = _store(tmp_path)
        store.upsert_playlist("yt-list-raw", "One")
        conn = sqlite3.connect(tmp_path / "jobs.db")
        try:
            conn.execute(
                "INSERT INTO playlists (id, youtube_playlist_id, title, created_at) "
                "VALUES ('x', 'yt-list-raw', 'Two', '2026-08-15T00:00:00+00:00')"
            )
            raised = False
        except sqlite3.IntegrityError:
            raised = True
        finally:
            conn.close()
        assert raised


# --- 4. the R1 switch -------------------------------------------------------


class TestR1Switch:
    def test_single_song_job_has_null_batch_columns(self, tmp_path):
        """A single-song paste (the R1 path) writes playlist_id = NULL, unchanged."""
        store = _store(tmp_path)
        job = store.create_job("https://youtu.be/single")
        assert job.playlist_id is None
        assert job.position is None
        assert job.youtube_video_id is None
        # …and reads back the same after a restart.
        got = Store(tmp_path / "jobs.db").get_job(job.id)
        assert got is not None and got.playlist_id is None
