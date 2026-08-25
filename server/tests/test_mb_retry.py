"""T-210 tests — the bounded MusicBrainz retry ladder, offline.

The speed lever is a single mutation: beets' MB session adapter carries a
`Retry(total=6, backoff_factor=0.5)`, and that deep ladder — not an uncapped
socket (the timeout is already 10s) — is the 18–34s identify tail. These tests pin
that the bound lands (6 → 1) through the real engine, that everything else about
the retry survives it, and that the patch degrades quietly rather than raising when
the plugin or adapter isn't shaped as expected.
"""

from types import SimpleNamespace

import pytest

from app.mb_retry import MB_RETRY_TOTAL, install_bounded_mb_retries


@pytest.fixture(scope="module")
def mb_session():
    """The live MusicBrainz session after the real configure path has run."""
    from beets import metadata_plugins

    from app.beets_engine import configure_beets

    configure_beets()
    plugin = metadata_plugins.get_metadata_source("musicbrainz")
    assert plugin is not None
    return plugin.mb_api.session


# --- the live effect ---------------------------------------------------------


def test_configure_beets_bounds_the_ladder(mb_session):
    """configure_beets() leaves the MB adapter at one retry, not beets' six."""
    adapter = mb_session.get_adapter("https://musicbrainz.org/ws/2/recording/x")
    assert adapter.max_retries.total == MB_RETRY_TOTAL == 1


def test_bound_preserves_backoff_rate_and_status_list(mb_session):
    """Only the retry *count* changes — backoff, spacing, and the 5xx/429 list stay."""
    adapter = mb_session.get_adapter("https://musicbrainz.org/ws/2/recording/x")
    retry = adapter.max_retries
    assert retry.backoff_factor == 0.5
    assert adapter.rate_limit == 0.25
    assert {int(s) for s in retry.status_forcelist} == {500, 502, 503, 504, 429}


def test_both_schemes_bounded(mb_session):
    """https and http share the one adapter, so both are capped."""
    https = mb_session.get_adapter("https://musicbrainz.org")
    http = mb_session.get_adapter("http://musicbrainz.org")
    assert https.max_retries.total == 1
    assert http.max_retries.total == 1


def test_idempotent(mb_session):
    """Re-running the patch keeps the bound — it never re-inflates the ladder."""
    assert install_bounded_mb_retries() is True
    adapter = mb_session.get_adapter("https://musicbrainz.org/ws/2/recording/x")
    assert adapter.max_retries.total == 1


def test_custom_total(mb_session):
    """The bound is a parameter; callers can pick a different ceiling.

    The MB session is a process-wide singleton, so the try/finally restore is
    load-bearing: without it a later assertion failure here would leave every
    subsequent test running against total=3.
    """
    try:
        assert install_bounded_mb_retries(total=3) is True
        adapter = mb_session.get_adapter("https://musicbrainz.org/ws/2/recording/x")
        assert adapter.max_retries.total == 3
    finally:
        # restore the module default so later tests/other modules see the real bound
        assert install_bounded_mb_retries() is True
    assert mb_session.get_adapter(
        "https://musicbrainz.org/ws/2/recording/x"
    ).max_retries.total == MB_RETRY_TOTAL


# --- degrades quietly, never raises ------------------------------------------


def test_missing_plugin_returns_false(monkeypatch):
    """No musicbrainz source loaded → logged, False, no raise (engine still runs)."""
    from beets import metadata_plugins

    monkeypatch.setattr(metadata_plugins, "get_metadata_source", lambda name: None)
    assert install_bounded_mb_retries() is False


def test_session_without_retryable_adapter_returns_false(monkeypatch):
    """An adapter carrying no urllib3 Retry is skipped, not stamped — returns False."""
    from beets import metadata_plugins

    # An adapter with no `max_retries` at all — nothing to bound.
    fake_session = SimpleNamespace(adapters={"https://": SimpleNamespace()})
    fake_plugin = SimpleNamespace(mb_api=SimpleNamespace(session=fake_session))
    monkeypatch.setattr(
        metadata_plugins, "get_metadata_source", lambda name: fake_plugin
    )
    assert install_bounded_mb_retries() is False


def test_no_mb_api_returns_false(monkeypatch):
    """A plugin missing its mb_api session is handled, not crashed."""
    from beets import metadata_plugins

    fake_plugin = SimpleNamespace(mb_api=None)
    monkeypatch.setattr(
        metadata_plugins, "get_metadata_source", lambda name: fake_plugin
    )
    assert install_bounded_mb_retries() is False
