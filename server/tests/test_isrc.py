"""T-203 tests — ISRC → MusicBrainz fact lookup.

Offline by construction: `isrc_to_mb` takes an injectable `http` client, so the resolve
case runs against a **captured** real MusicBrainz response (`tests/fixtures/
isrc_GBAHT1901215.json`, the Pa Salieu "Frontline" marquee correction), and the throttle
is exercised with an injected clock/sleep so no test waits a real second.

What each test pins:
  - a real ISRC resolves to the real recording MBID + artist + title from the fixture;
  - a multi-artist credit is joined into MusicBrainz's own as-credited phrase;
  - an unresolvable (HTTP 404) ISRC, an empty-recordings body, a network error, and a
    blank ISRC all return None (fail-soft, "no ISRC entry");
  - every request carries a User-Agent and the fmt/inc query params;
  - two calls in quick succession are spaced ≥ 1s by the throttle (ADR-001, 1/sec).
"""

import json
from pathlib import Path

import pytest
import requests

import app.isrc as isrc_mod
from app.isrc import ISRCRecording, isrc_to_mb

FIXTURE = Path(__file__).parent / "fixtures" / "isrc_GBAHT1901215.json"


class _Resp:
    def __init__(self, status=200, json_data=None):
        self.status_code = status
        self._json = json_data

    def json(self):
        if self._json is None:
            raise ValueError("no json body")
        return self._json


class _FakeHTTP:
    """A requests-shaped client that records calls and returns a canned/handler response."""

    def __init__(self, resp=None, handler=None, exc=None):
        self._resp = resp
        self._handler = handler
        self._exc = exc
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self._exc is not None:
            raise self._exc
        if self._handler is not None:
            return self._handler(url, kwargs)
        return self._resp


@pytest.fixture(autouse=True)
def _reset_rate_gate():
    """Each test starts from a clean throttle — the gate is module-level global state."""
    isrc_mod._last_request_monotonic = None
    yield
    isrc_mod._last_request_monotonic = None


# A clock/sleep pair that never really sleeps: sleeping advances the fake clock instead.
def _fake_clock():
    t = {"now": 1000.0}

    def clock():
        return t["now"]

    def sleep(seconds):
        t["now"] += seconds

    return clock, sleep, t


def _no_sleep():
    clock, sleep, _ = _fake_clock()
    return clock, sleep


# --- the resolve case, against the CAPTURED real MusicBrainz response ------------------


def test_real_isrc_resolves_to_real_recording_from_captured_fixture():
    data = json.loads(FIXTURE.read_text())
    clock, sleep = _no_sleep()
    http = _FakeHTTP(resp=_Resp(200, data))

    result = isrc_to_mb("GBAHT1901215", http=http, clock_fn=clock, sleep_fn=sleep)

    assert result == ISRCRecording(
        mbid="6d6dd1f3-4c06-434d-8179-653a29e141f5",
        artist="Pa Salieu",
        title="Frontline",
    )


def test_request_sets_user_agent_and_query_params():
    data = json.loads(FIXTURE.read_text())
    clock, sleep = _no_sleep()
    http = _FakeHTTP(resp=_Resp(200, data))

    isrc_to_mb("GBAHT1901215", http=http, clock_fn=clock, sleep_fn=sleep)

    url, kwargs = http.calls[0]
    assert "musicbrainz.org/ws/2/isrc/GBAHT1901215" in url
    assert kwargs["headers"]["User-Agent"]  # required, non-empty
    assert kwargs["params"] == {"fmt": "json", "inc": "artist-credits"}


def test_multi_artist_credit_is_joined_into_musicbrainz_phrase():
    # A constructed multi-credit body (the captured fixture is single-artist) — exercises
    # the join-phrase path with the exact shape MusicBrainz returns.
    data = {
        "isrc": "USUM71234567",
        "recordings": [
            {
                "id": "abc-123",
                "title": "Some Song",
                "artist-credit": [
                    {"name": "Artist A", "joinphrase": " feat. ", "artist": {}},
                    {"name": "Artist B", "joinphrase": "", "artist": {}},
                ],
            }
        ],
    }
    clock, sleep = _no_sleep()
    result = isrc_to_mb("USUM71234567", http=_FakeHTTP(resp=_Resp(200, data)), clock_fn=clock, sleep_fn=sleep)
    assert result == ISRCRecording(mbid="abc-123", artist="Artist A feat. Artist B", title="Some Song")


# --- the None cases: unresolvable / garbage / fail-soft --------------------------------


def test_unresolvable_isrc_returns_none_on_404():
    # A well-formed but unknown ISRC → real HTTP 404 (captured live behaviour).
    body = {"help": "https://musicbrainz.org/development/mmd", "error": "Not Found"}
    clock, sleep = _no_sleep()
    result = isrc_to_mb("ZZZZZ9999999", http=_FakeHTTP(resp=_Resp(404, body)), clock_fn=clock, sleep_fn=sleep)
    assert result is None


def test_empty_recordings_returns_none():
    clock, sleep = _no_sleep()
    result = isrc_to_mb("GB0000000000", http=_FakeHTTP(resp=_Resp(200, {"recordings": []})), clock_fn=clock, sleep_fn=sleep)
    assert result is None


def test_recording_missing_mbid_or_title_returns_none():
    clock, sleep = _no_sleep()
    data = {"recordings": [{"title": "No Id", "artist-credit": [{"name": "X"}]}]}
    assert isrc_to_mb("GB1111111111", http=_FakeHTTP(resp=_Resp(200, data)), clock_fn=clock, sleep_fn=sleep) is None


def test_network_error_returns_none():
    clock, sleep = _no_sleep()
    http = _FakeHTTP(exc=requests.ConnectionError("boom"))
    assert isrc_to_mb("GBAHT1901215", http=http, clock_fn=clock, sleep_fn=sleep) is None


def test_unparseable_body_returns_none():
    clock, sleep = _no_sleep()
    # _Resp with no json_data raises ValueError from .json()
    assert isrc_to_mb("GBAHT1901215", http=_FakeHTTP(resp=_Resp(200, None)), clock_fn=clock, sleep_fn=sleep) is None


@pytest.mark.parametrize("bad", ["", "   ", None])
def test_blank_isrc_returns_none_without_calling_http(bad):
    http = _FakeHTTP(resp=_Resp(200, {}))
    clock, sleep = _no_sleep()
    assert isrc_to_mb(bad, http=http, clock_fn=clock, sleep_fn=sleep) is None
    assert http.calls == []  # never touched the network


# --- the 1/sec floor (ADR-001) ---------------------------------------------------------


def test_throttle_spaces_calls_at_least_one_second_apart():
    data = json.loads(FIXTURE.read_text())
    clock, sleep, state = _fake_clock()
    slept = []

    def recording_sleep(seconds):
        slept.append(seconds)
        state["now"] += seconds

    http = _FakeHTTP(resp=_Resp(200, data))
    # First call: nothing to wait for.
    isrc_to_mb("GBAHT1901215", http=http, clock_fn=clock, sleep_fn=recording_sleep)
    assert slept == []
    # Second call immediately after (fake clock hasn't advanced): must wait ~1s.
    isrc_to_mb("GBAHT1901215", http=http, clock_fn=clock, sleep_fn=recording_sleep)
    assert slept and slept[0] == pytest.approx(1.0)


def test_throttle_does_not_wait_when_interval_already_elapsed():
    data = json.loads(FIXTURE.read_text())
    clock, sleep, state = _fake_clock()
    slept = []

    def recording_sleep(seconds):
        slept.append(seconds)
        state["now"] += seconds

    http = _FakeHTTP(resp=_Resp(200, data))
    isrc_to_mb("GBAHT1901215", http=http, clock_fn=clock, sleep_fn=recording_sleep)
    state["now"] += 2.0  # more than the interval passes on its own
    isrc_to_mb("GBAHT1901215", http=http, clock_fn=clock, sleep_fn=recording_sleep)
    assert slept == []
