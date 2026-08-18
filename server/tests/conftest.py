"""Shared pytest fixtures for the server suite."""

import pytest

from app.jellyfin import _clear_user_id_cache


@pytest.fixture(autouse=True)
def _reset_jellyfin_user_id_cache():
    """Clear the memoised Jellyfin user id before every test (T-311).

    `resolve_user_id` caches per (url, key) so a batch's many appends don't each re-hit
    GET /Users. Tests reuse constant fake hosts, so without this a user id resolved in one
    test would leak into the next and mask a test that means to exercise a /Users failure.
    """
    _clear_user_id_cache()
    yield
    _clear_user_id_cache()
