"""Unit tests for title normalization (T-006).

`normalize_title` is a **pure function** — no network, no beets — so the whole
contract is exercised here. The spike's known-song titles are the anchor cases:
with the embedded artist supplied (as T-007 supplies it), they normalize to the
strings that promoted the correct candidate to #1 (learnings 2026-07-11).

Run from the `server/` directory: `./.venv/bin/pytest tests/test_normalize.py -v`
"""

import pytest

from app.normalize import normalize_title

# (raw_title, artist_or_None, expected). Grouped by the behaviour each row pins.
CASES = [
    # --- The spike's real titles (the acceptance anchor), artist supplied. -
    ("Fleetwood Mac - Dreams (Official Audio)", "Fleetwood Mac", "Dreams"),
    # Rick Astley: promo bracket goes, a real qualifier stays.
    (
        "Rick Astley - Never Gonna Give You Up (Official Video) (4K Remaster)",
        "Rick Astley",
        "Never Gonna Give You Up (4K Remaster)",
    ),
    ("a-ha - Take On Me (Official Video)", "a-ha", "Take On Me"),

    # --- Promotional bracket cruft in its many spellings (no artist needed). -
    ("Song (Official Music Video)", None, "Song"),
    ("Song (Official Audio)", None, "Song"),
    ("Song [Official Video]", None, "Song"),
    ("Song {Official Video}", None, "Song"),          # brace variant (finding 7)
    ("Song (Lyrics)", None, "Song"),
    ("Song (Lyric Video)", None, "Song"),
    ("Song (Official Lyric Video)", None, "Song"),
    ("Song (Visualizer)", None, "Song"),
    ("Song (Visualiser)", None, "Song"),
    ("Song (Audio)", None, "Song"),
    ("Song (HD)", None, "Song"),
    ("Song (HQ)", None, "Song"),
    ("Song (4K)", None, "Song"),
    ("Song (MV)", None, "Song"),
    ("Song (With Lyrics)", None, "Song"),
    # Standalone (Video)/(Music Video)/(HD Video) — no "official" (finding 3).
    ("Song (Video)", None, "Song"),
    ("Song (Music Video)", None, "Song"),
    ("Song (HD Video)", None, "Song"),
    # Resolution / quality tags (finding 4).
    ("Song (1080p)", None, "Song"),
    ("Song (720p)", None, "Song"),
    ("Song (HD 1080p)", None, "Song"),
    ("Song (Full HD)", None, "Song"),
    # Multiple cruft groups all go.
    ("Song (Official Video) [HD]", None, "Song"),

    # --- Meaningful qualifiers are KEPT (they change the recording). -------
    ("Song (Live)", None, "Song (Live)"),
    ("Song (Remix)", None, "Song (Remix)"),
    ("Song (2022 Remaster)", None, "Song (2022 Remaster)"),
    ("Song (feat. Someone)", None, "Song (feat. Someone)"),
    ("Song (Live at Wembley)", None, "Song (Live at Wembley)"),
    # A real qualifier riding next to a promo word stays — when in doubt, keep.
    ("Song (Official Live Video)", None, "Song (Official Live Video)"),
    ("Song (Full Album)", None, "Song (Full Album)"),

    # --- Pipe-delimited promo tail (finding 5). ---------------------------
    ("Never Gonna Give You Up | Official Video", None, "Never Gonna Give You Up"),
    ("Song | HD | Official Audio", None, "Song"),

    # --- Leading `Artist - ` prefix removal — ONLY with the artist given. --
    ("Artist - Title", "Artist", "Title"),
    ("R.E.M. - Losing My Religion", "R.E.M.", "Losing My Religion"),
    ("AC/DC - Back in Black", "AC/DC", "Back in Black"),
    # En-dash and em-dash separators (YouTube uses them).
    ("Artist – Title", "Artist", "Title"),
    ("Artist — Title", "Artist", "Title"),
    # Hyphenated word is NOT a separator (no surrounding spaces).
    ("Spider-Man Theme", None, "Spider-Man Theme"),

    # --- The blind-strip regression the artist-aware rule fixes (finding 2). -
    # A legitimate " - " with no artist prefix must NOT lose its real title.
    ("Bohemian Rhapsody - Remastered 2011", None, "Bohemian Rhapsody - Remastered 2011"),
    # Even with an artist, a non-matching prefix is left alone.
    ("Bohemian Rhapsody - Remastered 2011", "Queen", "Bohemian Rhapsody - Remastered 2011"),

    # --- Both moves at once, plus dangling-separator cleanup. --------------
    ("Artist - Song - (Official Video)", "Artist", "Song"),
    ("Artist - Title (Official Audio)", "Artist", "Title"),

    # --- Empty-query guard: a non-empty title never collapses to "" (finding 1).
    ("Coldplay - (Official Video)", "Coldplay", "Coldplay"),

    # --- Degenerate inputs. -----------------------------------------------
    ("", None, ""),
    ("   ", None, ""),
    ("Just A Title", None, "Just A Title"),
    ("Title   with    spaces", None, "Title with spaces"),
]


@pytest.mark.parametrize("raw, artist, expected", CASES)
def test_normalize_title(raw: str, artist: str | None, expected: str) -> None:
    assert normalize_title(raw, artist) == expected


@pytest.mark.parametrize("raw, artist, expected", CASES)
def test_non_empty_input_never_yields_empty_query(
    raw: str, artist: str | None, expected: str
) -> None:
    # The empty-query guard: any input with real content produces a non-empty
    # query, so T-007 never hands beets an empty string to match on (finding 1).
    if raw.strip():
        assert normalize_title(raw, artist) != ""


@pytest.mark.parametrize(
    "raw, artist",
    [
        ("Rick Astley - Never Gonna Give You Up (Official Video)", "Rick Astley"),
        # A multi-dash title is the case a blind strip broke idempotency on.
        ("Radiohead - Karma Police - Live (Official Video)", "Radiohead"),
        ("Bohemian Rhapsody - Remastered 2011", None),
    ],
)
def test_normalize_title_is_idempotent(raw: str, artist: str | None) -> None:
    # Running it twice changes nothing — a clean title is a fixed point, even
    # for titles that still carry an internal dash (finding 6).
    once = normalize_title(raw, artist)
    assert normalize_title(once, artist) == once
