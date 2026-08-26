"""Unit tests for the Shazam sense (T-202, spec §5 fail-soft + hard timeout).

A *real* Shazam call needs the 3.12 venv + network and is flaky/offline in CI, so
these tests exercise the machinery this ticket actually owns — the **subprocess
contract** (audio path in → JSON record out) and **kill-on-timeout** — against a
**fake runner** driven by the app's own interpreter. That keeps the error, timeout
and contract paths deterministic while still running the true `Popen` /
timeout-kill / JSON-parse code (no mocking of subprocess).

The one live "known track" check (a populated `matched:true` record with an ISRC)
needs the real venv + network and is run once out-of-band, not here.

Run from `server/`: `./.venv/bin/pytest tests/test_shazam.py -v`
"""

import os
import sys
import textwrap
import time
from pathlib import Path

import pytest

from app import shazam


def _fake_runner(tmp_path: Path, body: str) -> Path:
    """Write a standalone script the app interpreter can run as the 'runner'."""
    path = tmp_path / "fake_runner.py"
    path.write_text(textwrap.dedent(body))
    return path


def _recognize(tmp_path, body, **kw):
    runner = _fake_runner(tmp_path, body)
    return shazam.recognize("audio.mp3", python_bin=sys.executable, runner_path=runner, **kw)


# --- Contract: a valid record round-trips through the subprocess unchanged -----

def test_matched_record_round_trips(tmp_path):
    rec = _recognize(
        tmp_path,
        """
        import json, sys
        print(json.dumps({
            "shazam_artist": "Pa Salieu", "shazam_title": "Frontline",
            "isrc": "GBKPL2000123", "art_url": "https://img", "lyrics": "la la",
            "matched": True, "error": None,
        }))
        """,
    )
    assert rec["matched"] is True
    assert rec["shazam_artist"] == "Pa Salieu"
    assert rec["shazam_title"] == "Frontline"
    assert rec["isrc"] == "GBKPL2000123"
    # art_url / lyrics captured for the record only (spec §3) — present, not dropped.
    assert rec["art_url"] == "https://img"
    assert rec["lyrics"] == "la la"
    assert rec["error"] is None


def test_runner_receives_the_audio_path_argument(tmp_path):
    """Proves the 'audio path in' half of the contract: argv[1] reaches the runner."""
    rec = _recognize(
        tmp_path,
        """
        import json, sys
        print(json.dumps({"shazam_title": sys.argv[1], "matched": True}))
        """,
    )
    assert rec["matched"] is True
    assert rec["shazam_title"] == "audio.mp3"


def test_record_is_always_full_shape(tmp_path):
    """A short runner record is normalised to the full §6 shape, all keys present."""
    rec = _recognize(tmp_path, 'import json; print(json.dumps({"matched": True}))')
    assert set(rec) == set(shazam._RECORD_KEYS)


# --- T-221: the widened tag payload (album/year/genre) rides the record --------

def test_widened_fields_round_trip(tmp_path):
    """A matched record carrying album/year/genre passes them through _normalise."""
    rec = _recognize(
        tmp_path,
        """
        import json, sys
        print(json.dumps({
            "shazam_artist": "Pa Salieu", "shazam_title": "Frontline",
            "album": "Send Them to Coventry", "year": 2020, "genre": "Hip-Hop/Rap",
            "matched": True,
        }))
        """,
    )
    assert rec["matched"] is True
    assert rec["album"] == "Send Them to Coventry"
    assert rec["year"] == 2020
    assert rec["genre"] == "Hip-Hop/Rap"


def test_widened_fields_are_none_on_a_non_vote(tmp_path):
    """A short/non-vote record normalises to album/year/genre = None (fail-soft)."""
    rec = _recognize(tmp_path, 'import json; print(json.dumps({"matched": False}))')
    assert rec["matched"] is False
    assert rec["album"] is None
    assert rec["year"] is None
    assert rec["genre"] is None


# --- Fail-soft: error / empty / garbage all become a non-vote ------------------

def test_runner_error_record_is_a_non_vote(tmp_path):
    rec = _recognize(
        tmp_path,
        'import json; print(json.dumps({"matched": False, "error": "NoMatchException: ..."}))',
    )
    assert rec["matched"] is False
    assert "NoMatch" in rec["error"]


def test_no_match_gets_a_default_error(tmp_path):
    """matched:false with no error still reports something, so it reads as a non-vote."""
    rec = _recognize(tmp_path, 'import json; print(json.dumps({"matched": False}))')
    assert rec["matched"] is False
    assert rec["error"]


def test_runner_crash_nonzero_exit_is_a_non_vote(tmp_path):
    """Runner itself failing to run (no JSON, exit 1) → non-vote, never an exception."""
    rec = _recognize(
        tmp_path,
        'import sys; sys.stderr.write("ModuleNotFoundError: shazamio\\n"); sys.exit(1)',
    )
    assert rec["matched"] is False
    assert "exit 1" in rec["error"]


def test_garbage_stdout_is_a_non_vote(tmp_path):
    rec = _recognize(tmp_path, 'print("not json at all")')
    assert rec["matched"] is False
    assert rec["error"] == "unparseable runner output"


def test_missing_interpreter_is_a_non_vote(tmp_path):
    rec = shazam.recognize(
        "audio.mp3",
        python_bin=tmp_path / "does-not-exist",
        runner_path=shazam.RUNNER_PATH,
    )
    assert rec["matched"] is False
    assert "unavailable" in rec["error"]


# --- Hard timeout: a hang is KILLED and returns within the cap -----------------

def test_hang_times_out_kills_child_and_returns_within_cap(tmp_path):
    """The load-bearing case: a hanging runner is killed, not waited on.

    The fake runner records its PID then sleeps far past the cap. `recognize` must
    (a) return `{matched:false, error:"timeout"}`, (b) well inside the wall clock,
    and (c) with the child process actually dead — otherwise, on the serial
    pipeline, it would block every later track.
    """
    pid_file = tmp_path / "pid"
    runner = _fake_runner(
        tmp_path,
        f"""
        import os, time
        open({str(pid_file)!r}, "w").write(str(os.getpid()))
        time.sleep(30)
        """,
    )
    # 2s cap (not a fraction of a second): the child must cold-start a fresh
    # interpreter and write its pid file before the kill, or the pid read below
    # races. Still an order of magnitude under the 30s sleep, so the timeout path
    # is what fires — proven by `elapsed` well below 30s.
    t0 = time.perf_counter()
    rec = shazam.recognize(
        "audio.mp3", python_bin=sys.executable, runner_path=runner, timeout_s=2.0
    )
    elapsed = time.perf_counter() - t0

    assert rec["matched"] is False
    assert rec["error"] == "timeout"
    # Returned within the cap (+ generous kill/reap margin), NOT after the 30s sleep.
    assert elapsed < 8, f"took {elapsed:.1f}s — worker was left blocked"

    child_pid = int(pid_file.read_text())
    assert not _pid_alive(child_pid), "child survived the timeout — not killed"


def _pid_alive(pid: int) -> bool:
    """True while the pid is a live, non-reaped process."""
    for _ in range(50):  # poll up to ~1s for the group SIGKILL to be reaped
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True  # exists but not ours (won't happen here) — count as alive
        time.sleep(0.02)
    return True


# --- Wiring sanity: defaults point at the isolated 3.12 venv + the runner ------

def test_defaults_point_at_the_isolated_venv_and_runner():
    assert shazam.SHAZAM_PYTHON.name == "python3.12"
    assert shazam.SHAZAM_PYTHON.parent.parent.name == ".venv-shazam"
    assert shazam.RUNNER_PATH.name == "shazam_runner.py"
