# R1 Tickets — CleanMuzik

> **Status: GENERATED — 2026-07-12, from `spec.md` (owner signed off).** These decompose the
> R1 spec into build-order tickets. Each ties back to a §7 acceptance item. Do not add scope
> that isn't in the spec; if a ticket needs a decision the spec doesn't make, stop and amend
> the spec first.

Ticket format (one block each, kept in this file — no GitHub Issues):

```
### T-001 — <short title>
- **Status:** todo | in-build | in-review | done
- **Depends on:** T-000 (or "none")
- **Agent:** which sub-agent / skill this suits (build, front-end, etc.)
- **What:** the concrete job, scoped small enough to finish in one sitting
- **Done when:** the check that proves it — ties back to a spec acceptance item
```

**Build order.** Three phases: **A — engine spine** (prove download → transcode → identify →
tag → land via scripts, no web layer yet), **B — API + orchestration** (job queue, SSE, review
endpoints), **C — UI**. Plus setup + a final verify pass. The spine is provable on its own before
any FastAPI/React exists — build it first, exactly as the spike proved the seam.

Definition of Done per ticket is the repo rule: `/code-review` on the diff, `/verify` the real
side effect for pipeline tickets, transcribe corrections to `docs/learnings.md`.

---

## Phase A — engine spine

### T-001 — FastAPI backend skeleton; drop Express
- **Status:** done (2026-07-12; `/code-review` high-effort passed — 4 doc/cleanup fixes applied, `httpx2` + PORT findings rejected with evidence)
- **Depends on:** none
- **Agent:** build
- **What:** Stand up the Python/FastAPI service that replaces `server/`. Project layout (e.g.
  `server/app/`), `uvicorn` run command, `GET /api/health` → `{ "status": "ok" }`, `.env` loading
  (python-dotenv or pydantic-settings reading the keys in spec §6). Remove the Express scaffold.
  Document the `uvicorn` invocation in `CLAUDE.md` (the placeholder there expects it).
- **Done when:** `uvicorn` boots, `GET /api/health` returns ok, `.env` values are readable in
  process, and `server/`'s Express code is gone. (Spec §6 `/api/health`.)

### T-002 — SQLite persistence layer
- **Status:** todo
- **Depends on:** T-001
- **Agent:** build
- **What:** Create the SQLite store and the two tables from spec §6: `jobs(id, url, status,
  created_at)` and `reviews(id, job_id, staging_path, query, candidate_ids_json, rec, status)`.
  Thin DAO/repository for create/read/update. Store candidate **IDs**, never rich objects
  (ADR-006 corollary / spec §5). DB lives on disk so it outlives a reboot.
- **Done when:** rows can be written and read back after a process restart; schema matches §6.
  (Spec §7 "restarting the backend preserves parked reviews".)

### T-003 — beets programmatic config + plugin loading (ADR-007)
- **Status:** todo
- **Depends on:** T-001
- **Agent:** build
- **What:** Ship the beets config the backend drives: `directory` +
  `paths` from spec §6 disk-layout block, `plugins: musicbrainz chroma lastgenre fetchart
  embedart lyrics`, and an **explicit `beets.plugins.load_plugins()` at startup** (ADR-007 — the
  library API does not auto-load; without it matching silently degrades to tag-only). **Pin the
  beets version** (2.12; treat an upgrade as re-testing the seam, per architecture.md). Confirm
  `fpcalc` is resolvable (Chromaprint), as in the spike.
- **Done when:** a boot-time smoke check confirms all six plugins loaded and `chroma` can reach
  `fpcalc`; a known song fingerprints and returns MusicBrainz candidates (proves musicbrainz +
  chroma wired). (Spec §2 plugin list; ADR-007.)

### T-004 — yt-dlp download stage + playlist rejection
- **Status:** todo
- **Depends on:** T-001
- **Agent:** build
- **What:** Given one YouTube **song** URL, download bestaudio with **`--embed-metadata`** into a
  staging dir (a bare `-x` rip strips tags → empty MusicBrainz query → HTTP 400, per learnings).
  Detect a **playlist URL and reject it** (the classifier the `POST /api/jobs` 422 will use).
  Staging-dir creation + path returned for the next stage.
- **Done when:** a song URL yields a tagged staging file; a playlist URL is refused (not expanded).
  (Spec §7 "playlist URL is rejected"; §4 download note.)

### T-005 — ffmpeg transcode → MP3 320 CBR
- **Status:** done
- **Depends on:** T-004
- **Agent:** build
- **What:** Transcode the staged audio to **MP3 320 CBR** via `ffmpeg` (ADR-002 — that format and
  only that). Preserve the embedded metadata from T-004.
- **Done when:** output probes as MP3 320 kbps CBR with tags intact. (Spec §7 landed file is MP3
  320 CBR; ADR-002.)

### T-006 — Title normalization
- **Status:** done (2026-07-13; `/code-review` high workflow-backed — 7 findings, all applied: artist-aware prefix strip + empty-query guard + token-set promo detection + pipe-tail stripping)
- **Depends on:** T-005
- **Agent:** build
- **What:** Before matching, strip `(Official Audio)` / `(Official Video)` / `(Lyrics)` cruft and a
  leading `Artist - ` prefix (learnings: promotes the correct candidate to #1). Pure function,
  unit-testable; feeds the beets query.
- **Done when:** the spike's known-song titles normalize to the strings that promoted the right
  candidate; unit tests cover the cruft patterns. (Spec §2 title normalization.)

### T-007 — beets import seam: ImportSession subclass + fingerprint-trust gate (ADR-006)
- **Status:** done — uncommitted (2026-07-14; two `/code-review` high workflow passes applied. Open question RESOLVED — beets' chroma **discards** the AcoustID score, so the seam reads it via its own `acoustid.lookup`. **Door B**: added singleton cover art (`artwork.py`, CAA→iTunes) since `fetchart` skips singletons. Verified end-to-end: a-ha "Take On Me" auto-landed MP3 320 + tags + synced lyrics + CAA cover; weak song parked. 158 tests green.)
- **Depends on:** T-002, T-003, T-005, T-006
- **Agent:** build
- **What:** The product's spine. Subclass `beets.importer.ImportSession`, import the file **as a
  singleton**, override `choose_item(task)`: read the AcoustID result behind the top candidate;
  **auto-accept when the top match's score is high AND the gap to the runner-up is wide**
  (dominant → apply, land under §6 `paths`); otherwise record candidate **IDs** + `task.rec` to
  the `reviews` table and return `Action.SKIP` to park it. **Drive the importer** so
  chroma/lastgenre/fetchart/embedart/lyrics run as stages — never call `autotag.tag_item`
  directly (ADR-005). Do **not** lower `strong_rec_thresh` globally (ADR-006). Runs off the event
  loop (worker-thread-safe; T-012 owns the thread). Use the candidate thresholds (score ≥ 0.90,
  gap ≥ 0.10) as a starting knob — T-008 tunes them.
- **Done when:** a dominant-fingerprint song auto-lands a tagged **MP3 320** with embedded cover
  art, year, and lyrics (genre when `LASTFM_APIKEY` is set) under
  `…\CleanMuzik\<Artist>\…`; a weak/ambiguous song is parked as a `reviews` row with candidate IDs
  and nothing lands. (Spec §7 dominant auto-tags zero clicks; landed-file tags; weak → review.)

### T-008 — Tune + record fingerprint score/gap thresholds
- **Status:** done (2026-07-14; measured 25 real songs — owner library + YouTube playlist. **22 correct auto-accepts, 0 wrong, 3 genuine no-matches**; correct matches all 0.955–0.995, no-matches 0.0. Tuned: **SCORE_MIN=0.90 held, GAP_MIN=0.0** — the gap check never once helped (a high runner-up was always the same song listed twice in AcoustID), kept as an off-by-default knob. Re-measured auto-accept ≈88%, written into ADR-006 addendum. Experiment published as primer A3. Findings + AcoustID-key correction transcribed to learnings.md.)
- **Depends on:** T-007
- **Agent:** build
- **What:** The ADR-006 build-time knob. Run a **larger sample** of real YouTube songs through
  T-007, measure the auto-accept rate and where correct/incorrect matches fall on score+gap, set
  the dominance thresholds, and expose them as config (not hard-coded blind). Record the chosen
  numbers + the re-measured auto-accept rate back into ADR-006 (it explicitly asks for this).
- **Done when:** thresholds are set from measurement, live in config, and the re-measured rate is
  written into `docs/r1/adr.md`. (ADR-006 "must be re-measured … once the fingerprint-trust rule
  exists".)

### T-009 — Acquire-time duplicate handling (`get_duplicate_action`)
- **Status:** done — non-destructive per ADR-009 (never auto-deletes; higher-bitrate upgrade → review)
- **Depends on:** T-007
- **Agent:** build
- **What:** In `choose_item`, when the accepted song matches one already in the library by MusicBrainz
  recording id (a **direct `MatchQuery` against the library** — beets' own import duplicate stage can't
  see MBID dupes; see ADR-009 / learnings), keep the existing copy when it's at **>= bitrate** (drop
  the redundant download, no second copy), else **park the strictly-higher-bitrate upgrade to the
  review queue** ("you already have this — keep which?"). **Non-destructive: never auto-deletes**
  (ADR-009, supersedes spec §5's "drop the other" + tag-richness tie-break, which is deferred to R2
  migrate). Full cross-library acoustic dedup is R2.
- **Done when:** re-pasting the **same** URL is caught (no silent second copy) and the existing copy
  is kept; a constructed higher-bitrate case routes to review. (Spec §7 duplicate item; ADR-009.)

### T-010 — Jellyfin scan trigger
- **Status:** todo
- **Depends on:** T-007
- **Agent:** build
- **What:** After a track lands, call the Jellyfin scan API (`JELLYFIN_URL` + `JELLYFIN_API_KEY`
  from `.env`) so it appears in seconds. If either is missing, **degrade to a logged warning** —
  the track still lands on disk (spec §6 missing-key behaviour). No manual scan.
- **Done when:** a landed track appears in Jellyfin within seconds via the app-triggered scan;
  with the key unset, landing still succeeds and logs a warning. (Spec §7 "appears in Jellyfin
  within seconds"; ADR-008.)

### T-011 — Identify-stage retry with backoff
- **Status:** done (2026-07-14; retry only the lookup — fingerprint generated once — with exponential 1→2→4s backoff on transient `AcoustidLookupError`; owner's `acoustid_apikey` wired into `fingerprint_dominance` via `_resolve_api_key` (private quota, shared key as fallback). `/code-review` high workflow-backed: 5 findings, load-bearing one applied — classify AcoustID errors by code, so an invalid key raises a non-retryable `AcoustidPermanentError` (fail fast + ERROR log) instead of burning 7s and silently mass-parking. 167 tests green.)
- **Depends on:** T-007
- **Agent:** build
- **What:** Wrap the AcoustID/identify lookup in **retry-with-backoff** before calling it a
  failure — AcoustID is flaky/rate-limited, and `chroma` swallows lookup errors so a failed lookup
  otherwise masquerades as "no match" (learnings). Respects ADR-001's between-request delay.
- **Done when:** a simulated transient AcoustID error retries and recovers rather than parking a
  matchable song as "no match". (Spec §5 failure-of-one-stage / retry note.)

## Phase B — API + orchestration

### T-012 — Job orchestration: worker thread + sequential queue + job routes
- **Status:** todo
- **Depends on:** T-004, T-005, T-007, T-010
- **Agent:** build
- **What:** Wire the stages into one job run on a **worker thread** (never the asyncio event
  loop). `POST /api/jobs {url}` → create a `jobs` row, **reject a playlist URL with 422** (uses
  T-004's classifier), return `{ job_id }`. `GET /api/jobs/{job_id}` → status snapshot (reconnect
  fallback). Sequential, one track at a time (ADR-001). On **any stage failure**: catch it, mark
  the stage, and **clean up the staging file** (SSE emission is T-013).
- **Done when:** posting a song URL runs the full spine to a landed file on a worker thread; a
  playlist URL returns 422; a forced stage failure cleans up staging and records the failing
  stage. (Spec §6 `/api/jobs`; §7 playlist-rejected + forced-failure-cleanup.)

### T-013 — SSE stream + event emission through stages
- **Status:** todo
- **Depends on:** T-012
- **Agent:** build
- **What:** `GET /api/jobs/{job_id}/events` streams the spec §6 event catalogue —
  `job.queued`, `track.downloading`, `track.transcoding`, `track.identifying`,
  `track.review_required`, `track.tagging`, `track.done`, `track.error`, and a periodic `ping`
  keepalive. Each stage in T-012 emits its event with the exact payload shape from §6. **No
  polling** (ADR / spec).
- **Done when:** driving a job emits the full ordered event sequence over SSE with correct
  payloads; `track.error` names the stage; `ping` keeps the stream alive. (Spec §7 SSE live
  progress; §6 event catalogue.)

### T-014 — Review API: list + resolve + resume import
- **Status:** todo
- **Depends on:** T-007, T-013
- **Agent:** build
- **What:** `GET /api/reviews` → parked reviews `[{ review_id, job_id, query, candidates[] }]`
  (candidates re-hydrated from stored MusicBrainz **IDs**, spec §5). `POST
  /api/reviews/{review_id}/resolve {choice: "<candidate_id>"|"reject"}` → resume the import
  applying the chosen candidate (land it) or discard on reject; emit the tail SSE events. Parked
  reviews **survive a backend restart** (reads T-002's table).
- **Done when:** a parked song lists with its candidates; accepting a candidate lands it, rejecting
  discards it; both work **after a backend restart**. (Spec §7 weak→review pick/reject; restart
  preserves reviews; §6 review routes.)

## Phase C — UI

### T-015 — Frontend shell: paste URL + Go → create job
- **Status:** todo
- **Depends on:** T-012
- **Agent:** front-end
- **What:** Replace the stock Vite template. A single input for one YouTube song URL + **Go** →
  `POST /api/jobs`, then render an empty **track card** for the returned `job_id`. Surface the 422
  playlist rejection as a readable message.
- **Done when:** pasting a URL and clicking Go creates a job and shows a track card; a playlist URL
  shows the rejection, not a silent expand. (Spec §4 step 1–2.)

### T-016 — Track card: SSE consumer + per-stage animation
- **Status:** todo
- **Depends on:** T-013, T-015
- **Agent:** front-end
- **What:** The track card subscribes to `GET /api/jobs/{job_id}/events` and animates through
  **download → transcode → identify → (auto-tag | review) → done**, keyed off the SSE event names
  (§6). Shows matched title/artist/album + art on `track.tagging`, final path + tags on
  `track.done`, and a **per-stage error** on `track.error`.
- **Done when:** a real job animates live end to end over SSE with no polling; error state names
  the failing stage. (Spec §7 SSE live progress + forced-failure error; §4 step 3.)

### T-017 — Review panel UI
- **Status:** todo
- **Depends on:** T-014, T-016
- **Agent:** front-end
- **What:** When a card flips to **Needs review** (`track.review_required`), show the candidate
  matches — per candidate: **title, artist, album, year, cover thumbnail** — plus the normalized
  query. Owner actions: **accept top**, **pick alternate**, **reject** → `POST
  /api/reviews/{id}/resolve`. On resolve, the card resumes to Landing/Done. Reuse the same panel
  for the ambiguous-duplicate case (T-009).
- **Done when:** a parked song's candidates render; accept lands it and the card completes, reject
  discards it. (Spec §7 weak→review pick/reject; §5 review-queue fields.)

## Setup + verification

### T-018 — Owner setup: Last.fm API key
- **Status:** todo
- **Depends on:** none
- **Agent:** owner
- **What:** Owner obtains a Last.fm API key and puts it in `.env` as `LASTFM_APIKEY` so
  `lastgenre` can fetch genres. Until then, tracks land with every other tag — **absent key is not
  a failure** (spec §6). AcoustID needs no personal key (built-in works, proven in the spike).
- **Done when:** `LASTFM_APIKEY` is set and a landed track carries a genre tag. (Spec §6 secrets
  table; §5 output.)

### T-019 — End-to-end verify pass against the §7 acceptance checklist
- **Status:** todo
- **Depends on:** T-016, T-017, T-010, T-014
- **Agent:** verify
- **What:** Drive the real flow and observe side effects for **every** §7 acceptance item —
  including the ones no single ticket owns end to end: dominant song auto-lands zero-click; weak
  song reviews and resolves; landed file is MP3 320 with art/genre/year/lyrics; appears in Jellyfin
  in seconds; duplicate caught; forced failure names the stage + cleans up; restart preserves
  reviews; playlist rejected; **everything on `localhost`, nothing exposed to the network**.
  Transcribe any correction to `docs/learnings.md`.
- **Done when:** every §7 checkbox is proven by `/verify` observing the real side effect (a
  correctly-tagged MP3 320 visible in Jellyfin), not by "the code looks right". (Spec §7, whole
  checklist.)
