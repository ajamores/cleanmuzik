"""Plain-Python library path computation — the mover, minus beets (T-226 step A).

Until T-226 the copy-into-library step rode entirely inside beets'
`ImportSession.run()`: `Item.destination()` evaluated the `$artist/$title` template,
`util.sanitize_path` legalized it against the default replacement map, `util.legalize_path`
truncated over-long components, and `util.unique_path` appended a `.N` on a collision.
None of it was ever called by this repo directly, and none of it was re-implemented or
asserted here — it was inherited from beets defaults.

This module reproduces that behaviour byte-faithfully for the one template that actually
fires on our path — the **singleton** `$artist/$title` (R1 imports every track as a
singleton, so `%aunique` and the album templates are dead). It is the single home for:

  * the six-rule NTFS/WSL character sanitizer (beets' default `replace` map),
  * NFC normalization (load-bearing on the `/mnt/c` drvfs mount — an NFD filename the
    Windows side stores as NFC reads back as a different byte string and Jellyfin's scan
    misses it, the NOT_INDEXED trap of learnings 2026-08-21),
  * 200-**byte** (not char) per-component truncation, preserving the extension,
  * the `.N`-on-collision disambiguator (`Title.1.mp3`), the real upgrade-path reclaim
    mechanism — NOT `%aunique`.

`destination()` is the whole public surface. It takes the applied identity's artist +
title and returns the absolute path the file should land at, collision-suffixed. Pure but
for the injected `exists` probe (defaulted to `os.path.exists`, overridable in tests).
"""

from __future__ import annotations

import os
import re
import sys
import unicodedata
from collections.abc import Callable

# The Jellyfin watched-folder root beets organized into (was `beets_engine.LIBRARY_DIRECTORY`).
# Kept here so the mover owns its own root once beets is gone; the WSL path for the Windows
# `C:\Users\aj_am\Music\CleanMuzik`.
LIBRARY_DIRECTORY = "/mnt/c/Users/aj_am/Music/CleanMuzik"

# beets 2.12's default `replace` map, verbatim (config.read(user=False) → config['replace']).
# Order matters — each rule runs in turn over every path component. Reproduced here so
# removing beets does not silently drop NTFS legalization (the `<>:"\/|?*` set Windows
# forbids, control chars, leading dots/dashes, surrounding whitespace).
_CHAR_REPLACE: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r'[<>:"\?\*\|]'), "_"),
    (re.compile(r'\"'), "_"),
    (re.compile(r"[\\/]"), "_"),
    (re.compile(r"^\."), "_"),
    (re.compile(r"\.$"), "_"),
    (re.compile(r"[\x00-\x1f]"), "_"),
    (re.compile(r"^-"), "_"),
    (re.compile(r"\s+$"), ""),
    (re.compile(r"^\s+"), ""),
]

# beets' MAX_FILENAME_LENGTH default. On a drvfs `/mnt/c` mount `os.statvfs().f_namemax`
# reports 255, and beets takes `min(f_namemax, 200)` = 200, so 200 bytes is the live cap.
_MAX_COMPONENT_BYTES = 200

_FS_ENCODING = os.fsencode  # component truncation is in bytes, per beets truncate_str


def _sanitize_component(comp: str) -> str:
    """Apply the six-rule replacement map to a single path component (beets sanitize_path)."""
    for regex, repl in _CHAR_REPLACE:
        comp = regex.sub(repl, comp)
    return comp


def _truncate_component(comp: str, limit: int) -> str:
    """Truncate a component to `limit` bytes, dropping a half-cut multibyte char (truncate_str)."""
    return _FS_ENCODING(comp)[:limit].decode(sys.getfilesystemencoding(), "ignore")


def unique_path(path: str, exists: Callable[[str], bool] = os.path.exists) -> str:
    """A version of `path` that does not exist: append/increment a `.N` before the extension.

    Faithful to beets' `util.unique_path` — `Title.mp3` → `Title.1.mp3` → `Title.2.mp3` …,
    and an existing `Title.1.mp3` re-uniquifies from its own number. The upgrade-path reclaim
    (T-009/T-014) relies on this exact shape (`test_reviews.py` asserts `Title.1.mp3`).
    """
    if not exists(path):
        return path
    base, ext = os.path.splitext(path)
    match = re.search(r"\.(\d)+$", base)
    if match:
        num = int(match.group(1))
        base = base[: match.start()]
    else:
        num = 0
    while True:
        num += 1
        candidate = f"{base}.{num}{ext}"
        if not exists(candidate):
            return candidate


def relative_destination(artist: str | None, title: str | None, *, ext: str = ".mp3") -> str:
    """The library-relative `artist/title.mp3` fragment for the applied identity.

    Reproduces beets' singleton `$artist/$title` template + legalization: sanitize each
    component, NFC-normalize, append the (lowercased) extension, then byte-truncate each
    component preserving the extension. No collision handling here (that needs the absolute
    path — see `destination`). An absent artist/title lands the file with an empty component,
    exactly as beets' `os.path.join(*comps)` would; every land supplies both.
    """
    comps = [_sanitize_component(artist or ""), _sanitize_component(title or "")]
    # NFC (non-darwin branch of Item.destination): the /mnt/c filename must match the byte
    # form Windows/Jellyfin store, or the scan never indexes it.
    comps = [unicodedata.normalize("NFC", c) for c in comps]
    ext = ext.lower()
    # Truncate: the last component keeps room for the extension, parents get the full cap.
    *parents, stem = comps
    parents = [_truncate_component(p, _MAX_COMPONENT_BYTES) for p in parents]
    stem = _truncate_component(stem, _MAX_COMPONENT_BYTES - len(_FS_ENCODING(ext)))
    return os.path.join(*parents, stem + ext)


def destination(
    artist: str | None,
    title: str | None,
    *,
    library_dir: str | None = None,
    ext: str = ".mp3",
    exists: Callable[[str], bool] = os.path.exists,
) -> str:
    """Absolute path the applied identity should land at, collision-suffixed (the mover).

    `library_dir` defaults to `LIBRARY_DIRECTORY`; `exists` is injected so tests can drive
    the `.N` collision path without touching the filesystem.
    """
    root = library_dir if library_dir is not None else LIBRARY_DIRECTORY
    rel = relative_destination(artist, title, ext=ext)
    return unique_path(os.path.join(root, rel), exists=exists)
