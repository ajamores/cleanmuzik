"""The direct-HTTP MusicBrainz client + shared rate limiter (T-226 step C, `app/mb_client.py`)."""

import json
from pathlib import Path

import pytest

import app.import_seam as seam
from app import mb_client

_FIXTURE = Path(__file__).parent / "fixtures" / "mb_recording_bohemian_rhapsody.json"


@pytest.fixture(autouse=True)
def _reset_rate_gate():
    mb_client._last_request_monotonic = None
    yield
    mb_client._last_request_monotonic = None


class _Resp:
    def __init__(self, status_code=200, data=None, raise_json=False):
        self.status_code = status_code
        self._data = data
        self._raise_json = raise_json

    def json(self):
        if self._raise_json:
            raise ValueError("bad body")
        return self._data


class _FakeHTTP:
    def __init__(self, resp=None, exc=None):
        self._resp = resp
        self._exc = exc
        self.calls = []

    def get(self, url, **kw):
        self.calls.append((url, kw))
        if self._exc:
            raise self._exc
        return self._resp


class _SeqHTTP:
    """Returns a queued sequence of responses/exceptions across successive `get` calls."""

    def __init__(self, *outcomes):
        self._outcomes = list(outcomes)
        self.calls = []

    def get(self, url, **kw):
        self.calls.append((url, kw))
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


# A clock/sleep pair that never really sleeps: sleeping advances the fake clock.
class _Clock:
    def __init__(self):
        self.t = 1000.0
        self.slept = []

    def now(self):
        return self.t

    def sleep(self, secs):
        self.slept.append(secs)
        self.t += secs


class TestParseDate:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("1975-10-31", (1975, 10, 31)),
            ("1975-10", (1975, 10, None)),
            ("1975", (1975, None, None)),
            ("", (None, None, None)),
            (None, (None, None, None)),
            ("not-a-date", (None, None, None)),
        ],
    )
    def test_parse(self, raw, expected):
        assert mb_client.parse_date(raw) == expected


class TestGetRecording:
    def test_returns_raw_json_on_200(self):
        http = _FakeHTTP(resp=_Resp(200, {"id": "rec-A", "first-release-date": "1975"}))
        clock = _Clock()
        out = mb_client.get_recording(
            "rec-A", includes=["releases"], http=http, clock_fn=clock.now, sleep_fn=clock.sleep
        )
        assert out == {"id": "rec-A", "first-release-date": "1975"}
        # `inc` is the space-joined includes, `fmt=json`.
        assert http.calls[0][1]["params"] == {"fmt": "json", "inc": "releases"}

    def test_empty_id_returns_none_without_a_request(self):
        http = _FakeHTTP(resp=_Resp(200, {}))
        assert mb_client.get_recording("", http=http) is None
        assert mb_client.get_recording(None, http=http) is None
        assert http.calls == []

    def test_non_200_is_fail_soft(self):
        http = _FakeHTTP(resp=_Resp(503, None))
        clock = _Clock()
        assert mb_client.get_recording("rec-A", http=http, clock_fn=clock.now, sleep_fn=clock.sleep) is None

    def test_request_exception_is_fail_soft(self):
        http = _FakeHTTP(exc=RuntimeError("boom"))
        clock = _Clock()
        assert mb_client.get_recording("rec-A", http=http, clock_fn=clock.now, sleep_fn=clock.sleep) is None

    def test_unparseable_body_is_fail_soft(self):
        http = _FakeHTTP(resp=_Resp(200, None, raise_json=True))
        clock = _Clock()
        assert mb_client.get_recording("rec-A", http=http, clock_fn=clock.now, sleep_fn=clock.sleep) is None

    def test_non_dict_body_is_fail_soft(self):
        http = _FakeHTTP(resp=_Resp(200, ["not", "a", "dict"]))
        clock = _Clock()
        assert mb_client.get_recording("rec-A", http=http, clock_fn=clock.now, sleep_fn=clock.sleep) is None


class TestRetry:
    def test_transient_503_then_200_succeeds(self):
        # MB answers 503 under load (seen live) — one retry absorbs it (beets-ladder parity).
        http = _SeqHTTP(_Resp(503, None), _Resp(200, {"id": "rec-A"}))
        clock = _Clock()
        out = mb_client.get_recording("rec-A", http=http, clock_fn=clock.now, sleep_fn=clock.sleep)
        assert out == {"id": "rec-A"}
        assert len(http.calls) == 2

    def test_exception_then_200_succeeds(self):
        http = _SeqHTTP(RuntimeError("reset"), _Resp(200, {"id": "rec-A"}))
        clock = _Clock()
        assert mb_client.get_recording("rec-A", http=http, clock_fn=clock.now, sleep_fn=clock.sleep) == {"id": "rec-A"}

    def test_two_transient_failures_give_up(self):
        http = _SeqHTTP(_Resp(503, None), _Resp(503, None))
        clock = _Clock()
        assert mb_client.get_recording("rec-A", http=http, clock_fn=clock.now, sleep_fn=clock.sleep) is None
        assert len(http.calls) == 2  # bounded — never a third attempt

    def test_404_is_not_retried(self):
        # A 404 is a real answer (unknown recording), not transient — no retry.
        http = _SeqHTTP(_Resp(404, None), _Resp(200, {"id": "should-not-be-reached"}))
        clock = _Clock()
        assert mb_client.get_recording("rec-A", http=http, clock_fn=clock.now, sleep_fn=clock.sleep) is None
        assert len(http.calls) == 1


class TestRealFixtureShape:
    """Guards the raw MB WS/2 recording shape `fetch_original_date` reads, against a CAPTURED
    real response (like isrc.py's fixture) — not just hand-authored dicts. If MB's nesting
    ever shifts, this trips instead of silently degrading the year to recording-level only."""

    def test_fetch_original_date_reads_the_real_nesting(self, monkeypatch):
        data = json.loads(_FIXTURE.read_text())
        # The real response nests release-group.first-release-date inside each release.
        assert "first-release-date" in data
        assert "release-group" in (data["releases"][0])
        monkeypatch.setattr(seam.mb_client, "get_recording", lambda _rid, includes=None: data)
        # Bohemian Rhapsody's 1975 recording — the authoritative first-release-date.
        assert seam.fetch_original_date("rec-A") == (1975, 11, 21)


class TestSharedLimiter:
    def test_second_call_within_a_second_waits(self):
        clock = _Clock()
        mb_client.respect_rate_limit(clock.now, clock.sleep)  # first: no wait
        assert clock.slept == []
        mb_client.respect_rate_limit(clock.now, clock.sleep)  # immediate second: waits ~1s
        assert clock.slept and clock.slept[0] == pytest.approx(1.0)

    def test_isrc_and_recording_share_the_gate(self):
        # The T-210 correctness half: a recording lookup and an ISRC lookup must not both
        # fire inside one second — they now share this module's gate.
        from app import isrc

        clock = _Clock()
        mb_client.get_recording(
            "rec-A", http=_FakeHTTP(resp=_Resp(200, {})), clock_fn=clock.now, sleep_fn=clock.sleep
        )
        isrc.isrc_to_mb(
            "GBAHT1901215",
            http=_FakeHTTP(resp=_Resp(200, {"recordings": []})),
            clock_fn=clock.now,
            sleep_fn=clock.sleep,
        )
        # The ISRC call saw the recording call's timestamp and threw a wait.
        assert clock.slept and clock.slept[0] == pytest.approx(1.0)
