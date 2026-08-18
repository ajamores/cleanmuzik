"""T-010 tests — the Jellyfin scan trigger.

Driven against a fake HTTP client (no live Jellyfin): the three contracts that
matter are the degrade path (missing config → False, no call, no raise), the
success path (correct endpoint + auth header, returns True), and the genuine
failure path (present config but the call fails → JellyfinScanError, so the caller
can name the `scan` stage).
"""

import logging

import pytest
import requests

from app.config import Settings
from app.jellyfin import JellyfinScanError, create_playlist, trigger_scan


def _settings(url: str = "http://jf.local:8096", key: str = "secret-key") -> Settings:
    return Settings(jellyfin_url=url, jellyfin_api_key=key)


class _Resp:
    def __init__(self, status: int = 204, body: object = None):
        self.status_code = status
        self._body = body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


# A single admin user, served for GET /Users so playlist ops can resolve a user id (T-311).
_ADMIN_USERS = [{"Id": "user-1", "Policy": {"IsAdministrator": True}}]


class _FakeHTTP:
    """Records POSTs and routes them through handler(url, kwargs) -> _Resp.

    GETs are only ever GET /Users here (the T-311 user-id lookup): by default it serves one
    admin user; pass `users_resp` to simulate a lookup failure. POSTs are recorded in `calls`;
    GET /Users is recorded separately in `users_calls`, so a create test's `len(calls) == 1`
    still counts just the create POST.
    """

    def __init__(self, handler, *, users_resp=None):
        self.handler = handler
        self.calls: list[tuple[str, dict]] = []
        self.users_calls: list[tuple[str, dict]] = []
        self._users_resp = users_resp if users_resp is not None else _Resp(200, _ADMIN_USERS)

    def get(self, url, **kwargs):
        assert "/Users" in url, f"unexpected GET in this fake: {url}"
        self.users_calls.append((url, kwargs))
        return self._users_resp

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.handler(url, kwargs)


def test_success_posts_to_refresh_endpoint_with_token():
    http = _FakeHTTP(lambda url, kw: _Resp(204))
    ok = trigger_scan(settings=_settings(), http=http)

    assert ok is True
    assert len(http.calls) == 1
    url, kwargs = http.calls[0]
    assert url == "http://jf.local:8096/Library/Refresh"
    assert kwargs["headers"]["X-Emby-Token"] == "secret-key"


def test_trailing_slash_on_url_is_normalized():
    http = _FakeHTTP(lambda url, kw: _Resp(204))
    trigger_scan(settings=_settings(url="http://jf.local:8096/"), http=http)
    assert http.calls[0][0] == "http://jf.local:8096/Library/Refresh"


@pytest.mark.parametrize(
    "override, expected_token",
    [
        ({"key": ""}, "JELLYFIN_API_KEY"),
        ({"url": ""}, "JELLYFIN_URL"),
        # Whitespace-only counts as absent — degrade, don't POST a bogus token.
        ({"key": "   "}, "JELLYFIN_API_KEY"),
        ({"url": "  "}, "JELLYFIN_URL"),
    ],
)
def test_absent_config_degrades_without_calling(override, expected_token, caplog):
    http = _FakeHTTP(lambda url, kw: pytest.fail("must not call Jellyfin without config"))
    with caplog.at_level(logging.WARNING, logger="cleanmuzik"):
        ok = trigger_scan(settings=_settings(**override), http=http)

    assert ok is False
    assert http.calls == []
    assert expected_token in caplog.text


def test_both_absent_names_both_vars(caplog):
    http = _FakeHTTP(lambda url, kw: pytest.fail("must not call Jellyfin without config"))
    with caplog.at_level(logging.WARNING, logger="cleanmuzik"):
        trigger_scan(settings=_settings(url="", key=""), http=http)

    assert "JELLYFIN_URL" in caplog.text
    assert "JELLYFIN_API_KEY" in caplog.text


def test_network_failure_raises_scan_error():
    def handler(url, kw):
        raise requests.ConnectionError("connection refused")

    with pytest.raises(JellyfinScanError):
        trigger_scan(settings=_settings(), http=_FakeHTTP(handler))


def test_http_error_status_raises_scan_error():
    # A present-but-stale key → Jellyfin answers 401; raise_for_status turns it into
    # an HTTPError, which is a genuine scan-stage failure, not a silent degrade.
    http = _FakeHTTP(lambda url, kw: _Resp(401))
    with pytest.raises(JellyfinScanError):
        trigger_scan(settings=_settings(), http=http)


# --- T-302: create_playlist — a create at expansion, degrade-never-raise ------
# The whole reason its contract diverges from trigger_scan: a create failure gates ALL N
# enqueues of a batch, so BOTH config-absent AND present-but-failed degrade to None (warn),
# never raise. A transient Jellyfin blip must not abort a 50-track paste.


def test_create_playlist_posts_and_returns_the_id():
    http = _FakeHTTP(lambda url, kw: _Resp(200, {"Id": "jf-playlist-1"}))
    playlist_id = create_playlist("Summer 2026", settings=_settings(), http=http)

    assert playlist_id == "jf-playlist-1"
    assert len(http.calls) == 1
    url, kwargs = http.calls[0]
    assert url == "http://jf.local:8096/Playlists"
    assert kwargs["headers"]["X-Emby-Token"] == "secret-key"
    assert kwargs["json"]["Name"] == "Summer 2026"
    assert kwargs["json"]["UserId"] == "user-1"  # T-311: playlists belong to a user


def test_create_playlist_degrades_to_none_when_no_user_id(caplog):
    """T-311: create needs a user id to own the playlist; if /Users can't resolve one, degrade
    to None (never raise) — same whole-batch rationale as any other create failure."""
    http = _FakeHTTP(
        lambda url, kw: pytest.fail("must not POST a playlist without a user id"),
        users_resp=_Resp(200, []),  # no users returned
    )
    with caplog.at_level(logging.WARNING, logger="cleanmuzik"):
        result = create_playlist("Mix", settings=_settings(), http=http)
    assert result is None
    assert http.calls == []  # never reached the create POST


@pytest.mark.parametrize(
    "override, expected_var",
    [({"key": ""}, "JELLYFIN_API_KEY"), ({"url": ""}, "JELLYFIN_URL"), ({"key": "  "}, "JELLYFIN_API_KEY")],
)
def test_create_playlist_absent_config_degrades_to_none(override, expected_var, caplog):
    http = _FakeHTTP(lambda url, kw: pytest.fail("must not call Jellyfin without config"))
    with caplog.at_level(logging.WARNING, logger="cleanmuzik"):
        result = create_playlist("Mix", settings=_settings(**override), http=http)

    assert result is None
    assert http.calls == []
    assert expected_var in caplog.text


def test_create_playlist_network_failure_degrades_to_none_not_raises(caplog):
    # THE divergence from trigger_scan: a present-but-failed create does NOT raise.
    def handler(url, kw):
        raise requests.ConnectionError("connection refused")

    with caplog.at_level(logging.WARNING, logger="cleanmuzik"):
        result = create_playlist("Mix", settings=_settings(), http=_FakeHTTP(handler))

    assert result is None
    assert "failed" in caplog.text.lower()


def test_create_playlist_http_error_degrades_to_none(caplog):
    http = _FakeHTTP(lambda url, kw: _Resp(500))
    with caplog.at_level(logging.WARNING, logger="cleanmuzik"):
        result = create_playlist("Mix", settings=_settings(), http=http)
    assert result is None


def test_create_playlist_non_json_body_degrades_to_none():
    # A 2xx with an unparseable body (requests raises a ValueError subclass on .json()).
    http = _FakeHTTP(lambda url, kw: _Resp(200, ValueError("no json")))
    assert create_playlist("Mix", settings=_settings(), http=http) is None


def test_create_playlist_missing_id_in_body_degrades_to_none(caplog):
    http = _FakeHTTP(lambda url, kw: _Resp(200, {"NotAnId": "x"}))
    with caplog.at_level(logging.WARNING, logger="cleanmuzik"):
        result = create_playlist("Mix", settings=_settings(), http=http)
    assert result is None
