"""Shared pytest fixtures for the server suite."""

import pytest

from app.jellyfin import _clear_user_id_cache


@pytest.fixture(autouse=True)
def isolated_library(tmp_path, monkeypatch):
    """Point the T-226 library-scan dedup at an empty temp dir for every test.

    The dedup is now a filesystem walk of `LIBRARY_DIRECTORY` (was an isolated beets-DB
    query). Without this, any test that reaches `_accept` / `_duplicate_detail` would walk
    the owner's REAL `/mnt/c` music library — slow (drvfs) and a live-data read the `/verify`
    playbook explicitly forbids. Isolating the root here mirrors how `DB_PATH` is isolated,
    and gives dedup tests a clean directory to plant real files in (request this fixture by
    name to get the path).
    """
    library_dir = tmp_path / "library"
    library_dir.mkdir()
    monkeypatch.setattr("app.import_seam.LIBRARY_DIRECTORY", str(library_dir))
    return library_dir


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
