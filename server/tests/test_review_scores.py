"""T-028 — the candidate `score` must survive a restart.

ADR-010 makes `score` the discriminator the owner picks on; spec §7 requires that
"restarting the backend preserves parked reviews". Before T-028 those two were not
both true: the score was computed at park time, streamed once, and dropped, so
`GET /api/reviews` returned `score: null` on every row forever.

The tests that matter here are the *restart* ones — a round-trip through a second
`Store` on the same file, which is what a `uvicorn` restart actually is. An
in-memory assertion would have passed before T-028 too.
"""

import json
import sqlite3

import pytest

from app.db import Store
from app.reviews import _hydrate

SCORES = {"rec-A": 0.91, "rec-B": 0.63}


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "jobs.db"


def _park(store, *, scores=SCORES, candidate_ids=("rec-A", "rec-B")):
    job = store.create_job("https://youtu.be/abc")
    return store.create_review(
        job_id=job.id,
        staging_path="/tmp/staging/song.mp3",
        query="some song",
        candidate_ids=list(candidate_ids),
        rec="medium",
        candidate_scores=scores,
    )


def test_scores_survive_a_restart(db_path):
    """The whole point of the ticket: a new process reads the scores back.

    Two `Store` instances on one file — no shared memory, which is exactly the
    relationship between the process that parked and the one that lists.
    """
    first = Store(db_path)
    first.init_schema()
    review = _park(first)

    second = Store(db_path)
    second.init_schema()
    reloaded = second.get_review(review.id)

    assert reloaded is not None
    assert reloaded.candidate_scores == SCORES


def test_hydrated_row_carries_the_score(db_path, monkeypatch):
    """`GET /api/reviews`' row shape — the field T-017's picker reads.

    MusicBrainz is stubbed out: this asserts the score reaches the API row, not
    that the network works.
    """
    monkeypatch.setattr(
        "app.reviews._candidate",
        lambda cid, score=None: {
            "candidate_id": cid,
            "title": None,
            "artist": None,
            "score": score,
        },
    )
    store = Store(db_path)
    store.init_schema()
    review = _park(store)

    row = _hydrate(store.get_review(review.id))

    assert [c["score"] for c in row["candidates"]] == [0.91, 0.63]


def test_score_follows_its_own_candidate_id(db_path, monkeypatch):
    """A map, not a parallel array — order can't smear one score onto another.

    Parking the ids in the reverse order to the map must still pair each id with
    its own score. This is the failure an id+score array invites.
    """
    monkeypatch.setattr(
        "app.reviews._candidate",
        lambda cid, score=None: {"candidate_id": cid, "score": score},
    )
    store = Store(db_path)
    store.init_schema()
    review = _park(store, candidate_ids=("rec-B", "rec-A"))

    row = _hydrate(store.get_review(review.id))

    assert {c["candidate_id"]: c["score"] for c in row["candidates"]} == SCORES


def test_duplicate_park_stores_no_scores(db_path):
    """A "keep which copy?" park scores nothing; empty must not raise."""
    store = Store(db_path)
    store.init_schema()
    review = _park(store, scores={})

    assert store.get_review(review.id).candidate_scores == {}


# --- the migration ------------------------------------------------------------


def _pre_t028_db(path):
    """A DB in the exact shape T-028 found on the owner's disk: one parked review,
    written by the old schema with no `candidate_scores_json` column at all."""
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE jobs (
            id TEXT PRIMARY KEY, url TEXT NOT NULL,
            status TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE reviews (
            id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id),
            staging_path TEXT NOT NULL, query TEXT NOT NULL,
            candidate_ids_json TEXT NOT NULL, rec TEXT NOT NULL, status TEXT NOT NULL
        );
        """
    )
    conn.execute(
        "INSERT INTO jobs VALUES ('job-old', 'https://youtu.be/old', 'review', '2026-07-18')"
    )
    conn.execute(
        "INSERT INTO reviews VALUES ('rev-old', 'job-old', '/tmp/old.mp3', "
        "'old song', ?, 'medium', 'pending')",
        (json.dumps(["rec-legacy"]),),
    )
    conn.commit()
    conn.close()


def test_migration_preserves_the_existing_parked_review(db_path):
    """Spec §7's promise, against a real pre-T-028 row.

    The owner's live DB had one pending review when this shipped. It must still be
    there afterwards — a migration that drops it breaks the guarantee the whole
    reviews table exists to keep.
    """
    _pre_t028_db(db_path)

    store = Store(db_path)
    store.init_schema()
    legacy = store.get_review("rev-old")

    assert legacy is not None
    assert legacy.candidate_ids == ["rec-legacy"]
    assert legacy.query == "old song"
    assert legacy.status == "pending"


def test_legacy_row_reads_as_unknown_not_a_crash(db_path):
    """A NULL column decodes to {} — i.e. score `None`, the pre-T-028 behaviour."""
    _pre_t028_db(db_path)
    store = Store(db_path)
    store.init_schema()

    assert store.get_review("rev-old").candidate_scores == {}


def test_park_path_persists_the_score_it_streams(db_path):
    """The integration point the other tests skip: `_candidate_rows` → the DB row.

    Every test above hands `create_review` a score map directly, which proves
    storage but not that the *park* produces one. This drives the real
    `_candidate_rows` over beets-shaped candidates (`.info.track_id` + `.distance`)
    and asserts the score that reaches the DB is the same one the SSE event carries
    — the two must not be able to disagree, which is why `_record_review` derives
    the map from the event rows rather than computing it a second time.
    """
    from types import SimpleNamespace

    from app.import_seam import Dominance, FingerprintTrustSession, _candidate_rows

    candidates = [
        SimpleNamespace(
            info=SimpleNamespace(track_id="rec-A", title="A", artist="Artist"),
            distance=0.09,  # score 0.91
        ),
        SimpleNamespace(
            info=SimpleNamespace(track_id="rec-B", title="B", artist="Artist"),
            distance=0.37,  # score 0.63
        ),
    ]
    rows = _candidate_rows(candidates)
    streamed = {r["candidate_id"]: r["score"] for r in rows}

    store = Store(db_path)
    store.init_schema()
    job = store.create_job("https://youtu.be/abc")

    # Call the real `_record_review`, not a copy of its logic — it needs only these
    # five attributes off `self`, so a stub stands in for the whole beets session.
    # Duplicating its dict comprehension here would test this file, not the product.
    seam = SimpleNamespace(
        store=store,
        job_id=job.id,
        staging_path="/tmp/staging/song.mp3",
        normalized_query="a song",
        outcomes=[],
    )
    review = FingerprintTrustSession._record_review(
        seam,
        ["rec-A", "rec-B"],
        "medium",
        Dominance(top_score=0.91, runner_up_score=0.63, top_recording_ids=("rec-A",)),
        candidates=rows,
    )

    stored = Store(db_path).get_review(review.id).candidate_scores
    assert stored == streamed
    assert stored["rec-A"] == pytest.approx(0.91)
    assert stored["rec-B"] == pytest.approx(0.63)


def test_migration_is_idempotent(db_path):
    """`init_schema()` runs on every boot; the second must not error on a column
    that is already there."""
    _pre_t028_db(db_path)
    store = Store(db_path)
    store.init_schema()
    store.init_schema()  # would raise "duplicate column name" if unguarded

    review = _park(store)
    assert store.get_review(review.id).candidate_scores == SCORES
