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

- 2026-07-21 — (T-020 browser verify) **The Vite dev proxy MASKS a hard backend death from the
  browser `EventSource` — `onerror` never fires, so no reconnect/fallback logic can run.** Driving
  the real card at `:5174` (Vite proxy → isolated backend `:8140`) and `kill -9`-ing the backend
  mid-job, the card froze on its last stage. An `EventSource` instrument (patched via
  `navigate_page`'s `initScript` before app JS) proved why: `construct → open`, then **no `error`
  event at all** across a 15s outage. Vite's proxy holds the client-side SSE connection open while
  the upstream socket is gone, so the browser never learns the stream dropped. Consequences: (1) a
  browser drop-recovery test *through the Vite proxy* cannot exercise the `onerror` path — use the
  `FakeEventSource` unit tests for that logic (they model the real `onerror` sequence faithfully),
  or test against a non-proxied / nginx transport; (2) this is a **dev-proxy artifact**, not an app
  bug, and NOT fixable in the app (no signal to react to) — a heartbeat-timeout would just be the
  give-up policy killed three times, so don't add one. A *graceful* restart (SIGTERM / real
  `uvicorn --reload`) is different: the in-flight job finishes and its `track.done` flows through the
  held-open connection, so the card completes normally with no false detach.
- 2026-07-21 — (T-020) **`unicode-bidi: plaintext` DEFEATS a `direction: rtl` start-truncation —
  it re-bases the line LTR and moves the ellipsis back to the end, hiding the filename it was meant
  to keep.** `.track-card__path` wanted start-truncation (a path's tail — the filename — is the only
  distinguishing part; every track shares the library prefix). A real-browser check showed the
  shipped `direction: rtl; unicode-bidi: plaintext` rendered `/mnt/c/Users/aj_am/Music/CleanMuzik/…`
  — prefix shown, filename gone — identical to plain LTR. `text-overflow: ellipsis` clips at the END
  of the line's *base direction*, and `plaintext` sets that base from the content's first strong
  char (LTR for a path), so the ellipsis lands on the right. Fix: drop `plaintext`, keep
  `direction: rtl`. The comment claimed `plaintext` was needed so the path stays copyable, but
  copy/selection uses DOM *logical* order regardless of visual bidi reordering — the only cost of
  rtl-only is the leading `/` rendering at the far right, purely cosmetic. Rule: **verify bidi/
  truncation CSS in a real rendering engine; `caretRangeFromPoint` offsets are unreliable under
  bidi — screenshot instead.**
- 2026-07-21 — (T-020) **A "one snapshot per outage" latch must count only an ANSWERED check, not a
  failed one.** `TrackCard`'s reconnect fallback latched `outageChecked=true` on the first `onerror`
  and called `checkOnce`; if that check ran while the backend was still down (fetch rejects, no
  answer), the latch was never cleared, and when the backend returned with the job already terminal
  (empty replay, no event to clear the latch via `on()`), the recovery snapshot never fired and the
  card froze. Fix: on a *transient* (non-404, no-answer) failure, reset `outageChecked=false` so the
  next `onerror` retries once the backend is back; a definitive answer (terminal / still-running /
  404) stays latched. Cost: ~1 snapshot per EventSource-retry during a *total* outage — bounded, and
  never against a healthy stream (ADR-005 holds). Note: proven by unit test + reasoning, NOT by the
  browser — the Vite proxy (entry above) prevents `onerror` from firing, so this path is only
  reachable on a transport that surfaces the drop (production nginx, a real network blip).
- 2026-07-21 — (T-027) **A URL-shape validator that enumerates the *bad* shapes leaks the ones it
  didn't think of; gate on the *good* shape instead.** `is_playlist_url` refused the playlist
  shapes it knew — a `/playlist` path, a `list=` with no song — and admitted everything else. A
  YouTube **channel / `@handle`** URL is neither of those, so it sailed through as if it were a
  song. Worse than a bad tag: `download_song` calls `extract_info(url, download=True)`, and on a
  collection-shaped result yt-dlp **downloads every entry** before returning — a mistyped channel
  URL would have pulled the whole channel into staging before any post-extract guard could fire
  (`noplaylist=True` can't help; it only picks the single video out of a `watch?v=…&list=…`, and a
  channel names no single video). Two fixes, owner-approved as "C + A": **(C)** reject at the route
  on the *positive* predicate `names_one_song(url)` — the complement that admits exactly the
  single-song shapes and refuses channels/searches/bare domains *before* a job starts; **(A)** a
  belt-and-braces guard in `download_song` that raises on a playlist-shaped `extract_info` result
  (`_type=="playlist"` / `entries`) so anything that still reaches the downloader (e.g. a non-YouTube
  `?v=` set, which `names_one_song` still admits) fails honestly on the **download** stage instead
  of handing back a bogus `prepare_filename` path that mis-attributes as a transcode
  `FileNotFoundError` two stages later. Rules: **when a guard runs *after* an expensive/irreversible
  step, the guard is in the wrong place — move the check before the step;** and **prefer a positive
  allowlist of valid shapes over a denylist of invalid ones** (the same "breadth in a validator is
  not safety" family as T-026, seen from the other side: there over-*rejection* was the risk, here
  it was silent over-*admission*). Reproduce-first paid off: the channel-download behaviour was only
  visible by actually running `download=True` (capped to one item for safety), not by reading code.
- 2026-07-21 — (T-029 browser verify, nearly reported a phantom bug) **A long-lived Vite dev
  server on this repo serves STALE JavaScript — WSL2's inotify does not fire on the `/mnt/c`
  Windows mount, so Vite never HMRs a source change and a page reload re-serves the cached
  transform.** The `:5175` verify server had been up ~11h; the T-029 client fix landed *after* it
  started, so the browser ran the *pre-fix* `TrackCard` and faithfully reproduced the OLD bug
  (id-only "Unknown title" rows, dead buttons, no re-park message). It looked exactly like a real
  regression. **Before trusting any browser `/verify`, confirm the served bundle is current**: e.g.
  `curl -s localhost:<port>/src/components/TrackCard.tsx | grep -c <a-marker-only-in-the-fix>`, or
  just restart the dev server with `--force` and reload. Rule: a dev server that predates the commit
  under test is presumed stale until proven otherwise. (The server-side half was correct the whole
  time; only the client bundle lied.)

- 2026-07-20 — (T-021/T-025 verify, paid two flaked runs) **To verify what *lands on the file*
  (tags/genre/year/art), don't drive the auto-accept path — the AcoustID fingerprint gate flakes
  under the shared/private quota (ADR-006 addendum) and parks `rec=none` on a track that landed
  fine last session, giving you no file to inspect.** Land *deterministically* via the resolve path
  instead: run the pipeline, and if it parks, call `resolve_import(review.staging_path, ...,
  recording_id=review.candidate_ids[0])` — it shares the exact `_configure_import_options`
  (`from_scratch`) and `finalize_outcomes` (year stamp) code, so the tags are identical to
  auto-accept. **And isolate the library in one shot** without a running server: set
  `beets_engine.LIBRARY_DIRECTORY` to a temp dir *before* `configure_beets` reads it, and pass
  `Settings(db_path=<temp>)` + `scan_fn=lambda *a, **k: None` to `run_pipeline` — real
  yt-dlp/ffmpeg/AcoustID/MusicBrainz, zero risk to the real library or Jellyfin. (Recipe lived in
  `scratchpad/verify_t021_t025.py`.)

- 2026-07-18 — (T-014 optional re-review, caught belt-and-suspenders) **A "commit before the
  best-effort step" reorder must protect the commit boundary in the *generic* exception handler,
  not just the one failure it special-cased.** The T-014 fix that moved the row-commit + staging
  drop *before* the Jellyfin scan handled the scan's own `JellyfinScanError` inline — but the outer
  `except Exception` still called `_release` unconditionally. So any *other* post-commit throw (a
  non-`JellyfinScanError` from the scan, `registry.set_stage`, or the `track.done` publish raising
  during shutdown) rolled an already-landed `resolved` review back to `pending` with staging gone —
  the very ADR-009-class inconsistency the reorder existed to kill, walking back in through the
  catch-all. Fix: a `committed` flag set at the point of no return; both handlers only `_release`
  when `not committed`. **Rule: when you introduce a commit point mid-function, the invariant is
  "no handler releases a committed unit of work" — enforce it on the catch-all by a flag, so it
  holds by construction, not by the reader proving no post-commit line can throw.** (Two sibling
  bugs in the same review: a batch `get_library()` hoisted *outside* the per-row `_hydrate` guard
  could 500 the whole review queue on one library-open failure → wrap it, fall back to per-row; and
  a hand-off rollback that only the route did, leaving the *job* stranded at `running` → moved the
  job-state rollback into `submit_resolve`, which alone knows what it mutated.) (→ `server/app/jobs.py`
  `run_resolve` / `submit_resolve`; regression tests in `test_reviews.py` + `test_jobs.py`.)

- 2026-07-18 — (T-014 integration, caught by the high-effort review) **A resolve/resume path that
  is a "twin" of the main pipeline must mirror that pipeline's commit-point and terminal-close
  discipline, or it silently reintroduces the exact data-loss / hang bugs the pipeline already
  solved.** Two escaped into `run_resolve` and were caught reviewing the merge, not writing it:
  (1) `replace` deleted the old library file, then a *later* Jellyfin-scan failure rolled the review
  back to `pending` — re-queueing a landing that already committed, so the queue contradicted the
  library. Fix: once the file has landed (and for `replace`, the old copy is gone) the resolve is
  **committed** — mark it `resolved` and drop staging *before* the scan; a scan failure is an error
  but must not `_release` the review. This is exactly what `run_pipeline` already does with a
  post-landing scan failure; the twin just hadn't copied it. (2) The `review is None` early-return
  (and any raise before the `try`) bypassed `_finish` → `bus.close`, so the SSE channel
  `submit_resolve` had reopened hung at `running` forever. Fix: pass `job_id` in (not read off the
  review) and put the whole body inside the `try`, so *every* exit closes the stream. **Rule:
  whenever you add a second entry point that re-runs a shared heavy operation (import, land, scan),
  diff it against the original's failure/finalize path line by line — the commit boundary and the
  "every path calls the terminal close" invariant are the two things a twin forgets.** (→ ADR-009
  family; `server/app/jobs.py run_resolve`; regression tests in `test_reviews.py`.)

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
- 2026-07-15 — (T-009) **beets' import duplicate stage CANNOT detect our duplicates by MBID —
  `chosen_info()` exposes the recording id under `track_id`, not `mb_trackid`.** On the APPLY path,
  `SingletonImportTask.find_duplicates` builds its probe from `chosen_info()` — the match's
  `TrackInfo`, whose recording id is `track_id`. `library.Item(**chosen_info)` therefore has
  `mb_trackid == ''` (the `track_id`→`mb_trackid` mapping only happens later, in `apply_metadata`), so
  a `duplicate_keys.item = mb_trackid` query matches **nothing** and `get_duplicate_action` never
  fires — every re-paste lands a silent second copy, the exact thing T-009 exists to prevent. The
  default `artist title` key *does* fire (those keys are in `chosen_info`) but over-matches — it
  falsely merges a live take with the studio cut (same artist+title, different recording). Fix: don't
  use beets' import stage at all — detect **directly against the library at accept time** in
  `choose_item`, where we already hold the winning recording id and the library:
  `lib.items(dbcore.query.MatchQuery("mb_trackid", recording_id))`. Set `duplicate_keys = mb_trackid`
  only to keep beets' own stage an inert no-op. **Verification lesson:** the ASIS path with a
  pre-populated `library.Item` probe gives a false green — you must reproduce the real APPLY path (a
  `TrackMatch`/`TrackInfo`) to see the `track_id` vs `mb_trackid` mismatch. (Also killed the
  earlier two-axis "tag completeness" comparison: it's read pre-apply and is a wash for same-recording
  copies anyway, so acquire-time dedup compares **bitrate only**; tag/acoustic tie-breaks are R2.) (→
  `server/app/import_seam.py`)
- 2026-07-16 — SSE: reconnecting to a **completed** job whose channel had been evicted by the
  256-job registry cap made the stream fabricate a **fresh, never-closed channel** → it emitted
  `ping` forever and the card never terminated (a hang, not an error — the worst kind). The
  in-memory registry and the durable `jobs.status` row have **different lifetimes**, and the
  in-memory one is not the source of truth for "is this finished". Rule: when a live channel is
  absent, consult **durable status** before opening a stream — the route passes it down as a
  `terminal` hint, and an absent channel + a terminal status closes the stream immediately (the
  client falls back to the `GET /api/jobs/{id}` snapshot). Any cache with an eviction policy needs
  an "evicted vs never-existed" answer, or absence reads as "still running". (→ `server/app/events.py`)
- 2026-07-16 — MusicBrainz canonicalizes some artist names with a **Unicode HYPHEN (U+2010)**, not
  ASCII `-`: the a-ha library folder is literally `a‐ha`. An ASCII `grep`/`ls`/path literal for
  `a-ha` finds **nothing** and the directory looks missing. Don't hand-type artist paths in tests or
  probes — derive them from the beets item, or match on the recording id.
- 2026-07-16 — `<input type="url">` **natively blocks a schemeless paste** ("www.youtube.com/…"):
  the browser's own validation rejects it before the submit handler ever fires, so the button looks
  **dead** with no error — the worst failure shape (silent). The backend is the real gate (it
  classifies and 422s), so the field is `type="text"`. Rule: don't let native input validation
  duplicate a server-side gate — it can only disagree with it, and it fails silently when it does.
  (→ `client/src/App.tsx`)
- 2026-07-17 — (T-014 reconcile) **A contract-narrowing commit updated the source and the ADR but
  left a test asserting the dead shape — the commit's own suite was red.** `6c7a69a` (ADR-010) cut
  `candidate_row` from seven keys to four across `events.py` and `import_seam._candidate_rows`, but
  `tests/test_events.py::test_candidate_row_is_the_canonical_seven_key_shape` still asserted the old
  seven, so the tree that "closed the art hole" shipped a failing test. Two lessons: (1) when you
  narrow a contract, grep the test tree for the old shape in the SAME change — the assertion that
  locks a contract is exactly the one that must move with it; (2) reconciling a worktree onto a moved
  base means adopting *all* of the base's touched call sites, not just the ones the brief names — the
  brief said "events.py + reviews.py", but `import_seam._candidate_rows` and this test also spoke the
  old shape and would have failed the merge. Fixed the test to the four-key shape as part of T-014.
- 2026-07-17 — (T-014, caught by `/verify`, not by review) **`replace` deleted TWO files when the
  library held two copies of one recording id — the exact state `keep_both` exists to create.**
  `_replace_existing` deletes every library item matching the recording id, which is correct for the
  everyday one-copy case and destructive for the one `keep_both` produces: two files, same recording
  id (a remaster shares one), different titles, both deliberately kept. A later `replace` on that
  recording then destroyed both — including the copy the owner had explicitly chosen to keep. Spec §6
  and ADR-009's addendum both say `replace` deletes "**the** existing library file", singular; neither
  settles *which* when there are two, so the code silently picked "all". Fix: **refuse** when >1
  library file shares the recording id, checked *before* the import lands anything (so nothing needs
  unwinding), with a message naming the paths. A click that can't identify its target is not consent
  to delete every candidate for it — the conservative reading is the ADR's own idiom. **The general
  lesson: a destructive operation keyed on a non-unique identifier is a data-loss bug waiting for the
  day the key stops being unique — and a sibling feature (`keep_both`) was the thing that made it
  non-unique.** Also a verification lesson: this was invisible to unit tests and to review, and only
  appeared because `/verify` drove the branches *in sequence* against a real library — keep_both then
  replace. Branch-at-a-time testing would never have produced the state. (→ `server/app/jobs.py`;
  needs an owner ruling on what `replace` *should* do with two copies)
- 2026-07-17 — (T-014, verification) **A nested `TestClient(app)` silently breaks the app under test:
  its lifespan replaces `app.state.worker` with a new worker and then *stops* it on exit.** Used a
  nested client to simulate "restart the backend" while holding the outer client open; every
  subsequent `POST /resolve` enqueued onto the dead worker, nothing drained the queue, and the SSE
  stream never closed — the verify hung with no error (a hang, not a failure: the worst shape).
  `app` is module-global, so the two clients were never independent. Rule: **one `TestClient` context
  == one backend lifetime.** To test a restart, exit the first context entirely and open a second —
  which is also the more honest test, since it gives a genuinely fresh worker + EventBus and proves
  spec §7's "parked reviews … can still be resolved" across the boundary rather than just "still
  list". (→ T-014 verify script)
- 2026-07-16 — **The board is not a filing cabinet.** `.claude/hot.md` reached 883 lines because the
  `/hot` skill said "prepend an entry, never rewrite older ones" (append, no eviction) while the
  Definition of Done's "transcribe corrections to learnings.md" lived in a *different* file the save
  path never read. Result: from T-012 on, lessons were stapled to the session board instead of filed
  — `learnings.md` stops at T-011 — and the board accumulated **false** statements about current
  state (two rival `## Current State` sections; T-015 described as both committed and still in a
  worktree) that were loaded into every session. Rule: a write path must carry its own filing rule
  inline; a norm stated in a file the writer doesn't read is not a rule. The board holds only what is
  **unfiled + true-only-today**; everything else goes to its owning store. (Same bug exists upstream
  in claude-obsidian: a 500-word cap in `WIKI.md`, a save skill that just says "reflect the new
  addition", and a hot.md at 3.3× its own cap.)
- 2026-07-16 — **A browser `EventSource` auto-reconnects when the server closes the stream, so our
  own clean shutdown reads to it as a crash.** The backend closes a job's channel on *every* terminal
  path (`_finish` → `bus.close`) — done, error, **and review**, plus a duplicate skip that emits no
  event at all. EventSource sees EOF, assumes a dropped connection, and reconnects ~3s later; the
  route then replays the buffer for the already-terminal job and closes again → an infinite
  reconnect loop, with the card re-animating through the replay each cycle. Rule: **the client must
  hang up first.** `TrackCard` closes the stream itself on `track.done` / `track.error` /
  `track.review_required` — all three end the *stream*, even though a review is not the end of the
  owner's workflow (T-017 re-subscribes after resolving). Corollary for anything that reopens a
  channel: **reset the replay buffer per episode**, or the new subscriber replays the old
  `track.review_required` and closes itself instantly — the same hang, one layer down.
  (→ `client/src/components/TrackCard.tsx`, `server/app/events.py::reopen`)
- 2026-07-16 — **`'toString' in obj` is `true`.** `in` walks the prototype chain, so it is not a
  membership test for a lookup map. A `track.error` payload with `stage: "toString"` passed a
  `v in ERROR_STAGE_LABEL` guard, got cast to a valid stage, and rendered
  `Object.prototype.toString` — a *function* — as a React child, on the exact path whose job is to
  name the failing stage. Use `Object.hasOwn(map, key)`. (→ `client/src/components/TrackCard.tsx`)
- 2026-07-16 — **`direction: rtl` to truncate a path from the left silently re-orders it.** It moves
  the ellipsis, but bidi-neutral characters at the paragraph boundary take the paragraph's
  direction: the leading `/` of `/mnt/c/…/Take On Me.mp3` jumps to the far right, and the owner is
  shown a path they cannot copy. Add `unicode-bidi: plaintext` so each line keeps the direction of
  its own first strong character while the box still truncates on the left. Any CSS that reverses
  direction for a *layout* effect will also reverse the *text*. (→ `client/src/components/TrackCard.css`)
- 2026-07-16 — **A defensive `or {}` on the server becomes a clobber on the client.** `jobs.py`
  emits `{"tags": landed.tags or {}}` and `Outcome.tags` is `dict | None`, so `track.done` can carry
  `tags: {}`. A client narrower that returned a truthy object of nulls then painted "Unknown title"
  over the correct match already shown by `track.tagging` — a perfect match ending as a failure on
  screen. Two rules: a narrower must return **null when it knows nothing** (an all-null object is not
  a value), and a display field should have **one writer** — the bug existed only because the done
  payload was written through into state the tagging event also owned. Deriving it at render removed
  the whole class. (→ `client/src/components/TrackCard.tsx`)
- 2026-07-16 — **Bound a reconnect in BOTH directions; the obvious half is the less dangerous one.**
  A snapshot-on-stream-death fallback (`GET /api/jobs`, spec §6's sanctioned reconnect path) fails
  two ways. Too patient: if the stream flaps while the snapshot keeps answering "running", every ~3s
  EventSource retry fires another fetch forever — no timer involved, but the traffic is
  indistinguishable from the polling the ADR forbids. Too eager: erroring on the *first* failed
  snapshot kills the card, and the most ordinary reason the stream and the snapshot fail together is
  the backend restarting — so every open card would die on every `uvicorn --reload`. One counter of
  consecutive failures, reset by any received event (a `ping` counts — that's what it's for), bounds
  both. (→ `client/src/components/TrackCard.tsx`)
- 2026-07-17 — **A code review cannot catch "this isn't what the ticket asked for", and four of them
  didn't.** T-016's ticket demanded cover art on `track.tagging` from the day the tickets were
  generated (`4a2f60f`); that event's payload has never carried art, and album/year/art_url on a
  review candidate were emitted null by every path since T-007. It survived T-007, T-012, T-013 and
  T-015 — including two high-effort reviews that *did* catch a data-loss bug and a hang-forever bug.
  Not a lapse: `/code-review` reads a **diff** and asks "is this code correct?" The card's code was
  correct — it faithfully rendered what the wire carried, and cannot render a field the wire lacks.
  The defect lived *between the ticket text and spec §6*, and **neither document is in the diff**.
  Compounding it: each agent sat in a single-ticket worktree, and the gap only appears when you line
  up `_candidate_rows` (server) against the card (client) — a view no fanned-out agent has, and the
  integrator's job to take. Rule: **a correctness receipt is not an acceptance receipt.** Read the
  ticket's own "Done when" against the diff, as its own step — now item 2 of the Definition of Done.
  Found only because the owner asked "what was the goal of T-016?" (→ ADR-010, `CLAUDE.md`)
- 2026-07-17 — **A contract field that is structurally always null reads as "not filled in yet", and
  the comment explaining it becomes an instruction to build the wrong thing.** `_candidate_rows`
  emitted `art_url=None` with a docstring saying "T-014/T-017 fill it when the owner actually views
  the queue" — a reasonable-sounding deferral that was *impossible to honour*, since album/year/art
  are **release** properties and a singleton candidate is a **recording** (`track_for_id` →
  `track_info(recording)`; one recording lives on many releases). T-014's agent duly wrote
  `album=None, year=None, art_url=None` with its own honest note, and the null propagated with two
  layers of documentation explaining it. Rules: **don't ship a key you cannot fill** — omit it, and
  let the absence be the honest signal; and **a docstring that promises a future ticket will do X is
  a live instruction** — if X is later withdrawn, the docstring is now actively wrong and must be
  corrected in the same commit as the decision. (→ ADR-010, `server/app/events.py::candidate_row`)
- 2026-07-18 — **A worktree review certifies code against its own assumptions about the other half;
  the integration review is where those assumptions get tested.** T-016's in-worktree review passed
  the track card after 4 fixes. The pre-commit review on the *merge* found 8 defects, 6 confirmed —
  and every one turned on something outside the diff: `EventBus.stream` replaying its whole buffer to
  each new subscriber (so the client's failure counter resets on every reconnect and its give-up bound
  is unreachable — the card degrades into ~3s polling, violating ADR-005), and EventSource's spec
  behaviour that a **non-200 fails the connection permanently** with no retry (so a 404 from the
  events route hangs the card silently on "Queued" forever). The card's comments stated both premises
  explicitly and both were wrong. Neither is visible from `client/`: one lives in `server/app/events.py`,
  the other in the HTML spec. Rules: **when a fanned-out ticket consumes another component's contract,
  the integration review must re-derive that contract from the other side's source, not from the
  consumer's comments about it** — a confident comment asserting how the peer behaves is a claim to
  check, not context to trust. And **a stated invariant ("this is bounded", "this can't loop") is the
  highest-yield thing to attack**, because it's load-bearing and nothing tests it. Related in shape to
  the 2026-07-17 acceptance lapse above: both are defects that live *between* components, where no
  diff-scoped reviewer is looking. (T-016 integration; cost: a second full review pass at the merge)
- 2026-07-18 — **Don't write failure-handling policy you cannot make fail.** The fixes for the six
  defects above introduced three new confirmed ones, and the second review pass found *more* defects
  than the first (10 vs 8). Every wrong answer was in the same layer: deciding when a stream is "too
  broken to keep retrying". One version detached on the first `uvicorn --reload` blip; another could
  never detach at all; a third detached a healthy 12-minute download because the rail hadn't moved.
  Each was reasoned carefully, type-checked, and wrong — because the inputs (real drops, restarts,
  races) cannot be produced in this sandbox, so there was no feedback signal at any point. **A green
  build is not evidence about failure paths; it is evidence only about the happy path.** Rules:
  **when a change's whole purpose is to handle conditions you cannot reproduce, that is a sequencing
  bug, not a coding problem** — carve it out and build it where it can be driven (→ T-020), rather
  than shipping a policy whose correctness rests entirely on argument. And **when successive fix
  rounds find more than they resolve, stop patching**: the count going up is the signal that the
  work is mis-sequenced, and one more round of reasoning will not supply the evidence that's missing.
  Corollary that saved a fourth round: the platform's own behaviour (EventSource auto-retry + the
  server's replay buffer) was already a correct recovery story — the bugs were all in the bespoke
  policy layered on top of it. Prefer the mechanism you can't get wrong to the one you can't test.
  (T-016 → T-020 carve-out; cost: three fix rounds + two full review passes)
- 2026-07-18 — **A rejecter written without watching how the input is actually produced will
  reject the real input.** `is_playlist_url` refused *any* `list=` parameter, a breadth its own
  docstring called "deliberate": `watch?v=X&list=Y` was read as "a song *in* a playlist" and
  refused rather than "guess which track was meant". The first browser session showed there was
  nothing to guess and nothing to protect. YouTube appends `&list=RD…` **by itself** whenever you
  play from Liked Videos or a search result, so the owner's everyday URL — his *primary* way of
  getting a link — was refused outright, and only the share-sheet link (which strips the parameter)
  ever worked. Meanwhile `v=` names exactly one video, and `download_song` already passes
  `noplaylist=True`: verified live against the exact radio URL, yt-dlp returned **one** line, the
  named track. So the outer check was pure cost — it blocked the main flow while the guarantee it
  claimed to provide was enforced a layer below it. Rules: **breadth in a validator is not safety,
  it is untested scope** — every extra thing you reject is a thing you have not watched a real user
  produce. And **before adding a guard, check whether the layer beneath already enforces it**; two
  guards for one invariant means the outer one's only unique contribution is its false positives.
  The tell was in the docstring all along: "deliberately broad" and "rather than guess" are
  confidence about a case nobody had observed. (First browser session; cost: the entire evening's
  primary flow, worked around by accident via the share menu.)
- 2026-07-18 — **`localhost` is not a location, and a dependency that is *down* cannot tell you
  whether your error handling is *wrong*.** Two lessons from one incident. First: `JELLYFIN_URL`
  defaulted to `http://localhost:8096` and could **never** have worked — the server runs inside
  WSL, Jellyfin runs on Windows, and WSL2's `localhost` is its own namespace. Not "misconfigured":
  structurally unreachable, since T-001, invisible because the scan is the one step that crosses a
  host boundary (the library path doesn't — beets writes `/mnt/c/...` directly). Phase 0 was
  written as "the owner's laptop at localhost", and the laptop turned out to be **two hosts**. The
  fix is the WSL gateway IP from `ip route show default`, with mirrored networking
  (`.wslconfig` → `networkingMode=mirrored`) as the durable answer since that IP moves on restart.
  Rule: **an environment assumption is load-bearing code and gets exercised like code** — "it's
  just config" is how a value survives four tickets unrun. Second, and the sharper one: with
  Jellyfin down, a proposal was made to change how a scan failure is reported — reasoning that it
  poisoned an otherwise successful landing. The owner pushed back: with the service off, a card
  reading `ERROR` and a card *wrongly* reading `ERROR` are the **same observation**. Starting
  Jellyfin resolved it in a minute and the proposed fix evaporated into a preference about a
  failure path never actually seen. Rule: **when a dependency is down, you cannot distinguish
  correct error reporting from a bug — restore the dependency before diagnosing anything above
  it.** This is the sandbox lesson above ("a green build is evidence only about the happy path")
  wearing different clothes, and it recurred *in the very session convened to fix it*: the
  temptation to reason past missing evidence does not announce itself as such.
  (First browser session; caught by the owner, not by the suite.)
- 2026-07-19 — **A config flag is not a fix until you've followed it to the code path your product
  actually takes.** `original_date: yes` was researched, justified, written into the config, and
  recorded as **ADR-011** — all in one pass, and all wrong. beets reads that option only in
  `AlbumInfo.item_data` (`autotag/hooks.py:325`); R1 imports **singletons**, which build a
  `TrackInfo` (`hooks.py:400`) with no such override and no `original_year` to read. The change
  altered no byte of any file. What made it survive to an ADR: the option's *name and
  documentation* answered the question perfectly, `config_default.yaml` confirmed it existed and
  defaulted off, and the suite stayed green — because **nothing in 284 tests asserts on year**, so
  a no-op change is indistinguishable from a working one. Three plausible-looking confirmations,
  none of them evidence. Rules: **when the fix is "set a flag", the acceptance check is to find the
  code that reads it and confirm your call path reaches that code** — grep the option name in the
  dependency, don't stop at its docs. And **never write the decision record before the observable
  artifact**: ADR-011 was filed within minutes of the edit and before any import ran, which
  inverted the Definition of Done's order and turned a wrong guess into recorded doctrine. Recording
  a wrong fix is worse than recording an open problem — the problem stays visible, the "fix" stops
  anyone looking. This is ADR-010's failure mode (*a decision whose payload cannot deliver it*)
  repeated **on the same night ADR-010's lesson was being cited to the owner**, which is the
  uncomfortable part worth keeping: knowing a failure mode by name does not stop you walking into
  it — only checking does. The problem itself is real and unfixed → T-025; ADR-011 kept as
  **rejected**, with the autopsy, so the next person who reaches for that option finds the answer.
  (First-browser-session follow-up; caught by the review pass an hour later, not by the suite.)
- 2026-07-19 — **A normaliser whose output you throw away is not a normaliser — it is a second
  opinion nobody acts on.** `_parse` was added so a scheme-less paste (`youtu.be/<id>`, the shape
  you get copying from a text message) would stop being false-rejected: it prepended `https://`
  and handed the tidied URL to the classifier. But it returned *parsed parts for the decision*,
  not a string for the caller, so the **raw** URL was what got stored, submitted, and passed to
  `extract_info`. yt-dlp picks its extractor by regex over the raw string, and no YouTube
  `_VALID_URL` matches without a scheme — so every scheme-less paste fell through to the
  **generic** extractor, which is not a YouTube extractor and does not honour `noplaylist`, by
  then the *sole* one-song guarantee. Net effect: the fix converted a clean 422 into a confusing
  failure deeper in the pipeline, on exactly the input it was written to support. Rule: **when you
  clean a value in order to judge it, the cleaned value is what must travel** — validating X and
  then using Y is the same bug whether Y is dirtier, staler, or merely different. The tell is a
  helper that takes a string and returns something that isn't one: it can inform a decision but
  cannot be propagated, so the call site silently keeps the original. Corollary, and the reason
  the suite was no help: the three scheme-less tests added alongside `_parse` asserted only
  *classification*, never that the URL survived to the downloader — a fix's own tests will happily
  cover the half of the path the author was thinking about.
- 2026-07-19 — **A placeholder that can't match the real pattern makes a test pass for the wrong
  reason.** Writing the regression test above, the first version used `abc123` as a video id and
  asserted against `YoutubeIE`. Both were wrong and each hid the other: YouTube's `_VALID_URL`
  requires an **11-character** id, so a 6-character placeholder matches no YouTube extractor at
  all — the "scheme-less URLs don't reach YouTube" assertion would have held for a URL with a
  scheme too. And there is no single `YoutubeIE` to assert on: a `watch?v=…&list=` goes to
  `youtube:tab`, the short domain to `YoutubeYtBe`, a plain song to `youtube`. Only running it
  surfaced either. Rules: **test fixtures must be able to match the thing under test** — if a
  value cannot possibly satisfy the real pattern, an assertion that it doesn't proves nothing; and
  **assert the behaviour, not the class that implements it** (here: "some YouTube extractor
  claims this", not "this exact one does"), or the test breaks on refactors while missing the bug.
  (Caught by running the test, which is the only reason it was caught.)
- 2026-07-19 — **`localhost` sockets are NOT blocked in this sandbox; `CLAUDE.md` said they were,
  and that claim shaped four tickets' worth of verification.** While checking T-028's migration, a
  plain `curl http://localhost:8137/api/reviews` against the owner's running `uvicorn` returned the
  real JSON — a full HTTP round-trip, no `TestClient` involved. `CLAUDE.md` had asserted "this
  sandbox blocks live sockets, so `TestClient` is this repo's `/verify` handle", and that sentence
  is why T-016's stream reattach, T-020's whole scope, and the browser run list were all filed as
  "needs the owner in a browser". Some of that is still true — *driving a DOM* needs a browser —
  but **anything reachable over HTTP was drivable all along**, including `POST /api/jobs`, the SSE
  stream, and the review endpoints. Rule: **an environment limit is a claim, and a claim that
  routes work away from you deserves one cheap test before it is written into the rules file.**
  The cost of checking was one `curl`; the cost of not checking was months of tickets scoped around
  a wall that wasn't there. Corollary: the tell was that nobody ever recorded the *symptom* — no
  connection-refused, no timeout, just an inherited "sandbox blocks sockets". A limit with no
  observed failure behind it is a rumour. (Found incidentally, chasing an unrelated question about
  which process migrated the live DB.)
- 2026-07-19 — **A running `uvicorn --reload` will silently migrate the owner's live database the
  moment you edit the schema module.** Adding `_migrate()` to `db.py:init_schema` was meant to be
  inert until the next boot. But the owner's dev server was up with `--reload`, so saving the file
  triggered a reload, which re-ran the lifespan, which called `init_schema()` — and the live DB
  gained its new column within seconds of the edit, with no command issued and no output seen. It
  worked, and the pending review survived, but that was luck rather than design: had the migration
  been destructive it would have run against real data before a single test did. Rules: **check for
  a running dev server before editing anything that mutates state at startup** (`pgrep -af uvicorn`
  costs nothing), and **test a migration against a copy first, on purpose, rather than discovering
  afterwards that production already ran it.** The confusion this caused is its own tell — several
  minutes went into "which test touched the live DB?" when no test had; the answer was a process
  nobody had accounted for. When state changes and no command you ran explains it, **look for the
  daemon before doubting the code.**
- 2026-07-19 — **MusicBrainz IS reachable from this environment; the "sandbox can't reach
  MusicBrainz" note (T-013's verify record) was another inherited wall with no observed failure
  behind it.** Setting up the T-017 browser verification, a plain `curl` to
  `musicbrainz.org/ws/2/recording/…` returned 200, and `beets.metadata_plugins.track_for_id`
  resolved a real MBID to `Never Gonna Give You Up / Rick Astley`. So the pattern that bit us with
  `localhost` sockets repeats exactly: a limitation was written into the record from an assumption,
  not a symptom (no rate-limit error, no timeout was ever logged — T-013 "stubbed the MB-dependent
  land" pre-emptively). Consequence: an isolated verification stack can be **fully real** — seeded
  review rows re-hydrate to real titles/artists, and weak-match accept / duplicate replace+keep_both
  actually tag through beets against live MB — no stubbing required. Same rule as the socket entry:
  **an environment limit that routes work away from you is a claim; spend the one cheap probe before
  believing it.** (Found setting up T-017's verification.)
