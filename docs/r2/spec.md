# R2 Spec — Playlists (+ T-037 tag-mangle fix)

> **Status:** `ready-for-agent` (specing → build). Scope signed off via the R2 scope grilling
> (2026-08-08). Product scope truth is `cleanmuzik-prd.md`; this file is R2's exit criteria.
> Binding decisions live in `docs/r1/adr.md` — this spec **calls for two new ADRs** (batch/backfill
> data model; T-037 artist-credit normalisation) and must not silently reverse ADR-001–005 or ADR-016.

R2 is the second everyday job from the PRD: **paste a YouTube _playlist_ URL and walk away.** R1
ships single-song acquire; R1.1 made the review inbox durable. R2 turns the same pipeline on a whole
playlist and mirrors it into Jellyfin as a playlist — the owner's monthly "music journals." It also
fixes **T-037**, a tagging-path defect the batch would multiply.

**Migrate/clean the existing library is _not_ R2** — it split out to a later release (R2.5). See
Out of Scope.

---

## Problem Statement

The owner curates music by month: a YouTube playlist per month (e.g. "August 2025") of everything he
listened to — personal "music journals." Today he can only bring that music into his clean Jellyfin
library **one song at a time**: R1 deliberately refuses a playlist URL with a `422`. So a 50-song
month is 50 manual pastes, and even then there is **nothing in Jellyfin that preserves the month** —
the grouping that is the whole point of the journal is lost the moment songs land under
`Artist/Album`.

Separately, the shared tagging path has a latent defect (**T-037**): some artist credits are written
mangled (a `JAY-Z` → `JAŸ-Z` encoding fault), splitting one artist across multiple library folders.
On single-song acquire this bites rarely; a 50-song batch multiplies every occurrence.

## Solution

Paste **one YouTube playlist URL** and walk away. The app:

1. Expands the playlist into its N tracks and runs each through the **existing** pipeline
   (download → transcode → identify → tag → land), one at a time (ADR-001, sequential).
2. Creates a **Jellyfin playlist named after the YouTube playlist** and adds each track to it as the
   track lands — so the month survives as a playable Jellyfin playlist, while each file still lands
   canonically under `Artist/Album` (one copy on disk; the playlist is pointers).
3. Sends low-confidence tracks to the **same review inbox** R1.1 built; when the owner resolves one
   later, it **backfills** into its playlist automatically.
4. Is **safe to re-run**: re-pasting a playlist as it grows through the month updates the _same_
   Jellyfin playlist and skips songs already in the library — no duplicates, no re-prompts.

And it fixes **T-037** so a batch never re-splits an artist across folders.

The owner watches all of this through **one aggregate playlist card** (not 50 cards) that reads like
a journal filling in — progress, outcome buckets, album art, and messy songs shown as "still filling
in," never as red errors.

---

## User Stories

1. As the owner, I want to paste a YouTube _playlist_ URL and have every track downloaded, so that a
   month's music enters my library in one action instead of 50 pastes.
2. As the owner, I want the app to accept a playlist URL that R1 used to reject, so that the
   paste-and-walk-away flow finally works for playlists.
3. As the owner, I want each landed track organised canonically under `Artist/Album`, so that my
   library stays clean regardless of which playlist a song came in through.
4. As the owner, I want a Jellyfin playlist named after the YouTube playlist, so that my monthly
   "journal" grouping survives into Jellyfin as something I can play.
5. As the owner, I want the Jellyfin playlist to contain pointers to the one canonical file, so that
   a song appearing in three months isn't stored three times on disk.
6. As the owner, I want low-confidence tracks in a 50-song batch to go to the existing review inbox,
   so that batching doesn't invent a second place to look for problems.
7. As the owner, I want a track I resolve in the inbox _days later_ to join its original playlist
   automatically, so that my journal doesn't have permanent holes where the messy songs were.
8. As the owner, I am fine with a backfilled track being **appended** to the playlist rather than
   restored to its exact position, so that the feature stays simple and robust.
9. As the owner, I want re-pasting the same playlist to update the _same_ Jellyfin playlist, so that
   I can paste a month repeatedly as it grows without creating duplicate playlists.
10. As the owner, I want a song I already have (exact same YouTube video) to be skipped rather than
    re-downloaded, so that re-pasting is fast and doesn't duplicate files.
11. As the owner, I want an already-have song to still be _added to the new playlist_, so that a song
    from July that reappears in August shows up correctly in both months.
12. As the owner, I want "already have this exact video" detected only on an **exact video-ID match**,
    so that the app never silently swaps one song for a different upload it merely guessed was "the
    same," leaving an invisible hole in my journal.
13. As the owner, I accept that a genuinely _different upload_ of a song I own may occasionally land
    as a duplicate file, so that I never lose a wanted song to an over-eager match.
14. As the owner, I want the playlist named automatically from the YouTube title, so that I don't
    have to type anything to keep the walk-away flow.
15. As the owner, I want to watch a 50-song batch through **one card**, so that I'm not scrolling a
    wall of 50 separate cards.
16. As the owner, I want that card to show at a glance _how far along_ and _what needs my attention_,
    so that I can triage a finished batch in seconds.
17. As the owner, I want the one song currently processing shown live, so that a long grind feels
    alive rather than hung.
18. As the owner, I want messy/parked songs shown as "still filling in" and failures shown as
    "gone / unavailable" rather than as alarms, so that my music journal doesn't feel like an error
    console.
19. As the owner, I want a failed song (deleted / region-locked video) to _not_ stop the rest of the
    batch, so that one bad video doesn't cost me the other 49 (ADR-002).
20. As the owner, I want the batch view to survive a page reload, so that I can genuinely walk away
    and come back to a long-running batch.
21. As the owner, I want a re-paste where most songs are already landed to read as a quiet "45 already
    here, 3 added, nothing wrong," so that the common case isn't visual noise.
22. As the owner, I want a finished batch that still has parked songs to read as **"waiting on you,"**
    not "done," so that I don't think a month is complete while messy tracks are still unfiled.
23. As the owner, I want album art on the tracks in the batch view, so that it feels like _my_ month,
    not a systems dashboard.
24. As the owner, I want an artist to land under a single canonical folder, so that Jellyfin shows one
    artist page with the full discography (T-037).
25. As the owner, I want a fresh download to never re-introduce a mangled artist folder
    (`JAŸ-Z` and variants), so that fixing the library once actually stays fixed (T-037 defect 1).
26. As the owner, I want the progress card to report the genre it actually wrote, so that a card
    doesn't claim "no genre" on a file that has one (T-037 defect 2 reporting bug).
27. As the owner, I want single-song acquire (R1) to behave _exactly_ as before, so that adding
    playlists doesn't regress the everyday single paste.

---

## Implementation Decisions

### Batch model — one playlist, many track-jobs, one stream

- **A batch reuses the per-song job.** Each track in a playlist is still its own `jobs` row, so the
  entire R1/R1.1 per-song pipeline **and the review lifecycle are reused unchanged**. Tracks in a
  batch are grouped by a shared playlist reference.
- **New `playlists` entity.** A durable table keyed by the **YouTube playlist ID** (unique),
  carrying the derived title and the created Jellyfin playlist ID. Fields (shape, not SQL):
  `id`, `youtube_playlist_id` (unique), `title`, `jellyfin_playlist_id` (nullable until created),
  `created_at`.
- **`jobs` gains a nullable `playlist_id`.** Null = a single-song paste → **R1's flow is byte-for-byte
  unchanged** (this is the switch that keeps R1 untouched). Non-null = a member of a batch. The job
  also carries a stable **`position`** (its index in the expanded playlist) and its source
  **YouTube video ID**.
- **One SSE stream per batch, not per track.** A 50-track batch must not open 50 `EventSource`s — the
  browser caps ~6 connections per origin, so 50 cards would leave 44 streams dead. The batch view
  opens **one** stream keyed by the playlist, and the server fans each track's pipeline events onto
  that playlist-scoped channel, **each event stamped with the track's `position`/job id**. Reuses the
  existing keyed event-bus mechanism.
- **This data model is a new ADR** (batch entity + `playlist_id` FK + the backfill chain below). It
  must be recorded and settled **before the design gate**, because retrofitting the association into
  live job data later is unrecoverable.

### Accepting and expanding a playlist

- **Relax the `422`.** `POST /api/jobs` currently refuses a playlist URL by shape. R2 accepts a
  playlist URL, creates/reuses the `playlists` row, expands the playlist via **yt-dlp** into its
  entries, and enqueues one track-job per entry with the shared `playlist_id` and `position`.
  Single-song URLs continue to enqueue a single `playlist_id = null` job (R1 path).
- **Playlist title is derived, not entered.** The name comes from the YouTube playlist's own title
  (available from the same yt-dlp metadata fetch). No user naming in R2 (see Out of Scope).

### De-duplication (exact video only)

- **Match on YouTube video ID, exactly. Never fuzzy.** On expansion, each entry's video ID is checked
  against the library's record of already-landed videos.
  - **Hit** → skip download/transcode/identify/tag entirely; **add the existing canonical file to the
    playlist**; emit a `track.skipped` event. This is **silent** — it must _not_ route through the
    ADR-009 duplicate-park path (that path is for a different-bitrate library duplicate offered for a
    keep/replace choice; a re-paste of a video already in _this_ library is just "already have it").
  - **Miss** → normal pipeline. A genuinely _different upload_ of a song already owned is treated as
    new (accepted duplicate-file risk — see story 13).
- **Requires the source video ID to be durably recorded** at landing, so "do I already have this
  video?" is answerable without guessing.

### Jellyfin playlist output (new seam)

- **`jellyfin.py` gains playlist create/append.** Today it only triggers a library scan. R2 adds:
  create-playlist (by name), resolve a landed file → its Jellyfin item ID, and append an item to a
  playlist. These extend the single existing Jellyfin seam — no second integration point.
- **Append as tracks land**, one at a time (matches the sequential pipeline). A parked-then-resolved
  track appends on resolve (backfill).
- **Timing seam to handle:** a Jellyfin item ID exists only _after_ Jellyfin has scanned the new
  file, and the scan is async on Jellyfin's side. The append must wait for/resolve the item post-scan;
  this ordering is part of the seam and must be specified in the ADR.
- **App-side membership is the source of truth.** An app-side playlist↔track membership record — not a
  per-re-paste query back to Jellyfin — answers "is this already in this playlist?" for the idempotent
  re-paste, and feeds the aggregate counters and backfill. One store, read three ways.

### Backfill (review → playlist)

- **The locked chain:** `review → job → playlist → jellyfin_playlist_id`. When a parked track is
  resolved through the existing `/api/reviews` resolve path and lands, the resolve's landed branch
  looks up the job's `playlist_id`; if present, it **appends** the newly-landed track to that Jellyfin
  playlist.
- **Append to end. Position is not preserved.** Exact in-playlist order is not restored on backfill
  (owner decision — within a monthly journal, order carries little meaning and insert-at-index is
  fiddly for no real gain). Original `position` is still recorded so the list isn't _actively_
  scrambled, but no effort is spent re-inserting.
- **Batch is not "done" while parked > 0.** A finished grind that still has tracks in review reports a
  terminal state of **"waiting on you,"** not complete — so the owner doesn't read a month as finished
  while messy tracks are unfiled.

### Batch view (UI) — "Hybrid": triage bones, journal warmth

- **One aggregate playlist card** in the existing `.deck` layout (no router). Shape signed off in
  direction at the grilling; **exact screens go through the design gate (ADR-016) before component
  code** — flat HTML scenario screens including the ugly states (a failed song, "N in review", a
  just-started batch, a mostly-already-done re-paste).
- Contents: an aggregate progress meter + outcome tally (landed / in-review / failed / skipped /
  queued); the single currently-processing track shown live; the rest bucketed by outcome with the
  **"needs you"** bucket hoisted to the top; **album art** on track rows; parked/failed rendered as
  "still filling in" / "gone", not error-red.
- Reuses the shipped visual language (the console skin, ADR-018 — "Signal Path" is its superseded
  predecessor) and the existing review-inbox resolve seam. Single-song R1 acquire keeps its existing card.

### New SSE events

Names to add (stable; batch-scoped stream, each stamped with track `position`/job id):

- `batch.queued` → the batch started; carries playlist title and total track count.
- `track.skipped` → an entry was already in the library (exact video match); carries the track that
  was added to the playlist without re-processing. **Required for the idempotent re-paste view.**
- `batch.progress` → aggregate tally (landed / review / failed / skipped / queued) for the card.
- Existing `track.*` events (`track.downloading`/`identifying`/`review_required`/`done`/`error`, etc.)
  ride the batch stream unchanged **plus** the track `position`/job id stamp.

### T-037 — artist-credit normalisation (in scope)

- **Defect 1 (the split): fix it in the pipeline.** The cause is diagnosed: MusicBrainz's canonical
  credit for the artist uses a Unicode hyphen (U+2010), and the `Y` is being mangled to `Ÿ` (U+0178)
  in the write path — riding the _matched-metadata_ path (both mangled items carried `mb_trackid`s).
  R2 adds a **canonical artist-credit normalisation step in the write/path-format path** so no fresh
  download re-introduces a mangled folder. **This binds every path the app writes → it is a new ADR**
  (the fold `Ÿ→Y` and the hyphen decision recorded there). The one-time library sweep for existing
  mangled folders is _already done_ for Jay-Z (recipe in the T-037 ticket) — not re-litigated here.
- **Defect 2 (missing genre): mostly closed, one real bug.** The T-103 verify already refuted the
  plugin/key-regression theories (`lastgenre` + `LASTFM_APIKEY` proven working); a bare genre is
  per-recording Last.fm coverage, not a defect (and `album` absence is correct per ADR-010). The one
  genuine bug to fix: **`Outcome.tags` under-reports the genre** it just wrote (snapshot taken before
  `lastgenre` writes), so the card claims "no genre" on a file that has one. Fix the reporting
  snapshot so `track.done` carries the genre actually written.

---

## Testing Decisions

**What a good test is here:** it drives the feature the way the owner does and asserts the
_observable result_ — events emitted, tracks landed, playlist membership — never a private function or
a DB row shape. Prior art: the R1/R1.1 route+SSE tests in `server/tests/` and the `/verify` playbook
(`docs/workflow.md` + the `/verify` skill), which drive the real flow against `TestClient` or the
running server with an **isolated `DB_PATH` + temp beets library**.

- **Seam 1 — HTTP + SSE (primary, existing seam).** `POST /api/jobs` with a playlist URL → assert the
  batch stream's `track.*` / `batch.*` / `track.skipped` events, the landed tracks, the parked tracks,
  and playlist membership. This is the single highest seam and covers most of R2. Isolated DB + temp
  beets library, per `/verify`.
- **Seam 2 — Jellyfin boundary (stubbed).** The app→Jellyfin create-playlist / append-item calls are
  tested against a **stub** at the `jellyfin.py` module edge — assert the app _calls_ them with the
  right playlist name and item, without touching a real Jellyfin. The **real** Jellyfin is exercised
  only in a `/verify` run, where the observable artifact is the playlist actually appearing.
- **Backfill via behaviour, not introspection.** Park a track, resolve it through `/api/reviews`, and
  assert it **appended to its playlist** — proving the `review → job → playlist` chain through what
  the owner would see, not by reading the `playlists` table.
- **Idempotent re-paste.** Run a playlist, then run it again with one added entry: assert the first
  run's tracks emit `track.skipped` (not re-downloaded), the one new entry processes, and the Jellyfin
  playlist is the _same_ one (not duplicated).
- **Dedup safety.** Assert an exact video-ID match skips + adds-to-playlist, and that no fuzzy match
  is attempted (a different video is processed as new).
- **T-037 normalisation.** Feed a matched credit that reproduces the `Y→Ÿ`/U+2010 case and assert the
  **landed path uses the canonical single folder** — the regression guard that a fresh write never
  re-splits the artist. Assert `track.done`'s reported genre equals the genre on disk (defect 2
  reporting fix).
- **R1 non-regression.** A single-song URL still enqueues a `playlist_id = null` job and behaves
  exactly as R1 — no batch, no playlist, unchanged card.

**Observable artifact (DoD step 3):** a `/verify` run pastes a small real playlist end-to-end and
confirms the real side effects — files landed canonically, the Jellyfin playlist created and
populated, a parked track backfilling on resolve.

---

## Out of Scope

- **Migrate / clean the existing library** — split to a later release (**R2.5**). This includes the
  scattered-source reality (music on the laptop, on a phone SD card, possibly phone storage) captured
  during the grilling as R2.5 input. R2 is acquisition only.
- **Loose multi-URL paste** (paste 3 song URLs, no playlist) — a different, lighter feature; deferred.
- **"Recently Added" rolling playlist** — needs a maintained/recomputed playlist mechanism R2's static
  playlists don't; deferred.
- **User-named playlists** — considered and rejected for R2; the name is derived from the YouTube
  title to keep walk-away friction at zero.
- **Preserving exact in-playlist position on backfill** — append-only (owner decision).
- **Parked backlog tickets not required for R2 exit** — per the roadmap scope gate: **T-034** (query
  normalisation), **T-035** (Shazam tier), **T-042** (ReplayGain loudness), **T-023/T-030** (lyrics
  second-scan), **T-031** (album recovery), **T-032** (reload restore for singles), **T-039** (inbox
  loading indicator), **T-041** (signal-glow reflow). Each rides its own release.

---

## Further Notes

- **Hard constraints hold (ADR-001–005):** sequential processing (a batch is a queue, one live track),
  MP3 320 output, one-failure-continues-the-batch, single-user/no-auth, beets-not-hand-rolled.
- **Two ADRs are prerequisites, both before the design gate:** (1) the batch/backfill data model
  (`playlists` + `job.playlist_id` + the review→playlist append + the Jellyfin item-ID timing seam);
  (2) the T-037 canonical artist-credit normalisation. The mockups encode these — writing them after
  the gate means re-mocking.
- **Design gate (ADR-016) applies** — this changes a user-visible flow/state, so flat HTML scenario
  screens (including failure/edge states) are published for owner sign-off _before_ component code.
- **T-037 filing:** `git mv docs/backlog/T-037.md` into R2's tickets when tickets are generated;
  roadmap already lists migrate as R2.5-bound.
- **Acceptance checklist (R2 is "done" when…)** — to expand into `docs/r2/tickets.md`:
  - [ ] Pasting a playlist URL expands it and processes every track sequentially over one SSE stream.
  - [ ] A Jellyfin playlist named after the YouTube title is created and populated as tracks land.
  - [ ] Each file lands canonically under `Artist/Album`; one copy on disk, playlist holds pointers.
  - [ ] A parked track resolved later appends to its playlist automatically.
  - [ ] Re-pasting the same (grown) playlist updates the same Jellyfin playlist, skips already-have
        videos silently, and adds only new entries.
  - [ ] An exact-video duplicate is skipped and added to the playlist; no fuzzy matching occurs.
  - [ ] A failed track doesn't stop the batch; the batch reads "waiting on you" while parked > 0.
  - [ ] The batch view is one aggregate card (design-gate screens signed off first).
  - [ ] A fresh download of a T-037-class artist lands under the single canonical folder.
  - [ ] `track.done` reports the genre actually written to disk.
  - [ ] Single-song acquire (R1) is unchanged.
  - [ ] Suites green on `main`; a `/verify` run shows the real playlist created and backfilled.
