"""Title normalization — clean YouTube cruft before matching (R1, T-006).

Between download (T-004) and the beets import seam (T-007) sits one pure,
network-free step: take the raw YouTube video title and strip the promotional
noise that buries the correct MusicBrainz candidate.

The spike proved the lever (learnings 2026-07-11): a raw title like
`"Fleetwood Mac - Dreams (Official Audio)"` ranked the *correct* match third;
normalizing it to `"Dreams"` pushed that match to #1. It does **not** cross the
`strong` bar — that is why the gate trusts the fingerprint (ADR-006) — but it
fixes ranking, which is what the review queue and the query fallback read.

Three moves, in order (spec §2):

1. **Drop promotional bracket groups** — `(Official Audio)`, `[Official Video]`,
   `(Music Video)`, `(Lyrics)`, `(Visualizer)`, `(HD)`, `(4K)`, `(1080p)`, and
   kin, in `()`/`[]`/`{}`. A group is removed only when **every** word in it is
   promotional; a meaningful qualifier the fingerprint might care about —
   `(Live)`, `(Remix)`, `(2022 Remaster)`, `(feat. X)`, `(Official Live Video)`
   — keeps the whole group. When in doubt, keep it and let the fingerprint
   decide.
2. **Drop a pipe-delimited promo tail** — `Song | Official Video` → `Song`,
   using the same all-words-promotional test on each `|` segment.
3. **Drop a leading `Artist - ` prefix** — but only when we're **told** the
   artist (from the download's embedded tags). A blind "strip everything before
   the first dash" throws away real titles like `"Bohemian Rhapsody - Remastered
   2011"`; matching the known artist string is precise and safe. With no artist
   given, the prefix is left intact — a slightly worse query beats a wrong one.

Pure and unit-testable by contract: same inputs in, same string out, no I/O. A
non-empty title never collapses to `""` (the empty-query guard below).
"""

import re

# A bracket group — (), [], or {} — capturing its inner text. YouTube uploaders
# use all three interchangeably for the same cruft.
_BRACKET_GROUP = re.compile(r"[(\[{]\s*([^)\]}]*?)\s*[)\]}]")

# Words that are *purely* promotional. A bracket group or pipe segment is
# stripped only when EVERY word in it is one of these (or a resolution tag) —
# any other word, including a real qualifier like "live" / "remaster" / "feat",
# keeps the group. This is the "when in doubt, keep it" rule made mechanical:
# extend the set to strip more, never to strip something ambiguous.
_PROMO_WORDS = frozenset(
    {
        "official",
        "music",
        "video",
        "audio",
        "hd",
        "hq",
        "uhd",
        "lyric",
        "lyrics",
        "lyrical",
        "visualizer",
        "visualiser",
        "mv",
        "with",
        "and",
        "the",
        "full",
    }
)

# Resolution / quality tags: 4k, 8k, 1080p, 720p, 2160p — promotional, never a
# qualifier. A bare year like "2022" (in "2022 Remaster") has no k/p suffix, so
# it is NOT matched and its group survives.
_RESOLUTION = re.compile(r"^\d+[kp]$")

# Word tokens inside a group (letters/digits), used to test promo-ness.
_WORD = re.compile(r"[a-z0-9]+")

# En/em dashes count as separators alongside the ASCII hyphen (YouTube uses all).
_DASH = r"[-–—]"

# Runs of whitespace left behind after removals.
_WHITESPACE = re.compile(r"\s{2,}")

# A separator (`-`, `|`, en/em dash) stranded at either end once the group beside
# it was removed, e.g. `"Song - "` → `"Song"`.
_DANGLING_SEP = re.compile(r"^\s*[-–—|]+\s*|\s*[-–—|]+\s*$")


def _is_pure_promo(text: str) -> bool:
    """True when every word in `text` is promotional (so the group can go).

    Empty/word-less text returns False — an empty bracket is not "promo", it is
    nothing, and removing it is the caller's whitespace concern, not ours.
    """
    words = _WORD.findall(text.lower())
    if not words:
        return False
    return all(w in _PROMO_WORDS or _RESOLUTION.match(w) for w in words)


def _strip_promo_brackets(title: str) -> str:
    """Remove every bracket group whose words are all promotional."""
    return _BRACKET_GROUP.sub(
        lambda m: "" if _is_pure_promo(m.group(1)) else m.group(0),
        title,
    )


def _strip_promo_pipe_segments(title: str) -> str:
    """Drop `|`-delimited segments that are purely promotional; rejoin the rest.

    `"Never Gonna Give You Up | Official Video"` → `"Never Gonna Give You Up"`.
    A title with no `|` is returned untouched (no reformatting).
    """
    if "|" not in title:
        return title
    kept = [
        seg.strip()
        for seg in title.split("|")
        if seg.strip() and not _is_pure_promo(seg)
    ]
    return " | ".join(kept)


def _strip_artist_prefix(title: str, artist: str | None) -> str:
    """Strip a leading `<artist> - ` prefix, but only if `artist` is known.

    Matches the exact artist string (case-insensitive, any dash), so a title
    whose dash is *not* an artist separator keeps its name. No artist → no strip.
    """
    if not artist or not artist.strip():
        return title
    prefix = re.compile(rf"^\s*{re.escape(artist.strip())}\s+{_DASH}\s+", re.IGNORECASE)
    return prefix.sub("", title, count=1)


def _cleanup(title: str) -> str:
    """Collapse whitespace and shear any separator left dangling at the ends."""
    title = _WHITESPACE.sub(" ", title).strip()
    return _DANGLING_SEP.sub("", title).strip()


def normalize_title(raw: str, artist: str | None = None) -> str:
    """Normalize a raw YouTube video title into a clean beets query string.

    Strips promotional bracket/pipe cruft and — when `artist` is supplied (the
    download's embedded artist tag, per T-007) — a leading `<artist> - ` prefix.
    Pure: no network, no state. Improves candidate *ranking*, not beets'
    confidence rec (ADR-006).

    A non-empty input never returns `""`: if removing the artist prefix would
    empty the title, the pre-strip form is kept instead, and a raw fallback backs
    even that. Empty/whitespace input returns `""`.
    """
    base = _strip_promo_pipe_segments(_strip_promo_brackets(raw))
    stripped = _strip_artist_prefix(base, artist)
    # Prefer the artist-stripped form; never collapse a real title to an empty
    # query (that would hand beets nothing to match on). Fall back to the
    # pre-strip form, then to the raw text.
    return _cleanup(stripped) or _cleanup(base) or raw.strip()
