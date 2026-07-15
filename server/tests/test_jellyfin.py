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
from app.jellyfin import JellyfinScanError, trigger_scan


def _settings(url: str = "http://jf.local:8096", key: str = "secret-key") -> Settings:
    return Settings(jellyfin_url=url, jellyfin_api_key=key)


class _Resp:
    def __init__(self, status: int = 204):
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


class _FakeHTTP:
    """Records POSTs and routes them through handler(url, kwargs) -> _Resp."""

    def __init__(self, handler):
        self.handler = handler
        self.calls: list[tuple[str, dict]] = []

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
