# Learnings — CleanMuzik (engine-level, all releases)

The ratchet loop. When an agent gets something wrong and it's corrected, the lesson is written
here — so the mistake is paid for once, not re-taught every session. Lives at **repo level**
(not under a release) because beets / yt-dlp / AcoustID quirks apply to every release, including
R2's migrate flow.

**Write trigger:** transcribe corrections here as part of every `/hot save` and `/handoff` — the
file dies without a habit attached. A repeated entry is a signal to *harden*: promote it to an
ADR, a `CLAUDE.md` rule, a skill, or a test.

Format: `- <date> — what went wrong → the correction / rule now in place`

---

- 2026-07-11 — Drove `beets.importer.ImportSession` programmatically; got 0 candidates / `rec=none`
  on well-known tracks and nearly recorded it as a real 0% auto-accept rate → **the beets library
  API does not auto-load plugins; only the CLI (`beets.ui`) does.** Must call
  `plugins.load_plugins()` yourself before running an import, or chroma never fingerprints and
  singleton lookup silently degrades to tag-only matching. The FastAPI backend must load plugins at
  startup. (Full context: `r1/spike-beets-review-queue.md`.)
- 2026-07-11 — beets **2.12** API differs from most online (1.x) tutorials: `importer` is a package;
  the action enum is `Action` not `action` (`Action.SKIP`); singleton choice hook is
  `choose_item(task)` (albums use `choose_match(task)`); `plugins.load_plugins()` takes **no args**.
- 2026-07-11 — The free AcoustID web service returned a transient `status: error` that cleared on
  retry → treat AcoustID as flaky/rate-limited; the real pipeline needs retry + backoff, not a
  single-shot lookup. (chroma swallows lookup errors, so a failed lookup looks like "no match".)
- 2026-07-11 — Dev-box setup, no sudo: `python3 -m venv` fails (no `ensurepip`/`python3.10-venv`) →
  use `pip install --user virtualenv`. `fpcalc` (Chromaprint, needed by chroma) isn't apt-installable
  without sudo → grab the static binary from the Chromaprint GitHub release and set `FPCALC`.
- 2026-07-11 — In beets 2.12 **MusicBrainz is a separate plugin**; chroma resolves fingerprint MBIDs
  through it (`self.mb`) and silently returns 0 candidates if `musicbrainz` isn't enabled → config
  must list `plugins: musicbrainz chroma …`, not just `chroma`. (→ ADR-007)
- 2026-07-11 — An **untagged** file makes the autotagger run a MusicBrainz search with an empty
  `query=` → HTTP **400**. Real yt-dlp rips avoid this only if downloaded with `--embed-metadata`
  (bare `-x` strips tags). The acquire flow must embed metadata (or beets pulls it from the video).
- 2026-07-11 — **Measured, not assumed:** a bare YouTube **singleton** cannot reach beets' `strong`
  rec on tag matching — even correct, clean tracks plateau at `medium` (dist ~0.11 floor: no
  album/track#/year to corroborate). PRD's "~80% auto-accept" is false for default-config singletons
  (measured 0/3). Auto-accept must trust dominant AcoustID fingerprint identity in `choose_match`,
  not relaxed thresholds; review queue is the primary path. (→ ADR-006, `r1/spike-beets-review-queue.md`)
- 2026-07-11 — Cleaning YouTube title cruft (`(Official Audio)`, leading `Artist - `) before
  matching is a cheap, real lever: it promoted a `none`→`medium` and ranked the correct candidate #1
  in every test case. Worth a pre-match normalization step. (It improves ranking, not the `strong` bar.)
- 2026-07-13 — (T-006) The leading-`Artist - ` strip must be **artist-aware**, not a blind "cut
  everything before the first spaced dash." YouTube's `Artist - Title` convention collides with real
  titles that carry a `-` (`"Bohemian Rhapsody - Remastered 2011"`), and shape alone can't tell them
  apart — a blind strip discards the real title and hands beets an empty/wrong query. Fix: strip the
  prefix only when it matches the **known artist** (from T-004's embedded tag); with no artist, keep
  the title. Also normalize-to-empty is a real hazard (`"Coldplay - (Official Video)"`), so guard the
  query against collapsing to `""`. (→ `server/app/normalize.py`)
- 2026-07-12 — (T-003) beets `lastgenre` does **not** read the Last.fm key from user config — its
  client binds `pylast.LastFMNetwork(api_key=beets.plugins.LASTFM_KEY)` at *import* time, and
  `LASTFM_KEY` is a hardcoded built-in key that works out of the box. So to use the owner's
  `LASTFM_APIKEY` you must assign `beets.plugins.LASTFM_KEY = <key>` **before** `load_plugins()`
  imports the plugin; setting a config value does nothing. Corollary: genre is fetched even with no
  owner key (the built-in one stands) — the spec's "missing key = no genre" is stricter than reality,
  same as the AcoustID built-in key.
- 2026-07-12 — (T-003) In beets **2.12** the `musicbrainz` plugin is a self-contained HTTP client
  built into beets — `musicbrainzngs` is no longer a dependency. Don't pin/import it. Resolve a
  recording MBID to a candidate `TrackInfo` via the loaded plugin's `track_for_id(mbid)`. Also:
  AcoustID can return recording MBIDs that 404 at live MusicBrainz (merged/removed) — expected data
  drift, not a wiring bug; other candidates still resolve.
- 2026-07-14 — (T-008) The **gap-to-runner-up** check is dead weight for fingerprint auto-accept.
  Measured on 25 real songs: a high runner-up was *always* the SAME recording listed twice in
  AcoustID (a re-release/duplicate submission), never a different rival — two genuinely different
  recordings don't both fingerprint-match one audio at ≥0.9. So a gap floor only ever false-parks
  matches you're certain of (canonical: Kanye "Through The Wire" — top 0.987 vs a 0.977 *duplicate*).
  Decision: `SCORE_MIN=0.90`, `GAP_MIN=0.0` (gap kept as an injectable knob, off by default). The
  real safety is the `_matching_candidate` identity check, not the gap. (→ ADR-006 addendum)
- 2026-07-14 — (T-008) **AcoustID "no match" = an empty result set, not a ranked list of maybes.**
  AcoustID is not a nearest-neighbour recommender: it returns the exact recording (artist/title/
  releases) or `results: []`. The review queue's "maybe this / that" candidates come from a *separate*
  path — a MusicBrainz **text search on the title** — not from the fingerprint. So a song with no
  fingerprint match AND no usable title/tags parks *empty*; a fresh YouTube rip parks with candidates
  because it still carries its title. This is why good titles matter and the review panel is title-driven.
- 2026-07-14 — (T-008) **AcoustID key terminology is a trap.** The credential from
  acoustid.org/new-application ("register an application") is an **application / lookup** key — valid
  for `acoustid.lookup`, with its own rate-limit quota (verified with the owner's 10-char key,
  `status=ok`). beets calls a user-supplied key "submission" only because its *own* code uses a
  provided key just for `beet submit` and does internal lookups on beets' built-in key — that's a
  beets behaviour, not a property of the key. Our seam hardcodes pyacoustid's **shared** built-in
  app key (`1vOwZtEn`) for its lookup, which throttles hard under load; point it at the owner's app
  key for a private quota. (→ ADR-006 addendum; T-011)
- 2026-07-14 — (T-008, field note) **yt-dlp fails opaquely on a private playlist** — it throws a
  generic "invalid URL" / can't-resolve error with no hint that visibility is the cause. A playlist
  must be **public or unlisted** to resolve. First thing to check when a playlist won't load: its
  privacy setting. (Owner-reported; hours lost to it once.)
- 2026-07-14 — (T-011) **Retry only *transient* failures — classify AcoustID errors by code.**
  pyacoustid's `_api_request` does **not** call `raise_for_status()`; it returns the parsed JSON, so
  a rate-limit (HTTP 429) AND an invalid key (HTTP 400) both arrive the same way — a non-ok `status`
  in the returned dict, distinguishable only by `error.code`. A naive "retry every `AcoustidError`"
  loop therefore retries a permanently-bad key: it burns the full exponential backoff on *every* song
  and then silently parks the whole run with no signal the key is wrong. Fix: split the errors —
  invalid-key / malformed-request codes (a denylist incl. 4 & 6) raise a non-retryable
  `AcoustidPermanentError` that fails fast and logs at ERROR ("check ACOUSTID_APIKEY"); everything
  else (rate limit 14, service-unavailable 13, internal 5, network/timeout, unknown code) stays a
  retryable `AcoustidLookupError`. Denylist not allowlist, so an unrecognised code errs toward retry
  (harmless wasted backoff), never toward hammering a doomed key. Also: retry the *lookup* only —
  the fingerprint is deterministic local work, generate it once. (→ `server/app/import_seam.py`)
- 2026-07-14 — (T-010, verification field note) **`localhost` from WSL2 does not reach a
  Windows-hosted service.** Jellyfin runs native on Windows (ADR-008) at `localhost:8096`, but WSL2
  has its own network namespace, so from WSL `localhost:8096` gets connection-refused. Reach the
  Windows host at the WSL2 gateway IP — `ip route show default | awk '{print $3}'` (was `172.20.0.1`
  this session; it is **not stable** across reboots, so derive it, don't hardcode). This is a
  *verification-environment* quirk only: on the Phase-0 laptop the app itself runs on Windows where
  the configured `localhost` is correct, so the `.env` value stays `http://localhost:8096` — only
  in-WSL manual `/verify` probes need the gateway override (via `settings.model_copy`). (→
  `server/app/jellyfin.py`)
- 2026-07-15 — (T-009) **Never let a library tool auto-delete the owner's file — beets' duplicate
  REMOVE deletes before it copies.** The obvious "keep the better copy" implementation returns
  `DuplicateAction.REMOVE`, but beets 2.12 `manipulate_files` runs `remove_duplicates()` (which
  `item.remove()`s and `util.remove()`s the OLD file off disk) *first*, then copies the new one — no
  rollback. A copy failure after the delete (disk full, permission, bad path) loses BOTH copies. For
  a music library that's an unacceptable data-loss window. R1 fix: **never auto-delete.** Keep the
  existing copy (SKIP) whenever an existing copy *covers* the incoming one; otherwise park to review
  and let the owner confirm any replacement. Auto-replace-with-deletion is deferred to R2 migrate,
  where it can be done copy-first / delete-after. (→ `server/app/import_seam.py`)
- 2026-07-15 — (T-009) **`get_duplicate_action` runs BEFORE beets applies the match, so the incoming
  item is still un-tagged.** In the 2.12 importer, `_resolve_duplicates` (which calls
  `get_duplicate_action`) fires before `_apply_choice`/`apply_metadata`, so `task.item` carries only
  the raw download's tags at decision time — comparing its "tag completeness" against a fully-tagged
  library item is apples-to-oranges and would systematically misjudge the incoming copy. The fix that
  also killed the destructive branch: model quality as a **partial order** on `(bitrate, tag
  completeness)` and only SKIP-keep-existing when an existing copy is `>=` on **both** axes. A bare
  fresh download can only *fail* to cover an already-tagged copy — never wrongly displace it — so
  reading pre-apply tags becomes correct rather than a bug, and every genuine upgrade / trade-off
  falls through to review. (Also: the 2.12 duplicate hook is `get_duplicate_action(task,
  found_duplicates) -> DuplicateAction`, not the older `resolve_duplicate` the ticket named.) (→
  `server/app/import_seam.py`)
