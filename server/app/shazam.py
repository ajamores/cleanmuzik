"""Shazam sense (sense 3) — one recognition per track, behind a killable subprocess.

R1.5 gathers three senses for identity reconciliation (spec §2). This is the
Shazam one. The app runs on Python 3.14, which has **no `shazamio-core` wheel**,
so the recognition cannot run in-process; it runs in the isolated 3.12 venv
`server/.venv-shazam` and is reached by spawning `shazam_runner.py` with that
interpreter (the contract lives in that file's docstring + here). ADR-024 records
why the boundary is a subprocess and why Shazam now runs on *every* track.

Two properties this module owns (ticket T-202, spec §5):

1. **Hard wall-clock timeout (default 8s, tunable).** A hang is *not* "Shazam
   unavailable" — on the serial pipeline an un-killed hang blocks every later
   track (exp 8 saw ~28s tail spikes). On timeout the child **process group is
   SIGKILLed** and the call returns `{matched: False, error: "timeout"}` within
   the cap, so the worker thread is never left blocked.
2. **Fail-soft, always a full §6 record.** Any error / empty / timeout ⇒
   `matched: False` — a *non-vote*. Shazam is never written as a tag on its own
   authority (that is enforced downstream at the 2-of-3 gate, T-205); here we
   only guarantee the record shape and that no failure escapes as an exception.

`art_url` / `lyrics` ride in the record for the record's sake only — R1.5 writes
neither (spec §3; art/lyrics land via the existing beets path).
"""

import json
import logging
import os
import signal
import subprocess
from pathlib import Path

from app.config import SERVER_DIR, get_settings

logger = logging.getLogger("cleanmuzik")

# The isolated 3.12 interpreter that carries the shazamio-core wheel, and the
# standalone runner it executes. The runner is spawned as a *file path*, never
# imported (the 3.12 venv has no `app` package). `SERVER_DIR` is reused from
# config so the venv root has a single anchor.
SHAZAM_PYTHON = SERVER_DIR / ".venv-shazam" / "bin" / "python3.12"
RUNNER_PATH = Path(__file__).resolve().parent / "shazam_runner.py"

_RECORD_KEYS = (
    "shazam_artist",
    "shazam_title",
    "isrc",
    "art_url",
    "lyrics",
    "matched",
    "error",
)


def _non_vote(error: str) -> dict:
    """A full §6 record that counts as absent (matched:False) — never raises."""
    return {
        "shazam_artist": None,
        "shazam_title": None,
        "isrc": None,
        "art_url": None,
        "lyrics": None,
        "matched": False,
        "error": error,
    }


def _normalise(record: dict) -> dict:
    """Coerce a runner record to the exact §6 shape (all keys present, bool matched).

    A malformed/short record from the child is treated as a non-vote so that a
    Shazam quirk can never fabricate a match or drop a required key.
    """
    if not isinstance(record, dict):
        return _non_vote("malformed record")
    out = {key: record.get(key) for key in _RECORD_KEYS}
    out["matched"] = bool(out["matched"])
    if not out["matched"] and out["error"] is None:
        out["error"] = "no match"
    return out


def _kill_group(proc: subprocess.Popen) -> None:
    """SIGKILL the child's whole process group, so nothing it spawned survives."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        try:
            proc.kill()
        except ProcessLookupError:
            pass


def recognize(
    audio_path,
    *,
    timeout_s: float | None = None,
    python_bin=None,
    runner_path=None,
) -> dict:
    """Recognise one track via Shazam, returning the spec §6 record. Never raises.

    Injectable (`python_bin` / `runner_path` / `timeout_s`) so tests can drive the
    real subprocess + timeout-kill machinery against a fake runner, offline.
    """
    timeout_s = get_settings().shazam_timeout_s if timeout_s is None else timeout_s
    python_bin = Path(python_bin) if python_bin else SHAZAM_PYTHON
    runner_path = Path(runner_path) if runner_path else RUNNER_PATH

    # A missing interpreter/runner is "unavailable", not a hang — a plain non-vote,
    # logged once so a mis-provisioned box is visible rather than silent.
    if not python_bin.exists():
        logger.warning("shazam interpreter missing at %s — sense unavailable", python_bin)
        return _non_vote("shazam interpreter unavailable")
    if not runner_path.exists():
        logger.warning("shazam runner missing at %s — sense unavailable", runner_path)
        return _non_vote("shazam runner unavailable")

    try:
        proc = subprocess.Popen(
            [str(python_bin), str(runner_path), str(audio_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            # New session ⇒ the child leads its own process group, so a timeout
            # kill (killpg) takes down anything shazamio spawned, not just the
            # direct child.
            start_new_session=True,
        )
    except OSError as exc:  # spawn itself failed — treat as unavailable, don't crash
        logger.warning("shazam subprocess failed to start: %s", exc)
        return _non_vote(f"spawn failed: {exc}")

    try:
        out, err = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        # A hang: KILL the group and reap, then report timeout within the cap.
        _kill_group(proc)
        try:
            proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            pass  # reaped best-effort; the group already got SIGKILL
        logger.warning("shazam recognition timed out after %ss — killed", timeout_s)
        return _non_vote("timeout")

    if proc.returncode != 0:
        # The runner itself failed to run (e.g. shazamio import error) — non-vote.
        tail = (err or "").strip().splitlines()[-1:] or [""]
        return _non_vote(f"exit {proc.returncode}: {tail[0]}"[:200])

    # The runner prints the §6 record as its LAST stdout line. shazamio's audio
    # stack (a reverse-engineered Rust ext + ffmpeg) can write decode noise to
    # stdout ahead of it, so parse the last non-empty line, not the whole stream.
    lines = [ln for ln in (out or "").splitlines() if ln.strip()]
    if not lines:
        return _non_vote("empty runner output")
    try:
        record = json.loads(lines[-1])
    except (ValueError, TypeError):
        return _non_vote("unparseable runner output")
    return _normalise(record)
