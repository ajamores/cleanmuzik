"""T-210: bound the MusicBrainz retry ladder (the tail-capping speed lever).

beets' MusicBrainz session (`LimiterTimeoutSession`) mounts a `RateLimitAdapter`
carrying `Retry(total=6, backoff_factor=0.5)`. On a slow or flaky MB endpoint that
ladder — up to six attempts with exponential backoff (~0.5 → 16s) — is what turns
one `get_recording` / `track_for_id` into the 18–34s (once 98s) spikes T-218
measured. The per-request socket timeout is already 10s, so the tail is the
*retries*, not an uncapped fetch (correcting the premise T-210 was filed on: there
is no missing timeout to add). Bound the ladder to a single retry and the deep
backoff tail collapses: the common 503-storm spike (backoff-dominated, ~30s of pure
sleep across six attempts) is gone, and only a rare genuinely-hung endpoint still
costs ~two socket timeouts (~20s, initial + one retry) rather than the ~30s+ ladder.
Everything else about the retry — the backoff
factor, the 5xx/429 status list, and the 0.25s adapter spacing — is preserved by
mutating the existing `Retry` via `Retry.new()`.

Both hot-path callers already degrade a lookup failure to a clean miss:
`_stamp_original_year` wraps `fetch_original_date` and lands without a year, and
beets' `maybe_handle_plugin_error` turns a raising `track_for_id` into `None`
(we never set `raise_on_error`). So a ladder that exhausts sooner surfaces as a
missing year or a dropped hydration — never a crash, never a stalled batch. The
candidate *search* was always exception-capable; bounding retries changes when it
gives up, not that it can. ADR-031.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# One retry after the initial attempt (beets' default is 6). Keeps a single
# absorb for a genuine transient 5xx/429 while killing the deep backoff ladder.
MB_RETRY_TOTAL = 1


def install_bounded_mb_retries(total: int = MB_RETRY_TOTAL) -> bool:
    """Bound the loaded MusicBrainz session's retry ladder to `total` retries.

    Idempotent (re-running on an already-bounded adapter is a no-op: `Retry.new`
    just re-stamps the same total). Mutates the adapter's `max_retries` in place so
    the pool, rate-limit clock, and lock survive untouched — only the retry count
    changes. Called from `configure_beets()` after `load_plugins()`; a missing
    plugin or an unexpected adapter shape is logged, not raised — the engine still
    runs, just with beets' default (slower-tailed) retry behaviour.
    """
    from beets import metadata_plugins

    plugin = metadata_plugins.get_metadata_source("musicbrainz")
    if plugin is None:
        logger.error("musicbrainz source not loaded — cannot bound MB retries")
        return False

    api = getattr(plugin, "mb_api", None)
    session = getattr(api, "session", None)
    if session is None:
        logger.error("musicbrainz plugin exposes no mb_api session — cannot bound MB retries")
        return False

    patched = 0
    seen: set[int] = set()
    # https:// and http:// share one adapter instance; de-dupe by identity so a
    # shared adapter is stamped once (and without hashing the adapter itself).
    for adapter in session.adapters.values():
        if id(adapter) in seen:
            continue
        seen.add(id(adapter))
        retry = getattr(adapter, "max_retries", None)
        if retry is None or not hasattr(retry, "new"):
            continue
        adapter.max_retries = retry.new(total=total)
        patched += 1

    if not patched:
        logger.error("MB session has no retryable adapter — retries left at beets' default")
        return False

    logger.debug("T-210: MB retry ladder bounded to total=%d (was beets' default 6)", total)
    return True
