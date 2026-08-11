"""T-206 — the reconcile Verdict's park story must survive a restart.

ADR-010's lesson: a park discriminator that lives only in the live SSE event is
unrecoverable after a reload, and spec §7 requires that "restarting the backend
preserves parked reviews". T-028 already paid this for `score`; T-206 does it for the
Verdict's `reason`, its `contradictions`, and the LLM-ranked candidate order.

As in the T-028 file, the tests that carry the weight are the *restart* ones — a
round-trip through a second `Store` on the same file, which is what a `uvicorn` restart
actually is. An in-memory assertion would pass without any persistence at all.
"""

import json
import sqlite3

import pytest

from app.db import Store
from app.reviews import _hydrate

REASON = "Only Shazam agrees; YouTube says Frank Ocean."
CONTRADICTIONS = ["yt: Frank Ocean ≠ Coldplay", "fp: absent"]


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "jobs.db"


def _park(store, *, reason=REASON, contradictions=CONTRADICTIONS,
          candidate_ids=("mb-cold", "rec-A")):
    job = store.create_job("https://youtu.be/abc")
    return store.create_review(
        job_id=job.id,
        staging_path="/tmp/staging/song.mp3",
        query="some song",
        candidate_ids=list(candidate_ids),
        rec="medium",
        reason=reason,
        contradictions=contradictions,
    )


def test_park_story_survives_a_restart(db_path):
    """The whole point of the ticket: a new process reads the story back.

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
    assert reloaded.reason == REASON
    assert reloaded.contradictions == CONTRADICTIONS
    # The ranked order is persisted as the candidate_ids list itself, in order.
    assert reloaded.candidate_ids == ["mb-cold", "rec-A"]


def test_hydrated_row_carries_reason_and_contradictions(db_path, monkeypatch):
    """`GET /api/reviews`' row shape — the fields T-207's card re-hydrates from.

    MusicBrainz is stubbed out: this asserts the story reaches the API row, not
    that the network works.
    """
    monkeypatch.setattr(
        "app.reviews._candidate",
        lambda cid, score=None: {"candidate_id": cid, "score": score},
    )
    store = Store(db_path)
    store.init_schema()
    review = _park(store)

    row = _hydrate(store.get_review(review.id))

    assert row["reason"] == REASON
    assert row["contradictions"] == CONTRADICTIONS


def test_park_with_no_story_reads_as_empty_not_null(db_path):
    """The R1/degrade park writes no Verdict — reason NULL, contradictions []."""
    store = Store(db_path)
    store.init_schema()
    review = _park(store, reason=None, contradictions=[])

    reloaded = store.get_review(review.id)
    assert reloaded.reason is None
    assert reloaded.contradictions == []


# --- the migration ------------------------------------------------------------


def _pre_t206_db(path):
    """A DB in the shape T-206 finds on the owner's disk: the T-029-era reviews table
    (candidate_scores_json + last_error present) but no `reason`/`contradictions_json`
    columns at all, with one pending review already parked."""
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
            candidate_ids_json TEXT NOT NULL, candidate_scores_json TEXT,
            rec TEXT NOT NULL, status TEXT NOT NULL, last_error TEXT
        );
        """
    )
    conn.execute(
        "INSERT INTO jobs VALUES ('job-old', 'https://youtu.be/old', 'review', '2026-08-01')"
    )
    conn.execute(
        "INSERT INTO reviews "
        "(id, job_id, staging_path, query, candidate_ids_json, rec, status) "
        "VALUES ('rev-old', 'job-old', '/tmp/old.mp3', 'old song', ?, 'medium', 'pending')",
        (json.dumps(["rec-legacy"]),),
    )
    conn.commit()
    conn.close()


def test_migration_applies_columns_to_a_pre_existing_db(db_path):
    """Spec §7's promise, against a real pre-T-206 row.

    The `_ADDED_COLUMNS` path must add `reason` + `contradictions_json` to the owner's
    live table (a `CREATE TABLE` edit would no-op on it), and the existing parked review
    must still be there afterwards, reading its new fields as "unknown" — NULL reason and
    an empty contradiction list, never a crash.
    """
    _pre_t206_db(db_path)

    store = Store(db_path)
    store.init_schema()
    legacy = store.get_review("rev-old")

    assert legacy is not None
    assert legacy.candidate_ids == ["rec-legacy"]
    assert legacy.status == "pending"
    assert legacy.reason is None
    assert legacy.contradictions == []


def test_migration_is_idempotent(db_path):
    """`init_schema()` runs on every boot; the second must not error on a column
    that is already there."""
    _pre_t206_db(db_path)
    store = Store(db_path)
    store.init_schema()
    store.init_schema()  # would raise "duplicate column name" if unguarded

    review = _park(store)
    reloaded = store.get_review(review.id)
    assert reloaded.reason == REASON
    assert reloaded.contradictions == CONTRADICTIONS
