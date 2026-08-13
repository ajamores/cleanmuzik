#!/usr/bin/env python3
"""Is our pinned yt-dlp behind the latest stable? — an on-demand check.

Version age is a bad proxy for "up to date": yt-dlp can sit five weeks old and
still be the newest stable, or be days old and already behind a YouTube-breaking
fix. The only honest signal is a comparison against PyPI, which is what this does.

Run it whenever a download 403s repeatedly, or just periodically:

    ./.venv/bin/python scripts/check-ytdlp.py

Prints the installed version, the latest STABLE on PyPI (dev/nightly builds are
ignored — we don't run those on the everyday tool), and whether a bump exists.
Exit 0 = current (or offline), 1 = a newer stable is out. Stdlib only, so it needs
no extra install and never touches the pipeline or the DB.

When it says a bump is available: edit the `yt-dlp==` pin in `requirements.txt`,
re-run `uv pip install --python .venv/bin/python -r requirements.txt`, restart
uvicorn, and re-verify one real download (the requirements.txt comment's rule).
"""

import json
import sys
import urllib.request
from importlib import metadata


def _installed() -> str:
    return metadata.version("yt-dlp")


def _latest_stable() -> str:
    """The newest non-prerelease on PyPI. `info.version` is PyPI's own 'latest
    stable' pick, which already excludes `.devN` builds — exactly our channel."""
    with urllib.request.urlopen("https://pypi.org/pypi/yt-dlp/json", timeout=10) as r:
        return json.load(r)["info"]["version"]


def _as_tuple(v: str) -> tuple[int, ...]:
    """yt-dlp versions are date-based (`2026.7.4`) — numeric, dot-split, so a plain
    tuple compare orders them correctly without a packaging dependency."""
    return tuple(int(p) for p in v.split(".") if p.isdigit())


def main() -> int:
    installed = _installed()
    try:
        latest = _latest_stable()
    except Exception as exc:  # offline / PyPI down — a check that can't run isn't a failure
        print(f"yt-dlp {installed} installed — could not reach PyPI to compare ({exc})")
        return 0

    if _as_tuple(latest) > _as_tuple(installed):
        print(f"yt-dlp is BEHIND: installed {installed}, latest stable {latest}.")
        print(f"  Bump the pin in requirements.txt to  yt-dlp=={latest}  and reinstall.")
        return 1

    print(f"yt-dlp {installed} is up to date (latest stable {latest}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
