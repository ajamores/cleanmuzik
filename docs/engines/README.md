# Engine notes — what the external tools can and can't do

Reference pages for the external engines CleanMuzik drives. They exist to stop the same class of
rework twice: a rule stated without its scope, a cost model nobody measured, a config key assumed
global. Written for T-038 (`docs/backlog/T-038.md`) after T-103 slice A lost roughly a session to
exactly that.

These describe **external tools, not a release.** They outlive R1 → R1.1 → whatever follows, which
is why they live here and not under `docs/r1/`.

| Page | Engine | Status |
|---|---|---|
| [`beets.md`](beets.md) | beets 2.12 — the tagging engine (ADR-005) | evidenced |
| [`musicbrainz.md`](musicbrainz.md) | MusicBrainz WS/2, via beets' built-in client | evidenced |
| [`acoustid.md`](acoustid.md) | AcoustID + Chromaprint — the live identification tier | evidenced |
| [`yt-dlp.md`](yt-dlp.md) | yt-dlp — the download stage | evidenced |
| [`shazamio.md`](shazamio.md) | ShazamIO — the ADR-019 backup tier | **open questions only** |
| [`thin-surfaces.md`](thin-surfaces.md) | ffmpeg · Jellyfin API · Last.fm · Cover Art Archive + iTunes | thin by design |

## The sourcing rule

**Every non-obvious claim carries how it was established.** This is the point of these pages, not a
formatting preference — a confident rationale is precisely what stops the next reader from
re-checking it, and that failure mode is on record twice already (ADR-010's cover art; T-103's fork
justification, `learnings.md` 2026-07-30).

Three tags, used inline:

- **`[source]`** — read from the installed library, with `file:line`. Paths are relative to
  `server/.venv/lib/python3.14/site-packages/`. Pinned versions, so the lines are stable; re-check
  on a version bump.
- **`[measured]`** — timed or observed against the running app, with the number and the date.
- **`[assumed]`** — reasoned but **not** verified. Treat as a lead, not a fact. If you verify one,
  promote it and say how.

An untagged sentence is either a definition or a pointer to another doc. If you catch an untagged
claim that is really an assumption, that's a bug in the page — fix it.

## What belongs here, and what doesn't

**These pages answer one question: *what does the external tool do?*** One incident usually produces
sentences for several stores. They are different sentences, and only one of them lives here.

| The sentence | Belongs in | Example, all from the same 27-second incident |
|---|---|---|
| **The fact** — what the tool does | **here** | *`tracks_for_ids` makes one HTTP request per id; the MusicBrainz plugin doesn't override it* |
| **The rule** — what to do differently | `docs/learnings.md` | *before hydrating a list of ids against a rate-limited API, ask what the list response already carries* |
| **The decision** — what we chose | `docs/r1/adr.md` | *don't invent a confidence threshold* (ADR-006/010/020) |
| **The scope** — what to build | `docs/r1.1/tickets.md`, `docs/backlog/` | *the Shazam tier's build ticket* |
| **The why-this-code** — why this module is shaped so | the module's docstring | *`mb_search.py`'s four findings* |

**Where they touch, link — don't restate.** A pointer (`→ the rule this produced:
learnings.md 2026-07-30`) is the whole obligation. Two copies of a rule means one of them goes stale
and nothing reconciles them — which is exactly the failure that produced this directory
(`.env.example` vs `beets_engine.py`, wrong for weeks; `learnings.md` 2026-07-30).

**The test, applied per paragraph:** *if this tool were swapped out tomorrow, would this sentence be
deleted?* Yes → it belongs here. No → it belongs to one of the other stores, and this page gets a
link to it.

Summarising a measurement and pointing at the full record is **not** duplication — that's a
citation. Copying the reasoning is.
