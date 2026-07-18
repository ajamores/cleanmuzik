# R1 Tickets — CleanMuzik

> **Status: GENERATED — 2026-07-12, from `spec.md` (owner signed off).** These decompose the
> R1 spec into build-order tickets. Each ties back to a §7 acceptance item. Do not add scope
> that isn't in the spec; if a ticket needs a decision the spec doesn't make, stop and amend
> the spec first.

Ticket format (one block each, kept in this file — no GitHub Issues):

```
### T-001 — <short title>
- **Status:** todo | in-build | in-review | **built** | done
  - **built** = code finished and its checks pass *in isolation* (worktree/branch), NOT yet on `main`.
  - **done** = built **and integrated onto `main`**, suite green there. "Done" always implies landed —
    a ticket verified in a worktree but not merged is **built**, never done (owner convention, 2026-07-17).
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
- **Status:** done (2026-07-12; `b612115`. SQLite `jobs` + `reviews` per spec §6; stateless DAO; candidate MBIDs stored as JSON not objects (ADR-006); schema init in lifespan; DB on disk survives restart. `/code-review` high: 4 applied — FK-enforce pragma, WAL, rowcount guards on both updates; 2 rejected as deliberate.)
- **Depends on:** T-001
- **Agent:** build
- **What:** Create the SQLite store and the two tables from spec §6: `jobs(id, url, status,
  created_at)` and `reviews(id, job_id, staging_path, query, candidate_ids_json, rec, status)`.
  Thin DAO/repository for create/read/update. Store candidate **IDs**, never rich objects
  (ADR-006 corollary / spec §5). DB lives on disk so it outlives a reboot.
- **Done when:** rows can be written and read back after a process restart; schema matches §6.
  (Spec §7 "restarting the backend preserves parked reviews".)

### T-003 — beets programmatic config + plugin loading (ADR-007)
- **Status:** done (2026-07-12; `88e17a0`. Builds the beets config + explicit `load_plugins()` (ADR-007 — all six load, proven); optional keys wired; boot smoke check logs a receipt or warns DEGRADED; beets pinned 2.12. `fpcalc` v1.5.1 installed to `~/.local/bin`. `/code-review` high: 4 applied — beets imported in lifespan not module-top, false-green-fpcalc guard, WSL isfile vs X_OK, subprocess via to_thread.)
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
- **Status:** done (2026-07-12; `57e6517`. yt-dlp bestaudio + `--embed-metadata` into staging (no MP3 transcode — that's T-005); pure playlist classifier feeding T-012's 422. 17 unit tests + `pytest.ini`. Live download verified. `/code-review` high: 2 applied, 1 rejected.)
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
- **Status:** done (2026-07-14; committed `3065731`. two `/code-review` high workflow passes applied. Open question RESOLVED — beets' chroma **discards** the AcoustID score, so the seam reads it via its own `acoustid.lookup`. **Door B**: added singleton cover art (`artwork.py`, CAA→iTunes) since `fetchart` skips singletons. Verified end-to-end: a-ha "Take On Me" auto-landed MP3 320 + tags + synced lyrics + CAA cover; weak song parked. 158 tests green.)
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
- **Status:** done (2026-07-14; `trigger_scan()` POSTs Jellyfin `/Library/Refresh` with `X-Emby-Token` after a track lands. Three-way contract per spec §6: True = scan requested; False = degraded (missing/whitespace-only config → warn, track still landed — absent is not a failure); raise `JellyfinScanError` = configured but the call failed, so T-012 emits `track.error` stage=`scan`. Verified against LIVE Jellyfin: valid → 204 → True; bad key → 401 → raise. `/code-review` high: 4 applied, 1 rejected. Wired into the job run by T-012.)
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
- **Status:** done + VERIFIED LIVE (2026-07-15; `1c14f3a`. The Phase B keystone — `run_pipeline` walks download→transcode→normalize→`import_song`→Jellyfin-scan sequentially on a single `JobWorker` thread draining a `queue` (ADR-001: `POST /api/jobs` only *enqueues*). Two state homes: durable `jobs.status` in SQLite + an in-memory `JobRegistry` (capped 256) for live stage detail; the GET snapshot overlays them. Boot reconciliation (`fail_unfinished_jobs`) marks crash-orphaned jobs `error`. `/code-review` high: 10 verified findings applied — load-bearing catch was a **data-loss bug** (a committed park's staging file being `rmtree`d by the land-error handler). `/verify` PASS: a-ha landed `CleanMuzik/a‐ha/Take On Me.mp3`, 320000 CBR, embedded cover. 204 tests green.)
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
- **Status:** done + VERIFIED LIVE (2026-07-16; `6a7675e`. `server/app/events.py` — `EventBus` thread→event-loop bridge; per-job `_JobChannel` = replay buffer + `closed` flag + subscriber queues; `publish()` fans out via `loop.call_soon_threadsafe` outside the lock; `stream()` snapshots buffer AND registers its queue under one lock so an event lands in exactly one of replay/live. Hand-rolled SSE (no sse-starlette) so `ping` is a real named event; `/events` stays import-light. `/code-review` high: 6 verified — load-bearing catch was a **hang-forever bug** (evicted-channel reconnect → pings forever; fixed via a durable `terminal` hint → learnings.md). `/verify` PASS: full ordered sequence 3× reproducibly; `track.done.path` proven to be the organized library location. 221 tests green.)
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
- **Status:** done (2026-07-18; integrated onto `main`. High-effort review found 6 findings: #1
  replace-before-scan rollback + #2 torn-row stream-hang fixed with regression tests; #3 failed
  hand-off releases the claim; #4 adjudicated no-code (settle-on-close; T-016 already honours it —
  guard-rail note added below for T-017); #5/#6 cleanups. Suite green (266); `/verify` PASS 26/26
  driving the real app (routes + worker thread + SSE + store + beets, temp-isolated; MB-dependent
  land stubbed as the sandbox can't reach MusicBrainz). The efficiency finding — guard
  `before`/`before_ids` behind `CHOICE_REPLACE` — was applied during the merge.)
- **Depends on:** T-007, T-013
- **Agent:** build
- **What:** `GET /api/reviews` → parked reviews `[{ review_id, job_id, query, rec, candidates[] }]`
  (candidates re-hydrated from stored MusicBrainz **IDs**, spec §5; `rec` tells the client which
  question the row is asking). `POST /api/reviews/{review_id}/resolve` → resume the import and emit
  the tail SSE events. **Two body shapes, per spec §6** — validate against the row's `rec`, 400 a
  mismatch:
  - weak match → `{choice: "<candidate_id>"}` lands it, `{choice: "reject"}` discards.
  - duplicate → `{choice: "keep_existing"|"replace"|"keep_both", suffix?}` (ADR-009 addendum).
    `replace` lands the upgrade **then** deletes the old file (never the reverse — the ADR-009
    data-loss window); `keep_both` appends the owner's `suffix` to the **title tag**, not the
    filename, and lets beets derive the path.

  Staging cleanup is **T-014's job, at resolve time, on every branch** (spec §5 retention rule — a
  parked song keeps its staging file; it *is* the copy being resolved). Parked reviews **survive a
  backend restart** (reads T-002's table).
- **Done when:** a parked song lists with its candidates; accepting a candidate lands it, rejecting
  discards it; each duplicate branch does what it says (and `replace` never leaves zero copies);
  all of it works **after a backend restart**. (Spec §7 weak→review pick/reject + duplicate
  branches; restart preserves reviews; §6 review routes.)

## Phase C — UI

### T-015 — Frontend shell: paste URL + Go → create job
- **Status:** done (2026-07-16; `439fdf3`. Stock Vite template replaced. `App.tsx` owns form state + a newest-first `jobs[]` list; `src/api.ts` `createJob()` POSTs same-origin `/api/jobs` (dev proxy `/api→:8000`); `components/TrackCard.tsx` is the **T-016 seam** — already exports the full `Stage` union matching the §6 event names and owns `useState<Stage>`, so T-016 adds only `EventSource`+`setStage` there. 422 surfaces the server's `detail` inline (`role="alert"`); empty-input + double-submit guarded. `/code-review`: 2 real UX bugs fixed — `type="url"` blocking a schemeless paste (→ learnings.md), and a rejected fetch showing raw "Failed to fetch". lint + build green. Not `/verify`'d live: UI shell, not a pipeline ticket; the browser round-trip rides with T-016.)
- **Depends on:** T-012
- **Agent:** front-end
- **What:** Replace the stock Vite template. A single input for one YouTube song URL + **Go** →
  `POST /api/jobs`, then render an empty **track card** for the returned `job_id`. Surface the 422
  playlist rejection as a readable message.
- **Done when:** pasting a URL and clicking Go creates a job and shows a track card; a playlist URL
  shows the rejection, not a silent expand. (Spec §4 step 1–2.)

### T-016 — Track card: SSE consumer + per-stage animation
- **Status:** built (branch `worktree-agent-aaffef646dc8b8e5c` @ `3885939`); integration in progress
  2026-07-18, **scope reduced**. Two pre-commit review passes found 8 then 10 defects in the stream
  *reattach* logic — the second set including three regressions introduced by the fixes for the
  first. All of it was failure-path behaviour written blind (this sandbox has no sockets), so the
  reattach layer was **cut to T-020** rather than patched a fourth time. What lands here is the SSE
  consumer + rail animation + one snapshot per outage; what does not is any give-up/backoff policy.
  → **done** still needs the live browser round-trip (T-019).
- **Depends on:** T-013, T-015
- **Agent:** front-end
- **What:** The track card subscribes to `GET /api/jobs/{job_id}/events` and animates through
  **download → transcode → identify → (auto-tag | review) → done**, keyed off the SSE event names
  (§6). Shows matched title/artist/album on `track.tagging`, final path + tags on
  `track.done`, and a **per-stage error** on `track.error`.
  *(Amended 2026-07-17: this said "+ art on `track.tagging`" from `4a2f60f` on, but spec §6's
  `track.tagging` payload is `{title, artist, album, year}` — it has never carried art, so the
  requirement was undeliverable as written. `track.done.tags.has_art` is a **boolean**: the card
  shows an "Art" chip meaning art was embedded, not the cover itself. See ADR-010.)*
- **Done when:** a real job animates live end to end over SSE with no polling; error state names
  the failing stage. (Spec §7 SSE live progress + forced-failure error; §4 step 3.)

### T-017 — Review panel UI
- **Status:** todo
- **Depends on:** T-014, T-016
- **Agent:** front-end
- **What:** When a card flips to **Needs review** (`track.review_required`), show the candidate
  matches — per candidate: **title, artist, `score`** — plus the normalized query. **No album/year/
  cover thumbnail (ADR-010: unreachable from a recording lookup — do not add a MusicBrainz round-trip
  to get them).** Owner actions: **accept top**, **pick alternate**, **reject** → `POST
  /api/reviews/{id}/resolve`. On resolve, the card resumes to Landing/Done — note it must open a
  **fresh `EventSource`**, since T-016 closes the stream on `track.review_required` and T-014
  re-opens the channel as a new episode. **That fresh `EventSource` MUST reuse T-016's
  reconcile-on-stream-death fallback (`TrackCard.tsx` `onerror` → one-shot `GET /api/jobs/{id}`),
  not a naive `EventSource`.** `reject` and `keep_existing` close the channel with no terminal
  `track.*` event (the job just goes to `done`), so a naive stream would reconnect-loop forever —
  the settle signal is stream-close + a status snapshot, exactly as the acquire card already does.
  (T-014 code-review finding, adjudicated 2026-07-17: no server change — the contract is
  settle-on-close, and T-016 already honours it; T-017 must not reintroduce the loop.)

  Reuse the same panel for the ambiguous-duplicate case (T-009), which asks a **different question**
  and takes a **different body** (spec §6): `keep_existing` · `replace` · `keep_both` + an
  owner-typed `suffix` (pre-fill something harmless like `(alternate)`). The duplicate side is
  **not** narrowed by ADR-010 — it reads an existing library item, so album/year/art are free.

  **Optimize for fast look-over-and-decide (owner requirement, ADR-009).** The owner accepts doing
  some cases by hand (e.g. `replace` refuses on the rare two-copy case) *on the condition* that
  moving through parked items and deciding is quick — minimal clicks, keyboard-resolvable, no reload
  between items. This is the panel's primary UX bar, not a nicety.
- **Done when:** a parked song's candidates render; accept lands it and the card completes, reject
  discards it; each duplicate branch is reachable and does what it says. (Spec §7 weak→review
  pick/reject + duplicate branches; §5 review-queue fields; ADR-009 addendum.)

## Setup + verification

### T-018 — Owner setup: Last.fm API key
- **Status:** done (2026-07-13; owner's `LASTFM_APIKEY` (32-char) is in the git-ignored repo-root `.env` and verified loaded in-process, so `lastgenre` fetches genres. Last.fm shared secret deliberately NOT stored — it only signs *write* requests; we only read. Follow-up, not a blocker: genre canonicalizes to a generic "Music" — a `lastgenre` whitelist tune.)
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

### T-020 — Track card: stream reattach + the snapshot payload gap
- **Status:** todo — **carved out of T-016 on 2026-07-18 because it could not be verified.**
- **Depends on:** T-016, T-019 (needs a live browser; that's the whole point)
- **Agent:** front-end
- **What:** Give the track card a real recovery story for a stream that stays broken. T-016 ships
  only the platform's own behaviour: EventSource reconnects on a dropped connection, the server
  replays its buffer losslessly, and one snapshot per outage catches the event-less finish
  (duplicate skip, `jobs.py:368`). Deliberately absent: any *give-up* policy, bounded backoff, or
  reattach control. Three attempts at that policy were written blind and two review passes killed
  all three (~12s grace fired instantly on a `uvicorn --reload` blip in one version, never at all
  in another). It is failure-path behaviour and needs a browser that can be taken offline.
- **Also fix here — the payload gap this exposed (spec amendment first, then code):**
  `GET /api/jobs/{id}` returns `job_id, url, status, created_at, stage, review_id, error` — **no
  `path`, no `tags`**. So when a song lands while the stream is down *and* the replay buffer is
  gone (`_CHANNEL_CAP = 256`, and every channel dies on restart), the landing receipt is
  **unrecoverable**: the card can say "Done" but never *where the song went*, which is
  indistinguishable from a duplicate skip where nothing landed. No client-side fix exists — the
  fallback endpoint cannot answer the question the fallback exists for. **Amend spec §6 to add
  `path` + `tags` to the snapshot before building the client half** (ADR-010's rule: don't build
  the nearest thing).
- **Also carried over from T-016's reviews** (deferred, not lost): the `[jobId]` effect resets no
  state on a job change (masked only by `key={job.jobId}` in `App.tsx`); `ERROR_STEP` duplicates
  `RAIL`; `STAGE_STEP.review_required` maps to step 3 ("Tag"), marking Identify complete on the
  very track identify failed to match; `unicode-bidi: plaintext` may defeat the path
  start-truncation.
- **Done when:** a stream killed in DevTools (offline toggle) recovers or reports honestly, a
  `uvicorn --reload` mid-job does **not** detach the card, a landed song shows its path and tags
  after a drop that raced completion, and each is *observed in a browser*, not reasoned about.
