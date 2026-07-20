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
- **Status: DONE** (2026-07-18, `a644c07` on `main`). **Acceptance receipt — run-list row 1,
  observed in a browser:** `Children of Yeshua` / Odeal pasted → rail ran clean through
  Download → Transcode → Identify → Tag → Land → `DONE` badge; title, artist and year on the card;
  final path shown; ART + LYRICS chips; audio stream **exactly 320 kbps** (ADR-002 satisfied —
  `ffprobe -select_streams a:0` reports `bit_rate=320000`; the container-level figure reads ~337k
  because the embedded cover art inflates it, which is not the audio bitrate) with lyrics at
  `/mnt/c/Users/aj_am/Music/CleanMuzik/Odeal/Children of Yeshua.mp3`; and the track appeared in
  Jellyfin **without a manual scan** — the first time the scan nudge has ever fired (it could not
  before; see the `localhost` learning). The **genre chip was absent and that is correct**: Last.fm
  returns zero tags for that 2025 release (verified directly against the API; a control query for
  a-ha/Take On Me returned `80s, pop, new wave, synthpop`), so beets wrote no genre and the card
  showed no chip. Spec §6: a missing genre is not a failure.
- **Integration history:** built on branch `worktree-agent-aaffef646dc8b8e5c` @ `3885939`;
  integrated 2026-07-18, **scope reduced**. Two pre-commit review passes found 8 then 10 defects in the stream
  *reattach* logic — the second set including three regressions introduced by the fixes for the
  first. All of it was failure-path behaviour written blind (this sandbox has no sockets), so the
  reattach layer was **cut to T-020** rather than patched a fourth time. What lands here is the SSE
  consumer + rail animation + one snapshot per outage; what does not is any give-up/backoff policy.
  → **done** needs exactly one thing: **row 1 of the owner-driven run list under T-019**, which is
  this ticket's "Done when" verbatim. The list is parked there because T-019 owns the browser
  session, but row 1 closes *this* ticket, not that one.
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
- **Status:** **DONE (2026-07-19)** — browser receipt discharged; all "Done when" clauses observed
  live. Landed on `main` @ `0e41956`; high-effort `/code-review` done, its 5 findings fixed
  (finding 2 → T-029). Server suite 312 green, client 20 green. Shipped the panel + `rec`-on-SSE
  (spec §6) + the narrow `GET /api/reviews/{id}` the reconcile path re-hydrates from. Was
  **unblocked 2026-07-19 by T-028** (`score` was `null` on every queue row until then; see below).
- **Acceptance receipt — driven live in a real browser (Playwright/Firefox) against a fully
  isolated stack** (temp `DB_PATH` + temp `LIBRARY_DIRECTORY` + blanked Jellyfin key, on `:8100`/
  `:5175`; the owner's real `:8137` server and `/mnt/c/.../Music/CleanMuzik` verified untouched —
  8 files before and after). Fixtures were **real parks**, not seeded rows (there is no queue view
  to surface a seeded row — T-029 note): a sped-up upload (`watch?v=Rxv4IPW1Y2o`) parks as a
  weak match with five real clustered candidates (0.18–0.24); re-downloading a song whose 320 copy
  was manually downgraded to 192k in the sandbox parks as a duplicate. Observed:
  - **weak match** — five candidates render with **match-strength bars** (not raw floats), Reject a
    peer of Accept; **Accept** landed `Moderat/Versions (sped up version).mp3` @ 320k and the card
    completed; **Reject** discarded (review→rejected 404, nothing landed).
  - **duplicate** — panel shows existing 192k vs incoming 320k; **keep_existing** kept the 192k and
    discarded the download; **replace** deleted the 192k then landed 320k (exactly one copy, never
    zero — ADR-009); **keep_both** left two copies with the `(alternate)` suffix in the **title
    tag**, not the filename (spec §5).
  - **load-bearing paths** — resolve settles on stream-close with **one** reconcile snapshot, **no
    reconnect-loop** (the bug two prior review passes caught; confirmed in the network trace); the
    duplicate panel's `GET /api/reviews/{id}` on-mount hydrate rendered correctly; and a **backend
    restart under a live parked card** fully recovered the panel (query + all candidates + actions)
    and the re-hydrated Reject resolved. Zero console errors across the session. (MusicBrainz was
    reachable throughout — see learnings 2026-07-19 — so nothing was stubbed.)
- **Depends on:** T-014, T-016, **T-028**
- **Design input — `score` is the discriminator, but do not render it as a verdict.** Measured on
  the one real parked review (2026-07-19, over live HTTP):

  | candidate | score |
  |---|---|
  | Nines — "Nines SBTV Bars 2015" | 0.4598 |
  | Nines — "Nines Freestyle 2007" | 0.4415 |
  | Bella Ballon — "Super Bella" | 0.4247 |
  | Bella Ballon — "Jij maakt de zomer top" | 0.3635 |
  | Bella Ballon — "Feest voor iedereen" | 0.3403 |

  The top two are **0.018 apart**, the whole field sits in a narrow 0.34–0.46 band, and the right
  answer is plausibly *not in the list at all* (the song is "Outro"). So the real-world shape of a
  parked review is "five weak, similar numbers", not "one clear winner". Consequences for the panel:
  **reject must be as reachable as accept** (it is often the correct action, not the exceptional
  one); don't print raw floats as though 0.4598 beats 0.4415 in any meaningful sense — a bar or a
  coarse band communicates the truth better than four decimal places; and **don't label the top row
  "best match"**, which asserts more than the number supports. ADR-010's "chosen between on `score`
  alone" is the *contract*; this table is what it looks like in practice.
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

#### First owner-driven browser session — the run list (queued 2026-07-18)
**Why now, before T-017:** nothing in this repo has *ever* been run in a browser. Every ticket to
date was verified through `TestClient`, which drives the real pipeline but never touches a proxy, a
DOM, or a live EventSource. The port mismatch found on 2026-07-18 (README 8137 vs Vite proxy 8000,
dead since T-001) is what that blind spot looks like. T-017 will reuse T-016's EventSource pattern,
so a defect in it gets inherited if this waits.

Run (terminal 1) `cd server && ./.venv/bin/uvicorn app.main:app --reload --port 8137`,
(terminal 2) `cd client && npm run dev`, then open the Vite URL.

**The rows close different tickets — this list is filed here for convenience, it is not all T-019.**

| # | Do this | Watch for | Closes | Why it matters |
|---|---|---|---|---|
| 1 | Paste a song that should match cleanly | Rail animates Download → Transcode → Identify → Tag → Land; title/artist appear; final path + genre/Art/Lyrics chips; file in Jellyfin | **T-016** | This *is* T-016's "Done when", word for word. Passing it is what makes T-016 **done**; nothing else will |
| 2 | Paste the **same URL again** | Should end "Done" sensibly, not hang | T-019 (§7 duplicate) | The duplicate skip emits **no §6 event at all** (`jobs.py:368`) — the only case relying on the snapshot fallback |
| 3 | Kill `uvicorn` mid-download, restart it | Card should recover, **not** freeze or show a false error | **T-020** | Three rewrites got exactly this wrong, in both directions |
| 4 | DevTools → Network → Offline ~10s, then back | Same as #3 | **T-020** | EventSource auto-retry + server replay — the mechanism T-016 now leans on entirely |
| 5 | Paste an obscure/live/remix track | Parks: "Weak match — parked for your review" then stops | — | **Expected dead end** — the review panel is T-017. Song is safe in the queue |
| 6 | Paste a **playlist** URL | Refused with a clear message, not expanded | T-019 (§7) | Spec §7 |
| 7 | Paste a track credited **"A feat. B"** | Lands under `A/`, title reads `Song (feat. B)`, and Jellyfin's artist view shows **one** `A` — not `A feat. B` as a separate artist | **T-024** | T-024's "Done when", word for word. ADR-012 is verified on the singleton path but has **never landed a real download**; this is its only receipt |

Record what actually happened per row — a symptom beats a hypothesis. **Row 1 passing is the
T-016 acceptance receipt**; rows 3–4 are evidence for T-020, not pass/fail gates on anything today.
T-019 stays open regardless: it owns the *whole* §7 checklist, of which rows 2 and 6 are two items.

**Results — session 1 (2026-07-18).** Rows **1 ✅** (receipt on T-016) and **5 ✅** (parked exactly
as specified; the dead end is by design until T-017). Rows **2, 3, 4, 6 not yet run** — the session
was spent on the four blockers the first paste exposed, which is the session working as intended.
Nothing could be tested at all until they were fixed:
- Playlist rejection blocked every URL the owner had (→ fixed; learnings + regression tests).
- `JELLYFIN_URL=localhost` was structurally unreachable from WSL (→ fixed in `.env`; learnings).
- Wrong year from a reissue release (→ ADR-011, `original_date`).
- Junk `TCON` from the YouTube category, plus two lesser finds (→ T-021, T-022, T-023).

**Results — session 2 (2026-07-19), HTTP against the isolated `:8100` harness.** Closed every
§7 item that does not require the owner's browser. Status of the 10 §7 checkboxes:

- **#9 playlist rejected** ✅ — `POST /api/jobs {playlist?list=}` → **422**; `watch?v=X&list=RD…`
  → **200** (deliberate: owner's everyday URL; `noplaylist:True` at `download.py:207` holds the
  one-song line, flagged load-bearing).
- **#10 localhost-only** ✅ — `ss -ltnp`: `:8100` and `:8137` `LISTEN 127.0.0.1` only.
- **#7 forced failure names stage + cleans staging** ✅ — nonexistent video id → SSE
  `track.error {stage:"download"}`; no staging dir orphaned by the job.
- **#4 MP3 320 CBR + art/lyrics/tags** ✅ *partial* — ffprobe of the landed JAŸ‐Z file: stream
  `320000` flat (CBR), attached mjpeg art, synced lyrics, correct title/single-artist. **genre=
  `Music`** (Last.fm key unset → junk YouTube category, T-021/22/23) and **date=`2026`** (T-025 /
  ADR-011) remain the two known tag-quality defects; #4 cannot be *fully* green until those land.
- **#6 duplicate handling** ✅ — all three branches driven live through the **real beets engine**:
  - `keep_existing` → download discarded, both existing copies intact, review→resolved, GET→404.
  - `replace` → single-copy fixture (192k); re-paste parked (320>192); resolve removed the old
    192k and landed one **320k** upgrade (land-before-delete; never zero copies).
  - `keep_both` suffix="(Verify KB Take)" → original 192k kept + new **320k** landed with the
    suffix on the **title tag** (path derived from it). (Resolve sat ~48s in `resolving` due to
    Genius lyrics `429` retry — transient, not a hang.)
- **#1 / #2 / #3 / #8** ✅ carried from session 1 + T-017 (Row 1 DOM/SSE render, auto-land,
  weak-match resolve, restart re-hydration). This session's re-paste SSE also showed the full
  `downloading → transcoding → identifying → review_required` progression at the stream level.

**#5 (track in Jellyfin within seconds via app-triggered scan)** ✅ — owner-confirmed live
2026-07-19 on Jellyfin 10.11.11: a landed track auto-appeared via the app's scan trigger, no
manual click (dashboard showed Songs: 6 + "finished playing JAŸ‐Z — Coming of Age"). A side
finding — lyrics need a second manual scan — is split out to **T-030** (minor, deferred); it is
NOT a §7 gate (#4 requires lyrics *in the file*, which is proven).

**T-019's only remaining gate is #4's tag-quality defects** — genre=`Music` (T-021/22/23) and
year=current-not-original (T-025 / ADR-011). Every §7 item has now been *observed*; T-019 closes
when those land and a re-verify shows real genre + correct year on a freshly landed file.

**Incidental observation (not a §7 gate, not a current-code bug).** Some orphaned
`/tmp/cleanmuzik-*` dirs linger (`nInBDfbZBbo`, `nXHW5UsbOIA`), but the current run path does **not**
leak: `run_pipeline`'s `finally` (jobs.py:389-392) `rmtree`s staging on every terminal outcome,
retaining only for a parked song — verified this session (forced-failure + both resolve jobs
cleaned up). The lingering dirs are prior-code debris (`nInBDfbZBbo` predates that `finally`) and
hard-killed runs (a `SIGKILL`'d process can't run its `finally`). Not a bug to fix in the run path;
would need a startup/TTL janitor, which is deferred past R1 (single-user localhost, `/tmp` clears on
reboot). **Not** folded into T-029, whose scope is the job/row status disagreement and which
deliberately retains staging.

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

### T-021 — Junk genre: the YouTube category survives into `TCON`
- **Status:** **BUILT (2026-07-20)** — fixed via **ADR-013 `from_scratch: yes`**, not `lastgenre
  force`. Diagnosis in the ticket was half-right: the junk `TCON` survived not because `lastgenre`
  "writes nothing", but because with `force: no` (default) an existing genre short-circuits it at
  `"keep any, no-force"` (`lastgenre/__init__.py:462`) — it never even queries Last.fm. `from_scratch`
  clears the junk at apply, so `lastgenre` then fetches fresh (or leaves blank). **Verified on a real
  download** (isolated temp library, `nInBDfbZBbo`): the landed `Coming of Age` MP3 carries **no genre
  tag** where it previously read `TCON="Music"` — Last.fm had no tags, so it lands blank, exactly the
  "Done when". `/code-review` (high) clean after fixes; suite 324 green. In-Jellyfin genre-list check
  is the owner's browser confirmation, but the on-disk absence is proven. **Done when merged to main.**
- **Depends on:** nothing
- **Agent:** back-end
- **What:** When Last.fm has no tags for a track, `lastgenre` writes nothing — and the genre that
  yt-dlp's `--embed-metadata` already put on the file *survives*. That value is YouTube's
  **category**, not a genre: two tracks landed as `TCON="Entertainment"` and `TCON="Music"`. The
  card correctly shows no genre chip (beets' item has no genre), so this is invisible in the UI and
  visible only in Jellyfin, which will build genre categories called "Music" and "Entertainment"
  out of it and pollute the library's browse-by-genre view.
- **Note:** the Last.fm key is fine — verified live; obscure/new releases genuinely have no tags.
  This is about what happens in that gap, not about fetching.
- **Done when:** a track for which Last.fm has no tags lands with **no** genre tag rather than a
  YouTube category, confirmed on disk and in Jellyfin's genre list.

### T-022 — No JavaScript runtime for yt-dlp: formats may be silently missing
- **Status:** todo — **found in the first browser session (2026-07-18).**
- **Depends on:** nothing
- **Agent:** back-end
- **What:** yt-dlp warns on every run: *"No supported JavaScript runtime could be found… YouTube
  extraction without a JS runtime has been deprecated, and some formats may be missing."* Downloads
  currently succeed, so this is latent — but "some formats may be missing" means the bestaudio
  picker may be choosing from a **degraded set**, which would quietly cost audio quality on a tool
  whose entire point is a clean library. Not measured yet.
- **Done when:** either a JS runtime is installed and the warning is gone, or it is *measured* that
  the formats offered with and without one are identical for a sample of tracks — and whichever it
  is, recorded here. Do not close on "downloads still work".

### T-023 — Jellyfin needs a second scan before sidecar lyrics appear
- **Status:** todo (low priority) — **found in the first browser session (2026-07-18).**
- **Depends on:** T-010
- **Agent:** back-end
- **What:** After a track lands, `POST /Library/Refresh` makes the **track** appear in Jellyfin
  promptly, but its `.lrc` lyrics do not — a second, manual library scan is what surfaces them.
  Reproduced twice.
- **Not a race (evidence):** file mtimes show the `.lrc` written 401 ms *after* the `.mp3`, and the
  scan nudge only fires after the import seam returns — so **both files were on disk before the
  POST**. Jellyfin enumerated them and attached lyrics on a later metadata pass regardless. This is
  scan *depth*, not timing, so a `sleep` before the nudge would not fix it.
- **Note — probably don't fix:** lyrics arrive on Jellyfin's next scheduled scan anyway. A second
  delayed nudge is a hack for a cosmetic delay and adds a timer to a pipeline that has none. Filed
  so the behaviour is known rather than rediscovered; close as won't-fix if that still reads right.
- **Done when:** a decision is recorded — either lyrics appear on the first nudge, or this is
  closed as accepted behaviour with the reason.

### T-024 — "feat." in the artist field fragments the library
- **Status:** **DONE (2026-07-19)** — row 7 discharged. ADR-012 written, `ftintitle`
  added to `PLUGINS` with `drop: no` / `format: "(feat. {})"` / `preserve_album_artist: no`, and
  6 regression tests added in `tests/test_beets_engine.py` (suite 301 green). The "Done when"
  below is now proven against a **real download** — ADR-012's first real-world receipt. Landed via
  the isolated verify harness (`:8100`, temp DB + sandboxed library, real yt-dlp/AcoustID):
  `youtube.com/watch?v=nInBDfbZBbo` (Jay-Z "Coming of Age (feat. Memphis Bleek)") auto-accepted and
  landed as `JAŸ‐Z/Coming of Age (feat. Memphis Bleek).mp3` — `TPE1='JAŸ‐Z'` (single primary artist,
  **not** `… feat. …`), featured credit in the title, MP3 320 CBR, embedded art, synced lyrics. So
  it groups under one `JAŸ‐Z` in Jellyfin's artist view, exactly the fragmentation this ticket
  killed. (Two non-T-024 observations on the same file: genre canonicalized to generic `Music` — the
  T-018 `lastgenre`-whitelist follow-up — and year stamped `2026` — see T-025.)
- **Depends on:** nothing
- **Agent:** back-end
- **What:** A collaboration lands with the featured artist baked into the artist field, so
  `PATHS["singleton"] = "$artist/$title"` creates a folder — and in Jellyfin, a distinct **artist** —
  per collaboration. Observed: `Nines feat. Tiggs da Author/NIC.mp3`. A future Nines track lands
  under `Nines/`, and the two never group. This is the library fragmentation the tool exists to
  prevent, and it compounds silently: every feature spawns another phantom artist.
- **Evidence (the clean value is already on the file):**
  - `TPE1` = `Nines feat. Tiggs da Author` ← names the folder
  - `TXXX:ARTISTS` = `Nines` ← the actual artist
  - `TXXX:MusicBrainz Artist Id` = `79598541-…` ← **Nines alone**, one ID, not the pair
  So nothing needs fetching; the correct value is already tagged.
- **Not our `artist_credit` setting.** beets defaults `artist_credit: no` (`config_default.yaml:103`)
  and we never set it — the "feat." comes from **MusicBrainz's own recording artist credit phrase**,
  which beets uses as `item.artist` for a singleton. Don't start by flipping that config; it isn't on.
- **Fix taken:** the stock **`ftintitle`** plugin, recorded as **ADR-012** before any code (ADR-010's
  rule — `PLUGINS` was closed at the spec §2 set by ADR-007, so a seventh plugin needed a decision,
  not a quiet edit). Verified against the *singleton* path before acceptance, per ADR-011's lesson:
  the plugin stage fires on `SingletonImportTask` (`session.py:237` → `stages.py:245`, no singleton
  branch; `tasks.py:699` returns `[self.item]`) and runs **before** `manipulate_files`, so the folder
  is written as `Nines/` rather than renamed after. Observed on the real file's tags:
  `artist='Nines feat. Tiggs da Author' title='NIC'` → `artist='Nines' title='NIC (feat. Tiggs da Author)'`.
- **Trap found while verifying — why `preserve_album_artist: no` is explicit.** `ft_in_title()` bails
  when `artist == albumartist`, and the option defaults **yes**. It doesn't trip today only because
  `TrackInfo.item_data` carries no albumartist (`hooks.py:400`), so `TPE2` is whatever yt-dlp left —
  and on the observed file it is **absent**, hence falsy, hence short-circuited before comparing.
  A future yt-dlp that writes `TPE2` would silently no-op the plugin with a green suite. Setting it
  off removes the dependency; `test_fires_even_when_albumartist_equals_artist` locks it in (confirmed
  to fail when the setting is removed, so it is a real guard, not decoration).
- **Note:** not retroactive — tracks already landed keep their folders until a re-tag pass.
  `Nines feat. Tiggs da Author/NIC.mp3` is still on disk; the owner accepted that rather than scope
  a backfill here.
- **Done when:** a track credited "A feat. B" lands under `A/`, groups with A's other tracks in
  Jellyfin's artist view, and the featured credit is preserved somewhere (title or a tag) rather
  than discarded. Verify in a browser, not just on disk.

### T-025 — Reissue years: a singleton lands with the matched release's date, not the original
- **Status:** **BUILT (2026-07-20)** — the diagnosis was wrong: the bad year was **not** a MusicBrainz
  reissue date, it was **yt-dlp's embedded date surviving** the same way T-021's genre did (a
  singleton `TrackInfo` carries no year, and `apply_metadata` only overwrites non-None fields). Two
  fixes, both owner-signed: **ADR-013 `from_scratch`** clears the junk year, and **ADR-014** stamps
  an original-*ish* year via one MusicBrainz call on the auto-accept/resolve path (recording-level
  `first_release_date`, else earliest release date). It is an honest **proxy, not a guarantee** — a
  recording AcoustID mapped to a reissue master yields a reissue year — the owner accepted this over
  a blank year, shown the limits before deciding. **Verified on a real download** (`nInBDfbZBbo`): the
  landed `Coming of Age` MP3 is stamped **`date=1996-06-25`** — the true original — where it
  previously read `2026`. `/code-review` (high) surfaced 7 findings; 5 fixed (recording-level date,
  same-year fullest-date tie-break, write-fail rollback, cached MB client, reuse beets' `_get_date`),
  1 accepted (double tag-write — negligible for a single-user tool), 1 escalated (album-family
  blanking → owner decision → T-031). Suite 324 green. **Done when merged to main.**
- **Depends on:** nothing
- **Agent:** back-end
- **What:** AcoustID matches the *recording* correctly, but MusicBrainz metadata comes from a
  **release**, and the one chosen may be a remaster/compilation/reissue. A track the owner knew to
  be much older landed stamped **2024** (first browser session, 2026-07-18). The audio is right;
  only the date is a reissue's.
- **Second data point (2026-07-19, T-024 row 7):** Jay-Z "Coming of Age" — a 1996 *Reasonable Doubt*
  track — landed stamped **2026**, the *current* year, not merely a reissue's. That flavour is worth
  a look: a plain reissue would carry some real-but-later release date, whereas landing today's year
  suggests the singleton path may be **defaulting** when it can't resolve a release date at all,
  rather than picking a wrong-but-real one. Same fix reaches both; the diagnosis may differ.
- **Do NOT start with `original_date: yes` — it is inert here and has already been tried.** beets
  reads it only in `AlbumInfo.item_data` (`autotag/hooks.py:325`); R1 imports singletons
  (`import_seam.py:845`), which build a `TrackInfo` (`hooks.py:400`) with no such override and no
  `original_year` field. See the rejected ADR-011 for the full autopsy.
- **Price it before building.** The data is not on the singleton path at all, so reaching it means
  an extra MusicBrainz call per import (the recording's earliest release date, or its release
  group's `first-release-date`). That is the same per-item lookup cost **ADR-010 explicitly
  declined** for candidate enrichment — so this ticket must justify why the year is worth what the
  album/art fields were not. Plausible answer: it is one call on the *auto-accept* path only (not
  per candidate), and the year is visible in Jellyfin on every browse. Decide, record, then build.
- **Done when:** a known reissued track lands stamped with its **original** release year, verified
  on disk and in Jellyfin — and if the call is instead "not worth it", that is recorded here with
  the measured cost and the ticket closed won't-fix.

### T-026 — A deliberately-pasted playlist now lands one track with no signal
- **Status:** todo — **needs an owner decision before any code.**
- **Depends on:** nothing
- **Agent:** back-end
- **What:** Narrowing the playlist classifier (2026-07-19) fixed the false rejection of
  `watch?v=SONG&list=RD…`, but it also means a URL carrying *real* playlist intent —
  `music.youtube.com/watch?v=TRACK1&list=OLAK5uy_ALBUM`, copied while an album played — is now
  accepted. One track lands, the other eleven are silently dropped, and nothing in the UI says the
  URL named more than one song. Spec §3's "don't expand" guarantee still holds; what was lost is
  the *"playlists aren't supported yet"* message for the shape most likely to mean an album.
- **The decision:** list ids are distinguishable — `RD…` is an auto-generated radio/mix seed
  (YouTube's, not the owner's), while `PL…` / `OLAK5uy_…` / `UU…` are curated playlists. So the
  refusal *could* be restored for curated ids only. **Counter-argument, and it is not weak:** the
  owner also reaches songs by clicking into his own `PL…` playlist, so refusing those re-creates
  the exact false rejection just removed — and over-rejecting is the mistake this repo has now made
  once (see the "breadth in a validator is not safety" learning). Landing the named song is also
  arguably the more useful behaviour: R1 does not do playlists at all, so a track in hand beats an
  error message.
- **Options:** (a) leave as is, accept the silent single-track landing; (b) refuse curated list ids
  only; (c) accept, but have the UI *say* "this URL was part of a playlist — only the named song
  was taken", which keeps the owner's flow and restores the signal. **(c) looks strongest** — it
  is additive, refuses nothing, and needs no id-prefix taxonomy to be correct.
- **Done when:** a decision is recorded here with its reason, and if (b) or (c), the behaviour is
  observed in a browser against a real album URL.

### T-027 — `download_song` has no guard for a playlist-shaped `extract_info` result
- **Status:** todo — **deferred deliberately: this is a failure path this sandbox cannot produce.**
- **Depends on:** T-019 (needs a live browser / real yt-dlp failure to drive)
- **Agent:** back-end
- **What:** With `list=` URLs now admitted, `extract_info` can return a playlist-shaped dict. That
  result has no top-level `requested_downloads`, so the fallback `prepare_filename(info)` returns a
  path for a file that was never written; there is no `info.get("_type") == "playlist"` guard. The
  transcode stage would then fail with a bare `FileNotFoundError` **attributed to the wrong stage**.
- **Why it is not being fixed blind:** the review verdict was PLAUSIBLE, not confirmed, and nobody
  has produced the input that triggers it. Writing the guard now means writing failure-handling for
  a condition we cannot make fail — the exact mis-sequencing that cost T-016 three fix rounds and
  two full review passes (see `learnings.md`, 2026-07-18). Reproduce it first, then guard it.
- **Done when:** either a URL is found that produces a playlist-shaped result (then: guard it, and
  the card reports the Download stage honestly), or it is demonstrated that `noplaylist=True` makes
  the shape unreachable — and that demonstration is recorded here, closing the ticket.

### T-028 — Persist candidate `score`: the queue can't supply the field ADR-010 picks on
- **Status:** **DONE (2026-07-19) — unblocks T-017.** Found by reading T-017's ticket against the
  payload it needs (the ADR-010 acceptance check), not by any code review. 8 tests in
  `tests/test_review_scores.py`, suite 309 green.
- **Receipt (both halves of "Done when", driven over real HTTP):**
  1. *Migration preserves the queue* — the owner's live DB migrated in place when the running
     `uvicorn --reload` re-ran its lifespan on the `db.py` edit; the pending `Outro` review and its
     5 candidate ids survived, confirmed by a live `GET /api/reviews` (scores stay null there, as
     designed: the row predates the column).
  2. *A new park writes non-null scores that survive a restart* — an isolated server
     (`DB_PATH` → temp dir, so the real library was untouched) was given the same URL that produced
     the legacy row. It parked, `GET /api/reviews` returned five scored candidates, the process was
     **restarted**, and the same scores came back. A clean A/B on one track: all `null` before,
     fully scored after.
- **The bug, observed live.** That surviving review is a clean demonstration of why this ticket
  exists: its candidates include `Nines — "Nines SBTV Bars 2015"` and `Nines — "Nines Freestyle
  2007"` — two rows reading nearly alike — with `score: null` on both. That is ADR-010's "chosen
  between on `score` alone" with the field empty. The row keeps its nulls (it predates the column);
  new parks won't.
- **Depends on:** T-014
- **Agent:** back-end
- **What:** ADR-010 makes `score` load-bearing — *"`score` is the discriminator"*, with the accepted
  cost that *"two identical-reading candidates must be chosen between on `score` alone."* But
  `GET /api/reviews`, which is the review panel's only data source, returns **`score: null` always**:
  - `db.py:14` — `candidate_ids_json` is *"a JSON array of MBID strings, nothing more"*. The score is
    computed at park time (`import_seam._candidate_rows:823`, `1.0 - distance`), emitted once on the
    `track.review_required` SSE event, and **never persisted**.
  - `reviews.py:307` — the re-hydration path states it outright: *"score stays null: a recording
    lookup carries no per-candidate tag distance."*
  So the discriminator exists only in the live SSE moment. Reload the page and it is gone.
- **Why that is not survivable:** spec §7 requires *"restart preserves reviews"*, so the queue's
  normal case is being worked **later** — exactly when `score` is null. Building T-017 as written
  ships a picker that shows its discriminator only if you happened to be watching.
- **This is the ADR-010/ADR-011 failure class, caught in time for once.** A decision recorded whose
  payload cannot deliver it. The DoD's acceptance check says: *if the ticket asks for something the
  spec's payload can't deliver, stop and amend, don't build the nearest thing.* Hence this ticket
  rather than a null-tolerant panel.
- **Fix:** persist the score at park time. **Add `candidate_scores_json` — a map of MBID → score —
  not an id+score array.** The map avoids duplicating the id list and cannot drift out of order with
  `candidate_ids_json`; a missing key degrades to `None`, which is exactly today's behaviour, so
  legacy rows and duplicate parks (which have no scores) need no special case.
- **Migration, not a recreate:** the live DB has **1 pending review** (row 5's parked track) and
  spec §7 promises it survives. `db.py` has no migration mechanism — only `CREATE TABLE IF NOT
  EXISTS` — so this needs an idempotent `ALTER TABLE ... ADD COLUMN` guarded on the column being
  absent. The legacy row keeps `score: null`, which is what it has today.
- **Done when:** a track parks, the server is restarted, `GET /api/reviews` still returns a non-null
  `score` for each candidate, and the pre-existing pending review still lists (with null scores)
  rather than disappearing or 500ing. **Second half done** (live `GET /api/reviews` above); the
  first half needs one real download that parks — **row 8 on the browser run list**, or a direct
  `POST /api/jobs` against the running server, which is now known to work (see `learnings.md`,
  2026-07-19: localhost sockets are *not* blocked).

### T-029 — A failed resume orphans the review: job goes `error` while the row is `pending`
- **Status:** todo — **carved out of T-017's code review (2026-07-19, finding 2).** Not a T-017
  regression; the inconsistency predates it (T-014), but T-017 is what made it *visible* — the
  per-card panel is the only resolve UI, so a review that leaves the card has nowhere to go.
- **Depends on:** T-014, T-017 (T-017 built the reconcile-re-hydration + `GET /api/reviews/{id}`
  this fix rides on)
- **Agent:** back-end (a server status change; the client half may need nothing)
- **The bug.** The owner picks a candidate; the resolve POST returns `{ok:true}` and the card opens a
  fresh EventSource for the resume. The resume then fails *before the point of no return* — a
  releasable `_StageFailure` (e.g. the chosen recording no longer resolves at MusicBrainz). The
  server does the right thing for the **row**: `run_resolve` releases the review back to `pending`
  (jobs.py ~586, retryable) and keeps its staging. But it settles the **job** to `STATUS_ERROR` and
  emits `track.error` (jobs.py ~589). The card follows the job to `error`, the `ReviewPanel`
  unmounts — and the still-pending review is orphaned, because there is no standalone queue view to
  reach it from. The owner sees only "Failed" and must re-paste the URL, re-downloading a song that
  is sitting resolvable in the queue.
- **Why the two states disagree.** `run_resolve`'s error handling has two branches: a **committed**
  failure (past `committed = True` — staging dropped, row `RESOLVED`) is a genuine job error and
  must stay `error`; a **releasable** failure (pre-commit) returns the row to `pending` for a retry.
  Only the *releasable* branch is wrong to report as a terminal job error — the job is not done, it
  is parked again.
- **The fix (the shape, not the letter — settle in the ticket).** On the releasable branch, set the
  job status back to **`review`** (not `error`) so it matches the row, and re-signal the parked
  state instead of `track.error`. The cleanest re-signal reuses what T-017 already consumes:
  re-emit `track.review_required` (same `review_id`, same candidates) so the live card re-renders
  the panel with no new machinery, **and** a `GET /api/jobs/{id}` snapshot then reports `review`, so
  a card that lost the stream re-hydrates via `GET /api/reviews/{id}` exactly like the restart path.
  - **Open design point for the ticket:** the owner should be *told the pick failed* ("That match
    couldn't be applied — pick another"), not silently re-parked. Decide whether that rides on the
    re-emitted `track.review_required` (an added optional `message`) or a small dedicated event.
    Do not lose the reason.
  - **Do not touch the committed branch.** A post-commit raise (scan/`track.done` publish after the
    file already landed) is a real job error and stays one — the review is `RESOLVED`, not pending.
- **Done when:** a resume made to fail on the releasable path leaves the job status `review` (not
  `error`), the card re-shows the resolve panel (live and after a forced stream drop), the review is
  still `pending` and resolvable, and the owner can see *why* the previous pick failed. Verifiable
  over real HTTP by forcing a resolve to a recording id that won't resolve (no browser strictly
  needed for the status/row assertions; the re-render is the browser half).

## Backlog (post-R1 — triage into a future release)

Not R1 scope. These are real, filed so they aren't rediscovered, but they do **not** gate R1 or
T-019's close. Triage them when R2 is scoped (see `docs/roadmap.md`). Everything above this line is
the R1 set.

### T-030 — Landed lyrics don't surface in Jellyfin until a second scan (minor, deferred)
- **Status:** todo — **minor, owner-deferred (2026-07-19).** Found during T-019 #5. Not a §7 gate:
  §7 #4 requires lyrics *embedded in the file*, which is proven; lyrics *visible in Jellyfin* is
  beyond the literal checklist. Park until the R1 must-haves are closed.
- **Depends on:** T-010 (the scan trigger this adjusts).
- **The finding.** A freshly-landed track auto-appears in Jellyfin via the app's scan trigger, but
  its **lyrics do not show until the owner clicks "Scan All Libraries" a second time.** Confirmed
  live 2026-07-19 on Jellyfin **10.11.11**.
- **What's NOT the cause (verified).** The landed file is complete: synced lyrics both embedded in
  the tag AND written as a `.lrc` sidecar at land time (real library: every `.mp3` has a same-mtime
  `.lrc`; e.g. `JAŸ‐Z/Coming of Age….lrc` @ 22:05:16). So this is not a tagging/sidecar gap.
- **Likely cause — a race, not the wrong scan.** The owner's manual button is **the same
  `/Library/Refresh`** the app already fires (`jellyfin.py`). A second identical scan surfacing the
  lyrics points to the app's scan firing **before Jellyfin can index the just-written `.lrc`** (or
  before the file settles), so the first pass ingests the track but not its lyrics.
- **Fix directions to weigh in the ticket (don't pre-commit):** (a) a short delay / retry before or
  a second deferred `/Library/Refresh` after land; (b) an item-level metadata-refresh call once the
  item exists; (c) confirm `.lrc` is flushed+closed before triggering the scan. Prefer the smallest
  reliable option; a single-user localhost tool doesn't need a polling loop.
- **Done when:** a landed track shows its lyrics in Jellyfin with **no manual scan**, driven once
  through the real stack and watched (owner browser, like #5).

### T-031 — Recover the album when it's real (Topic-channel rips, same-album clusters)
- **Status:** todo — **future feature, owner-deferred (2026-07-20).** Born from ADR-013 / T-021's
  F1: `from_scratch` correctly blanks yt-dlp's junk album, but that also drops the *real* album on
  the rips that carry one. Not an R1 blocker (see ADR-013 — album isn't load-bearing for a
  singles-by-`$artist/$title` library), but the owner does want the album when it's genuine.
- **Depends on:** ADR-013 (the behavior this refines), likely the R2 migrate flow.
- **The opportunity.** The owner's flow is individual tracks off YouTube saved to playlists, so a
  lone track legitimately often has no album — that's fine. But two cases carry real album data
  worth keeping: (a) a **YouTube "Topic" channel** rip, where the embedded album is the label's
  actual release (e.g. `Thriller`), not a video title; (b) **several tracks from one release** landing
  over time, which should recover and **group under that album** in Jellyfin rather than stay loose
  singles.
- **Why it's abstract (the owner's own framing).** R1 imports everything as a *singleton*
  (`PATHS["singleton"] = "$artist/$title"`), and a MusicBrainz recording lookup carries no album. So
  "put the album back" means either trusting yt-dlp's embedded album (junk-prone — the exact thing
  ADR-013 stops) or an extra release/release-group lookup + a which-release heuristic (the per-item
  cost ADR-010 declined) plus a re-organize into album folders. It reopens the album-vs-singleton
  path decision, which is why it's its own ticket, not a tweak.
- **Directions to weigh (don't pre-commit):** (a) detect Topic-channel uploads and trust their album
  tag specifically; (b) on the migrate/re-tag pass, cluster landed tracks by release-group and
  promote a group to an album; (c) a MusicBrainz release lookup on auto-accept to pick a canonical
  release (cost + heuristic — price it like ADR-014 priced the year).
- **Done when:** a decision is recorded here, and if built, a real album's tracks land grouped under
  that album in Jellyfin — verified in a browser.
