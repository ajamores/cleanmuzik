"""T-308 acceptance — a matched credit reproducing the T-037 case lands under the
single canonical folder (ADR-028, spec §Testing "T-037 normalisation").

The unit fold is pinned in `test_normalize.py`; the match-shaped wiring in
`test_import_seam.py`. This file closes the loop the spec asks for: drive the
credit through the **real beets path template** and assert the *landed folder* —
the observable the owner sees in Jellyfin — is the canonical one, not a mangled
split. It is a regression guard that a fresh write never re-splits the artist.

No real library is touched: an in-memory beets library rooted at a temp
directory, and only `Item.destination()` is computed (no copy, no organize).
"""

import os

import pytest
from beets import config, library, util
from beets.autotag import Distance, TrackMatch
from beets.autotag.hooks import TrackInfo

from app.beets_engine import PATHS, configure_beets
from app.import_seam import canonicalize_credit


@pytest.fixture
def temp_library(tmp_path):
    """A beets library rooted at a temp dir, with the app's real path formats.

    Overrides `config['directory']` off the real CleanMuzik library (the /verify
    hazard) so nothing here can land against it.
    """
    configure_beets()
    config["directory"].set(str(tmp_path))
    config["paths"].set(PATHS)
    lib = library.Library(":memory:", str(tmp_path))
    return lib, tmp_path


def _landed_folder(lib, tmp_path, info: TrackInfo) -> str:
    """The top-level folder `info` would land under, via the real path template."""
    item = library.Item()
    item.update(info.item_data)  # what beets applies onto the item at import
    lib.add(item)
    dest = util.displayable_path(item.destination())
    return os.path.relpath(dest, str(tmp_path)).split(os.sep)[0]


def test_mangled_credit_lands_under_the_canonical_folder(temp_library):
    lib, tmp_path = temp_library
    # The T-037 subject: Ÿ (U+0178) + Unicode hyphen (U+2010), both mangled.
    match = TrackMatch(Distance(), TrackInfo(artist="JAŸ‐Z", title="My 1st Song"), None)

    folded = canonicalize_credit(match)

    assert _landed_folder(lib, tmp_path, folded.info) == "JAY-Z"


def test_the_fold_is_what_moves_the_folder(temp_library):
    # Negative control: the SAME credit, unfolded, lands under the mangled folder —
    # proving the canonical landing is the fold's doing, not the path template's.
    lib, tmp_path = temp_library
    mangled = TrackInfo(artist="JAŸ‐Z", title="My 1st Song")

    assert _landed_folder(lib, tmp_path, mangled) == "JAŸ‐Z"


def test_accented_artist_folder_is_preserved(temp_library):
    # The fold must never manufacture a NEW split from the owner's correctly
    # accented folders — the exact bug T-037 exists to kill.
    lib, tmp_path = temp_library
    match = TrackMatch(Distance(), TrackInfo(artist="Sigur Rós", title="Hoppípolla"), None)

    folded = canonicalize_credit(match)

    assert _landed_folder(lib, tmp_path, folded.info) == "Sigur Rós"
