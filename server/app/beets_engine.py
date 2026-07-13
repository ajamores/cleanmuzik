"""beets tagging engine — programmatic config + explicit plugin loading (T-003).

beets is the identify/tag/organize engine (ADR-005), and this module owns the
config the whole backend shares. T-007's `ImportSession` drives imports against
it; here we only stand the engine up and prove it loaded.

Two facts about driving beets from a long-lived backend (instead of the `beet`
CLI) shape every line below:

  1. **The library API does NOT auto-load plugins — only the CLI does.** Unless we
     call `beets.plugins.load_plugins()` ourselves, `chroma` never fingerprints and
     matching silently degrades to tag-only (ADR-007; learnings 2026-07-11). This
     is the whole point of the ticket.
  2. **In beets 2.12 MusicBrainz is its own plugin.** `chroma` resolves fingerprint
     MBIDs *through* it and returns zero candidates if it isn't enabled, so the
     plugin list must lead with `musicbrainz` (ADR-007).

Call `configure_beets()` once at startup, then `smoke_check()` for a boot receipt
that all six plugins loaded and `chroma` can reach `fpcalc` (the Chromaprint
binary it shells out to). Both are safe to call more than once.
"""

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass

from beets import config, plugins

from app.config import Settings, get_settings

logger = logging.getLogger("cleanmuzik")

# Library root = the Jellyfin watched folder (spec §6, ADR-008). beets organizes
# into it; Jellyfin reads from it. WSL path for the Windows `C:\…\Music\CleanMuzik`.
LIBRARY_DIRECTORY = "/mnt/c/Users/aj_am/Music/CleanMuzik"

# beets `paths` (spec §6). A single that MusicBrainz resolves to a real release
# has an album → `default`; a truly album-less song → `singleton`.
PATHS = {
    "default": "$albumartist/$album%aunique{}/$track $title",
    "singleton": "$artist/$title",
    "comp": "Compilations/$album%aunique{}/$track $title",
}

# Order matters: `musicbrainz` must precede `chroma` (ADR-007). These six are the
# spec §2 identify/tag/art/lyrics set — no more, no less.
PLUGINS = ["musicbrainz", "chroma", "lastgenre", "fetchart", "embedart", "lyrics"]

# Set once configure_beets() has run so it's idempotent at *our* layer too (beets'
# load_plugins is already guarded, but we also mutate global config + LASTFM_KEY).
_configured = False


def configure_beets(settings: Settings | None = None):
    """Build the shared beets config and load the six plugins (ADR-007).

    Idempotent: safe to call from both the startup hook and `smoke_check()`.
    Returns the beets global `config` object.
    """
    global _configured
    if _configured:
        return config

    s = settings or get_settings()

    config["directory"].set(LIBRARY_DIRECTORY)
    config["paths"].set(PATHS)
    config["plugins"].set(PLUGINS)

    # Optional API keys. Absent keys must NOT crash (spec §6): each plugin ships a
    # working built-in key, so we override only when the owner actually set one.
    if s.acoustid_apikey:
        # chroma uses this for AcoustID *submission*; lookups use beets' built-in
        # key. Setting it raises rate limits when provided (spec §6).
        config["acoustid"]["apikey"].set(s.acoustid_apikey)
    if s.lastfm_apikey:
        # lastgenre binds its Last.fm key from the module global
        # `beets.plugins.LASTFM_KEY` at import time — NOT from user config — so the
        # override must land BEFORE load_plugins() imports the plugin. Absent →
        # beets' built-in key stands and genre is still fetched.
        plugins.LASTFM_KEY = s.lastfm_apikey

    # ADR-007: the library API never auto-loads plugins. Without this call chroma
    # never runs and singleton lookup degrades to tag-only. `load_plugins()` reads
    # config["plugins"] itself and takes no args in 2.12.
    plugins.load_plugins()

    _configured = True
    return config


@dataclass(frozen=True)
class SmokeResult:
    """Boot receipt for the beets engine (T-003 done-when)."""

    ok: bool
    loaded_plugins: list[str]
    missing_plugins: list[str]
    fpcalc_path: str | None
    fpcalc_version: str | None
    problems: list[str]


def _resolve_fpcalc() -> tuple[str | None, str | None]:
    """Locate the Chromaprint `fpcalc` binary chroma shells out to.

    pyacoustid honours `$FPCALC` (the spike's no-sudo path — a static binary in the
    scratchpad) and otherwise falls back to `fpcalc` on PATH. Returns
    `(path, version)`, or `(None, None)` when it can't be found.
    """
    candidate = os.environ.get("FPCALC", "fpcalc")
    if os.path.isabs(candidate):
        # os.path.isfile, NOT os.access(X_OK): on a WSL /mnt/c mount a
        # Windows-downloaded binary frequently lacks the Unix execute bit yet
        # execs fine (pyacoustid just subprocesses it, no X_OK check). The
        # `-version` probe below is the real runnability test, not this.
        path = candidate if os.path.isfile(candidate) else None
    else:
        path = shutil.which(candidate)
    if path is None:
        return None, None

    version: str | None = None
    try:
        proc = subprocess.run(
            [path, "-version"], capture_output=True, text=True, timeout=10
        )
        output = (proc.stdout or proc.stderr).strip()
        version = output.splitlines()[0] if output else None
    except (OSError, subprocess.SubprocessError):
        # A found-but-unrunnable binary still counts as a problem the caller sees
        # via a missing version; don't mask the path we resolved.
        version = None
    return path, version


def smoke_check(settings: Settings | None = None) -> SmokeResult:
    """Confirm all six plugins loaded and chroma can reach `fpcalc`.

    Non-raising: returns a `SmokeResult` whose `problems` list is empty iff the
    engine is fully wired. The startup hook logs it; a test can assert on it.
    """
    configure_beets(settings)

    loaded = sorted(p.name for p in plugins.find_plugins())
    missing = [name for name in PLUGINS if name not in loaded]

    problems: list[str] = []
    if missing:
        problems.append(f"plugins failed to load: {', '.join(missing)}")

    fpcalc_path, fpcalc_version = _resolve_fpcalc()
    if fpcalc_path is None:
        problems.append(
            "fpcalc (Chromaprint) not found — chroma cannot fingerprint, so every "
            "song would fall through to the review queue. Install "
            "libchromaprint-tools or set FPCALC to a static binary "
            "(see server/README.md)."
        )
    elif fpcalc_version is None:
        # Found but `-version` failed to run (wrong arch, missing shared lib): a
        # broken binary silently fingerprints nothing, so it must NOT report green
        # — this is the exact silent degradation the boot receipt exists to catch.
        problems.append(
            f"fpcalc found at {fpcalc_path} but won't run (`-version` failed) — "
            "likely wrong architecture or a missing shared library. chroma cannot "
            "fingerprint. Reinstall Chromaprint or fix FPCALC (see server/README.md)."
        )

    return SmokeResult(
        ok=not problems,
        loaded_plugins=loaded,
        missing_plugins=missing,
        fpcalc_path=fpcalc_path,
        fpcalc_version=fpcalc_version,
        problems=problems,
    )


def log_smoke_check(settings: Settings | None = None) -> SmokeResult:
    """Run the smoke check and log a one-line boot receipt (never a secret)."""
    result = smoke_check(settings)
    if result.ok:
        logger.info(
            "beets engine ready: plugins=%s fpcalc=%s (%s)",
            " ".join(result.loaded_plugins),
            result.fpcalc_path,
            result.fpcalc_version or "version unknown",
        )
    else:
        # A degraded engine still lets the service boot (a track can land tag-only),
        # so warn loudly rather than crash — but make the cause unmissable.
        logger.warning(
            "beets engine DEGRADED: %s | loaded=%s",
            " ; ".join(result.problems),
            " ".join(result.loaded_plugins),
        )
    return result
