---
type: meta
title: "Hot — cleanmuzik"
updated: 2026-07-15
last-commit: 2c3c3d9
tags:
  - meta
  - hot-cache
status: evergreen
---
# Hot — cleanmuzik (personal YouTube → Jellyfin music tool)

> This repo's own working-memory board — session continuity, loaded at session start via
> `/hot`. Durable business/vault learnings belong in the garden (send them with `/graft`),
> not here.

## What this repo is

CleanMuzik — personal YouTube → Jellyfin music tool. Full description, stack, and constraints
live in `CLAUDE.md` and `cleanmuzik-prd.md` (this board holds *volatile state*, not evergreen
description — see there, don't restate here).

**Phase: R1 IN BUILD — Phase A engine spine COMPLETE. T-001…T-011 all done, committed + pushed.**
Spec signed off, `docs/r1/tickets.md` holds 19 build-ordered tickets. **T-009 (acquire-time
duplicate handling) committed** (`2c3c3d9`) — the last spine sibling. Next is **Phase B**: **T-012**
(worker-thread job queue + `/api/jobs` routes; wires every stage — download → transcode → normalize →
identify/tag/art → Jellyfin scan — into one sequential run). T-012 is the next *big* ticket and the
first time the whole pipeline runs end-to-end as a job; keep it **solo** (it's the integration point).
The one genuine fan-out pocket is later: after T-012, **T-013 (server SSE) ∥ T-015 (client paste+Go)**
are disjoint (server vs `client/`). See `docs/r1/tickets.md`.

## Current State (2026-07-15)

- **Branch `main` == `origin/main`** — session-10's pending push landed (`53bea61`), then **T-009
  committed + pushed** (`2c3c3d9`). This board lands next as `docs(hot)`.
- **T-009 DONE — acquire-time duplicate handling (`get_duplicate_action`), NON-DESTRUCTIVE (ADR-009).**
  The 2.12 hook is `get_duplicate_action(task, found_duplicates)`, not the ticket's older
  `resolve_duplicate` name. Detection by **MusicBrainz recording id** (`duplicate_keys.item =
  mb_trackid`) — complete for R1 by construction (every landed copy has an MBID; untagged legacy
  files are R2 migrate input). **R1 never auto-deletes the owner's file** — quality is a *partial
  order* on `(bitrate, tag richness)`: keep existing (`SKIP`) when an existing copy *covers* the
  incoming one on **both** axes; else **park to review** ("you already have this — keep which?").
  Owner picked non-destructive (the recommended option); auto-replace (copy-first/delete-after) is
  deferred to R2. **184 tests green** (+8 dup tests). ADR-009 recorded; spec §5 + tickets updated.
  - **`/code-review` high (workflow): 4 findings, all mine, all confirmed, all handled.** The
    load-bearing one (#1): my first cut returned `DuplicateAction.REMOVE`, but beets 2.12
    `manipulate_files` **deletes the old file before it copies the new one** — a copy failure loses
    BOTH. That data-loss window drove the whole non-destructive rework. #3: `get_duplicate_action`
    runs *before* beets applies tags, so reading the incoming item's "completeness" was pre-apply —
    the partial-order/cover model makes that read *correct* (a bare download can only fail to cover a
    tagged copy, never wrongly displace it). #2: mb_trackid-only misses untagged legacy copies —
    documented as R1-scoped. #4: folded `_park`/`_park_duplicate` into `_record_review`. → learnings.md.
  - **Verify note:** decision logic proven by unit tests (cover → skip; upgrade/trade-off → review;
    one-outcome bookkeeping); detection-by-mbid proven against real beets (`duplicates_query` on
    `mb_trackid` matches a committed row; a different recording does not). A full live re-paste
    end-to-end rides with **T-012/T-019** (needs the job pipeline to drive two real downloads).
- **T-010 DONE — Jellyfin scan trigger (`server/app/jellyfin.py`).** `trigger_scan()` POSTs
  Jellyfin's `/Library/Refresh` with `X-Emby-Token` auth after a track lands so it appears in
  seconds. Three-way contract (spec §6): **True** = scan requested; **False** = degraded (missing OR
  whitespace-only `JELLYFIN_URL`/`_API_KEY` → logged warning, track still landed — "absent is not a
  failure"); **raise `JellyfinScanError`** = config present but the call failed, so T-012 can emit
  `track.error` stage=`scan`. **Not yet wired into a job run — that's T-012**, which lists T-010 as a
  dep.
  - **Verified against LIVE Jellyfin** (real `.env` key): valid → 204 → True; bad key → 401 →
    `JellyfinScanError`. Gotcha logged to learnings.md: **`localhost` from WSL2 can't reach the
    Windows-hosted Jellyfin** (separate net namespace) — probe the WSL2 gateway IP
    (`ip route show default`, was `172.20.0.1`, not stable) via `settings.model_copy`; the `.env`
    stays `localhost` because the app runs on Windows in Phase 0.
  - **`/code-review` high (workflow):** 5 findings — **4 applied** (whitespace-only config degrades;
    both-absent warning now names *both* vars; class-docstring de-dup vs the module docstring; the two
    degrade tests parametrized), **1 rejected** (requests-only `except` is the house HTTP convention,
    matches `artwork.py`; injected `http` is a requests-shaped double). **9 Jellyfin tests, suite 176
    green.**
- **T-011 DONE — identify retry/backoff + owner AcoustID key wired.** `import_seam.py`: retry only the
  *lookup* (fingerprint generated once) with exponential **1→2→4s** backoff on transient
  `AcoustidLookupError`; `_resolve_api_key(settings)` picks the owner's `acoustid_apikey` (private
  quota, verified 10-char, resolves over the shared key) with the shared `1vOwZtEn` as fallback, bound
  in `import_song` via `functools.partial` so `choose_item`'s call site stays key-agnostic.
  - **Load-bearing review fix (the flaw I introduced, then fixed):** pyacoustid's `_api_request`
    does **not** `raise_for_status`, so a **rate-limit AND an invalid key both arrive as a non-ok
    `status`** — distinguishable only by `error.code`. Naive "retry every error" would hammer a
    typo'd key 4× (~7s) per song then silently mass-park the whole run with no signal. Fix:
    `_PERMANENT_ERROR_CODES` **denylist** (incl. invalid-key 4/6) → raises non-retryable
    `AcoustidPermanentError` → `choose_item` parks **but logs ERROR** ("check ACOUSTID_APIKEY").
    Everything else (rate-limit 14, service-unavailable 13, network, unknown code) stays retryable.
    Denylist not allowlist, so an unknown code errs toward retry (harmless), never toward hammering
    a bad key. (→ learnings.md)
  - **`/code-review` high (workflow):** 5 findings, 0 refuted — #1 permanent-retry / #4 stale
    docstring / #5 tests-run-full-loop **applied**; **#2** (blocking sleep / no SSE progress) mostly
    moot after #1 (invalid-key 7s-stall gone; batches are R2, SSE is T-013, beets runs off the event
    loop in a worker thread — deferred to owning tickets); **#3** auto-fallback-to-shared-key on a bad
    owner key **rejected** (masks a misconfig the owner should fix; a *rate-limited* owner key still
    recovers via the transient path). **167 tests green** (+8: retry-recovers, retry-exhausted,
    no-match-not-retried, invalid-key-permanent, rate-limit-retryable, permanent-parks, 2 key-resolve).
- **Intro primer built + committed** (`6e8f205`) — `docs/primers/00-what-is-cleanmuzik.html`, a
  friendly non-technical walkthrough (old Googled-converter routine, inconsistency/title-only pains,
  the tool cast in plain words, an SVG network diagram with a Phase 0/1 toggle). Published Artifact:
  `https://claude.ai/code/artifact/9288627e-39b4-45f7-874d-bec3cedfc31b`. "Start here" ahead of the
  numbered tracks.
- **Primer A3 redeployed** — the claude.ai 500 cleared; the public copy at
  `https://claude.ai/code/artifact/b2d9e8f0-7902-4f09-979e-bd4e0f908df1` now shows the final
  gap-decided verdict (git source was already correct; no file change).
- **T-008 DONE — thresholds tuned on 25 real songs. `SCORE_MIN=0.90` held, `GAP_MIN=0.10→0.0`.**
  Measured owner-library (15, incl. tag-less bare-title files — the worst case) + a YouTube playlist
  (10 usable, 5 lost to rate-limit): **22 correct auto-accepts, 0 wrong, 3 genuine no-matches**;
  correct all 0.955–0.995, no-matches 0.0. **Re-measured auto-accept ≈88%** (vindicates the PRD's
  ~80%, via fingerprint identity not tag distance) — written into the **ADR-006 addendum**.
  - **Load-bearing finding — the gap check is dead weight.** A high runner-up was *always* the SAME
    recording listed twice in AcoustID (a re-release), never a different rival — two different
    recordings can't both fingerprint-match one audio at ≥0.9. So any gap floor only false-parked
    *certain* matches (Kanye "Through The Wire": top 0.987 vs a 0.977 duplicate). Gap kept as an
    injectable knob, **off by default**; the `_matching_candidate` identity check is the real backstop.
  - **AcoustID key correction (owner caught it).** The board previously called the owner's
    `ACOUSTID_APIKEY` a *submission* key — WRONG. It's a valid **application/lookup** key (verified,
    `acoustid.lookup`→status=ok). "Submission" only describes how *beets* uses a provided key. The
    seam still hardcodes pyacoustid's *shared* built-in app key (`1vOwZtEn`) which throttles hard
    (5/30 batch lookups rate-limited). **T-011 wires the owner's key into `fingerprint_dominance`**
    for a private quota + adds retry/backoff. (~3-line change; deferred to keep T-008's commit clean.)
  - **No-match behaviour clarified (owner asked):** AcoustID returns the exact recording or an EMPTY
    set — never a ranked list of maybes. The review queue's "maybe this/that" candidates come from a
    *separate* path (MusicBrainz **title** search), which is why good titles matter and tag-less
    bare-title files park empty.
  - **`/code-review` high (workflow, 4 findings):** 2 applied (stale `API_KEY` comment still calling
    the owner's key "submission"; primer verdict still framing gap as an open call), 1 rejected
    (GAP_MIN=0.0 near-tie tradeoff — the documented, intended decision), 1 empty. **159 tests green.**
  - **Primer A3 published** — "Score vs Gap" experiment walkthrough (full-bleed, house style, a
    real score/gap scatter of all 25 songs). Source: `docs/primers/A3-score-vs-gap-experiment.html`;
    URL: `https://claude.ai/code/artifact/b2d9e8f0-7902-4f09-979e-bd4e0f908df1`. (Redeploy of the
    final gap-decided copy was 500-ing on claude.ai at session end — retry; git source is correct.)
  - **Field note (owner-reported):** yt-dlp fails **opaquely** on a *private* playlist ("invalid
    URL", no reason) — a playlist must be public/unlisted. In learnings.md + primer A3.
  - **Measurement harness** (throwaway) lives in the session scratchpad (`measure.py` + `results.csv`):
    downloads/fingerprints a corpus, reads score+gap+identity with retry/backoff. Reusable if T-011
    wants to re-measure on the owner's key.
- **T-007 DONE (committed `3065731`) — the fingerprint-trust seam + Door B cover art.** The spine.
  `import_seam.py`: subclasses beets `ImportSession`, imports the song as a **singleton**, and
  `choose_item` runs the ADR-006 gate — **auto-land when the AcoustID fingerprint is dominant
  (now: score ≥ 0.90; gap check off per T-008) and the winning recording is a beets candidate;
  else park a `reviews` row + `Action.SKIP`.** (Reference detail below; the tuning is T-008 above.)
  - **Load-bearing finding #1 (resolved the artifact's open question):** beets' `chroma` plugin
    **computes the AcoustID score then discards it** — keeps only recording MBIDs, so the number
    ADR-006 gates on never reaches a beets candidate (their `distance` is *tag* distance, the ~0.11
    floor). The seam recovers it via **its own `acoustid.lookup`** (`fingerprint_dominance`), meta
    `recordings releases`. Trade-off accepted: 2 lookups/song → the free tier throttles the 2nd →
    parks-and-(T-011)-retries; the seam **parks-not-crashes** on `AcoustidLookupError`.
  - **Load-bearing finding #2 → Door B (owner picked "extend T-007 now"):** beets `fetchart` has
    `if task.is_album:` — it **skips singletons**, so cover art never embeds for us. `artwork.py`
    fetches the front cover from **Cover Art Archive** (by release MBID, full-res) → **iTunes**
    fallback (artist-verified), embeds via beets' native `art.embed_item`. Best-effort: never
    un-lands a track. **Lyrics already worked** (LRCLib, default source; now `synced` on for Jellyfin).
  - **Verified end-to-end (real song):** a-ha "Take On Me" → **auto-landed** `a‐ha/Take On Me.mp3`,
    score 0.959, **MP3 320 CBR**, title/artist/year(2010)/genre, **USLT lyrics**, **849 KB CAA cover**.
    Weak/ambiguous song → parked with 5 candidates. (Genre came out generic "Music" — a lastgenre
    whitelist cosmetic, minor follow-up, not a blocker.)
  - **Two `/code-review` high workflow passes, all real findings applied.** Pass 1 (gate, 7 findings):
    park-not-crash on lookup failure, NoBackendError surfaces loudly (not silent park), landed-receipt
    settled *after* run() (duplicate-skip no longer lies), bytes→TEXT fsdecode, runner-up = best
    *different*-recording result. Pass 2 (Door B, 6 applied / 1 rejected): `embed_cover` returns the
    *truth* (checks the file has art), iTunes artist-verified (no wrong covers), 1200→100px fallback,
    CAA release cap (≤3, no pipeline stall), PNG test. Rejected: "reuse fetchart sources" (needs fake
    Album+Candidate machinery — more coupling than a scoped fetch).
- `server/app/` was a real 6-stage backend (health / db / beets_engine / download / transcode /
  normalize); **T-007 adds the 7th + 8th: `import_seam` (the gate) + `artwork` (cover art).**
- **T-006 DONE** (`6ed1841`, pushed) — `normalize.py`: pure `normalize_title(raw, artist=None)`
  between download and the beets seam. Strips promotional bracket/pipe cruft (**token-set** rule: a
  group goes only when *every* word is promo — official/video/audio/lyrics/hd/4k/1080p — so real
  qualifiers Live/Remix/2022 Remaster/feat. stay) + a leading `Artist - ` prefix **only when it
  matches the known embedded artist** (not a blind cut-before-first-dash — that discarded real
  titles like "Bohemian Rhapsody - Remastered 2011"). Empty-query guard. `/code-review` high
  (workflow, 15 agents): **7 findings, all applied** (the load-bearing one: artist-aware strip).
  103 normalize tests, suite **126 green**. Learning transcribed (artist-aware, not blind dash).
- **T-007 walkthrough Artifact built** (private, pre-build teaching aid) — the fingerprint-trust
  gate explained: why singletons floor at ~0.11 (can't reach `strong`), the trust-identity move
  (ADR-006), an **interactive dial** for the score≥0.90 / gap≥0.10 dominance test, the
  `ImportSession.choose_item` shape, and the honest open question (where the AcoustID score lives
  behind a beets candidate vs the tag distance the spike measured).
  URL: `https://claude.ai/code/artifact/c8ecf382-a996-48bf-a9a7-d6a79051663d`.
- **T-005 DONE** (`b371f2a`) — `transcode.py`: `transcode_to_mp3_320` re-encodes the T-004 staged
  bestaudio → **MP3 320 CBR** via ffmpeg `libmp3lame -b:a 320k` (CBR by contract — no `-q:a`),
  `-map_metadata 0` carries tags, `-vn` drops any thumbnail stream, ID3v2.3. Typed `TranscodeError`.
  Sync/blocking (worker thread, ADR-001). **Verified end to end**: real download → transcode →
  ffprobe = codec mp3 @ 320000 bps, title/artist intact. `/code-review` high (workflow, 14 agents):
  **5 findings, all applied** — input-overwrite guard now covers explicit dest aliasing the source
  (`resolve()` cmp, not just the default-`.mp3` branch; `-y` would've truncated the input mid-decode),
  dest-parent mkdir like the download stage, 300s subprocess timeout (corrupt source can't wedge the
  worker), + 2 test gaps (nonzero-exit path, format-level bit_rate fallback). 6 tests, suite 23 green.
- **Both optional API keys now in `.env`** (git-ignored, verified loaded in-process): **`LASTFM_APIKEY`**
  (32-char → `lastgenre` fetches genres; **T-018 effectively closed**) and **`ACOUSTID_APIKEY`**
  (10-char → `chroma` *submission*; lookups already worked on beets' built-in key). Last.fm shared
  secret deliberately NOT stored — only signs *write* requests, we only read.
- **T-001 DONE** — `server/app/` (`main.py` lifespan config receipt, `config.py` pydantic-settings
  off repo-root `.env`, `routes/health.py`). Setup uses **`uv`** (no `python3-venv`) — see
  `server/README.md`.
- **T-002 DONE** (`b612115`) — `db.py`: SQLite `jobs` + `reviews` tables (spec §6), stateless DAO,
  candidate MBIDs stored as JSON not objects (ADR-006), schema init in lifespan, DB on disk (survives
  restart). `/code-review` high: 4 applied (FK-enforce pragma, WAL, rowcount guards on both updates),
  2 rejected (lru_cache + startup-write — deliberate/consistent).
- **T-003 DONE** (`88e17a0`) — `beets_engine.py`: builds the beets config + explicit
  `load_plugins()` (ADR-007 — all six load, proven), optional keys wired, boot smoke check logs a
  receipt or warns DEGRADED. beets pinned 2.12. `/code-review` high: 4 applied (beets imported in
  lifespan not module-top, false-green-fpcalc guard, WSL isfile vs X_OK, subprocess via to_thread),
  1 rejected. **`fpcalc` v1.5.1 now installed** to `~/.local/bin` (on PATH, no sudo) → boots
  `beets engine ready` (all 6 plugins + fpcalc). T-007 is unblocked for live verification.
- **T-004 DONE** (`57e6517`) — `download.py`: yt-dlp bestaudio + `--embed-metadata` into staging
  (no MP3 transcode — that's T-005), pure playlist classifier (→ T-012's 422). 17 unit tests +
  `pytest.ini`. Live download verified in-agent (tagged `.webm` landed). `/code-review` high: 2
  applied (dead host-set removed, pytest pythonpath), 1 rejected.
- **Fan-out mechanics (worked well, reuse):** 3 parallel worktree build agents (T-002/03/04, all
  depend only on T-001, disjoint files) → integrate one at a time on `main`, `/code-review` high
  (workflow-backed) each diff in the working tree before commit, reconcile shared files
  (`requirements.txt`/`README.md`/`main.py`) by hand. I own the accept/reject on every finding.
- **`docs/r1/tickets.md` (committed) — 19 tickets, 3 phases:**
  **A engine spine** (T-001…T-011: FastAPI skeleton → SQLite → beets config+plugins → download →
  transcode → normalize → **T-007 fingerprint-trust seam** → threshold tuning → dedup → Jellyfin
  scan → retry), **B API+orchestration** (T-012 worker-thread job queue+routes, T-013 SSE, T-014
  review list/resolve), **C UI** (T-015 paste+Go, T-016 SSE card, T-017 review panel), + T-018
  owner Last.fm key, T-019 full §7 verify sweep. Spine is script-provable before any web layer.
  T-007 is the biggest ticket (gated behind 5); T-008 tunes ADR-006's score/gap knob on a real
  sample and writes the re-measured auto-accept rate back into the ADR.
- **Spec has a rendered companion Artifact** (single-page R1 dossier, private) — kept in sync with
  `spec.md`; URL in the session log below. Not a source of truth, a read-view for owner sign-off.
- **`docs/r1/spec.md` WRITTEN** — full 7-section build-ready spec. R1 scope locked to
  **one YouTube song per run** (batches → R2, playlists → R2, migrate → R2). Match gate =
  **fingerprint-trust auto-accept (ADR-006)** else review queue. App **triggers a Jellyfin scan**
  after landing. MP3 320 → `…\Music\CleanMuzik`. Lyrics in. FastAPI routes + SSE event catalogue +
  SQLite schema all specified. Two things left open by design: the numeric fingerprint score/gap
  thresholds (build-time knob — measure, don't guess) and owner sign-off on the spec.
- **`.env` created + populated** (git-ignored) — Jellyfin API key, **`LASTFM_APIKEY`**, and
  **`ACOUSTID_APIKEY`** all set (see the T-005/keys entry above). `.env.example` committed as the
  template.
- **All three owner facts LOCKED** (the spec's inputs):
  1. **Jellyfin library folder** → `C:\Users\aj_am\Music\CleanMuzik` (WSL: `/mnt/c/Users/aj_am/Music/CleanMuzik`).
     Jellyfin **installed native on Windows** this session (Phase 0), Music library pointed there,
     empty. "Auto-refresh metadata: Never" set (protects beets' tags). Jellyfin ADR-008 to record.
  2. **Existing library** → 15 month-batch folders under `C:\Users\aj_am\OneDrive\Documents\`
     (`April2024MUsic` etc.). **Measured: 3.2 GB, 855 MP3** + 37 `.webm` + broken-download debris
     (`.part`/`.ytdl`/`.mhtml`). Also lives on his **phone** (overlapping copies → R2 dedup input).
     Destination after extraction: `C:\Users\aj_am\Music` (out of OneDrive to stop cloud sync).
  3. **Keys/secrets** → Last.fm key later (setup ticket; genres won't fetch till then). AcoustID
     needs **no** personal key (beets' built-in lookup key works — proven in spike). Secrets → `.env`.
- **The beets spike is RESOLVED** (prior session): 0/3 auto-accept on singletons → **ADR-006**
  (trust fingerprint identity in `choose_match`, review queue is the primary path) + **ADR-007**
  (beets 2.12 plugin loading). Writeups in `docs/r1/`.
- **Owner-education track started** — `docs/primers/` (NOT `learnings.md`): full-bleed HTML
  explainers. Built **01 VPN-vs-VPS** + **03 network-map** (published Artifacts, linked in
  `docs/primers/README.md`). Track A 02/04/05 + Tracks B/C parked for later sessions.
- **Lyrics decided IN for R1** — add beets `lyrics` plugin; owner to flip Jellyfin "Save lyrics
  into media folders" on. Metadata philosophy: R1 = every cheap plugin on (genre/year/art/lyrics);
  acoustic tier (Essentia, BPM/key) stays deferred.
- `client/` still stock Vite (untouched until Phase C UI tickets). `server/` is now the FastAPI
  skeleton (Express dropped in T-001); the pipeline stages (download/transcode/beets) don't exist yet.

## Session log

### 2026-07-15 (session 11) — T-009 duplicate handling; Phase A spine complete

- **Pushed session-10's backlog** — `53bea61` (T-010) was committed-not-pushed; pushed it, then
  `main` == `origin/main`.
- **Discussed the fan-out question first** (owner asked if a parallel pocket was coming). Mapped the
  remaining dependency graph: the rest of R1 is mostly a serial chain, NOT the wide leaf-set that made
  the T-002/03/04 fan-out clean. T-009 solo, **T-012 solo by design** (it's the integration keystone —
  parallelizing the thing that stitches the others is a merge mess), and the one genuine pocket is
  **T-013 (server SSE) ∥ T-015 (client paste+Go)** after T-012. Recorded in the phase line above.
- **Built T-009** (`2c3c3d9`) — acquire-time duplicate handling; **the spine's last sibling, so
  Phase A is now complete.** Read the beets 2.12 importer to find the real hook is
  `get_duplicate_action` (not the ticket's `resolve_duplicate`), that it fires *before* the file is
  copied/added (so a SKIP leaves no phantom), and that REMOVE deletes-before-copies.
  - **First cut had a data-loss bug I introduced; the review caught it.** `/code-review` high
    (workflow) returned 4 findings, all confirmed: the destructive REMOVE window (#1, load-bearing),
    a pre-apply tag read (#3), mb_trackid detection scope (#2), and a park-path dup (#4). #1 drove a
    full rework to a **non-destructive** design (never auto-delete; cover-based partial order; upgrade
    → review). Adjudicated + fixed all four. **184 tests green.** Two learnings transcribed.
  - **Surfaced the spec deviation to the owner** (spec §5 said "drop the other"). Owner chose the
    **non-destructive** option (the one I recommended). Recorded as **ADR-009**; annotated spec §5 and
    tickets so code and the signed-off spec don't silently disagree.
- **NEXT:**
  1. **T-012 — Phase B keystone: worker-thread job queue + `/api/jobs` routes.** Wires every stage
     into one sequential run (ADR-001), creates the job row before the pipeline (import_song's FK
     precondition), owns staging cleanup + the playlist-422, and is where a full **live re-paste**
     verify of T-009 finally becomes drivable. Keep it **solo** (integration point).
  2. After T-012: the **T-013 ∥ T-015** fan-out (server SSE + client shell, disjoint), then T-016
     (convergence) → T-014 → T-017.
  3. Optional cheap confidence: a targeted re-review of T-009's reworked non-destructive path (I
     changed the model substantially mid-ticket; tests cover it, an extra pass is cheap).
  4. Carry-overs (housekeeping): "proactively flag learnable moments" → global `~/.claude/CLAUDE.md`;
     build the **artifact-visual-style skill**, then drop the redundant project-memory copy.

### 2026-07-14 (session 10) — T-011 retry/backoff + owner key; intro primer; A3 redeployed

- **Redeployed primer A3** (item 1 carry-over) — the claude.ai 500 cleared; the public copy now shows
  the final gap-decided verdict. Git source was already correct, no file change.
- **Built + published an intro primer for a friend** (owner request) — full-bleed non-technical
  walkthrough: the old Googled-"youtube to mp3" routine, the real pain (inconsistency + title-only
  tags across phone/computer), the tool cast in plain words, and an **SVG network diagram** (devices ⇄
  home server → internet, Phase 0/1 toggle). Refined the pain section per owner correction (it was the
  *inconsistency* — a different random converter each time, one crammed title field, nothing else).
  Committed `6e8f205` as `docs/primers/00-what-is-cleanmuzik.html`.
- **Built T-011** (committed `1c3b952`) — the identify-stage retry + owner AcoustID key. Discussed the
  fork with the owner (T-009/T-010/T-011 are *siblings*, all deps only T-007 — "next" = highest-value
  unblocked, not lowest number) and recommended T-011: it removes a *measured, live* pain (T-008's
  shared-key throttling) rather than adding surface. Owner approved value-order.
  - Retry only the lookup (fingerprint once), 1→2→4s backoff; `_resolve_api_key` wires the owner's key
    with the shared key as fallback (verified against real `.env`).
  - **`/code-review` high (workflow) caught a real flaw I'd introduced:** retrying an invalid key is
    futile and would silently mass-park every song after a 7s stall each. Root cause: pyacoustid
    surfaces a rate-limit and a bad key identically (non-ok status), split only by `error.code`. Fixed
    with a permanent-vs-transient split (`AcoustidPermanentError`, fail-fast + ERROR log). Adjudicated
    all 5 findings (3 applied, 1 moot-after-fix, 1 rejected — see Current State). Transcribed the
    lesson to learnings.md. **167 tests green.**
- **NEXT:**
  1. **Push `main`** — `1c3b952` (T-011) + `6e8f205` (primer) + this `docs(hot)` are committed but
     **not yet pushed** to `origin/main`. (Owner asked to push this session.)
  2. **T-010** (Jellyfin scan trigger) — small, and the one remaining spine sibling that gates Phase B
     (T-012 lists it as a dep). Then **T-009** (acquire-time dedup: keep-better-copy tie-break,
     ambiguous → review). After the spine siblings: Phase B (T-012 worker-thread job queue + routes).
  3. Optional: a targeted re-review of T-011's permanent/transient split (I introduced the flaw and
     fixed it same-session — tests cover it, but an extra pass is cheap confidence).
  4. Carry-overs (housekeeping): "proactively flag learnable moments" → global `~/.claude/CLAUDE.md`;
     build the **artifact-visual-style skill**, then drop the redundant project-memory copy.

### 2026-07-14 (session 9) — T-008: thresholds tuned on 25 real songs; gap switched off

- **Ran the measurement, not a guess.** Built a throwaway harness (scratchpad `measure.py`) and drove
  **25 real songs** through the fingerprint gate: **15 owner-library files** (deliberately including
  tag-less, bare-title rips — the worst case) + **10 fresh YouTube rips** from an owner-supplied,
  deliberately international playlist (5 more lost to rate-limit). Result: **22 correct auto-accepts,
  0 wrong, 3 genuine no-matches**; correct all 0.955–0.995, no-matches 0.0. **Auto-accept ≈88%.**
- **The load-bearing finding: the gap check is dead weight.** A high runner-up was *always* the SAME
  recording listed twice in AcoustID, never a rival — so a gap floor only false-parked certain
  matches (Kanye "Through The Wire": 0.987 vs a 0.977 duplicate). **`SCORE_MIN=0.90` held,
  `GAP_MIN=0.10→0.0`** (kept as an off-by-default knob). Written into the **ADR-006 addendum**.
- **Owner caught a real error.** The board/config called his `ACOUSTID_APIKEY` a *submission* key —
  wrong. Verified empirically it's a valid **application/lookup** key (own quota). "Submission" only
  describes how *beets* uses a provided key. The seam still uses pyacoustid's shared built-in key
  (throttles hard); **T-011 wires his key in + retry/backoff.** Correction saved to learnings.md.
- **Answered his no-match curiosity:** AcoustID returns the exact recording or an EMPTY set — no
  ranked maybes. The "maybe this/that" list is a *separate* MusicBrainz title-search path. Bare-title
  tagless files park empty; a fresh rip parks *with* candidates because it carries its title.
- **Published primer A3** ("Score vs Gap") — full-bleed house-style walkthrough with a real scatter of
  all 25 songs; teaches gap-vs-score for a non-tech reader. (Final redeploy 500-ing on claude.ai at
  session end — retry; git source correct.) Also logged the **private-playlist yt-dlp trap** (owner-
  reported: fails opaquely as "invalid URL"; must be public/unlisted).
- **`/code-review` high (workflow):** 4 findings — 2 applied (stale API_KEY comment, primer verdict
  framing), 1 rejected (GAP_MIN=0.0 tradeoff is the intended decision), 1 empty. **159 tests green.**
  Committed + pushed `a353ec7`. This board lands as the `docs(hot)` follow-up.
- **NEXT:**
  1. **Retry the A3 artifact redeploy** (claude.ai was 500-ing) so the public copy shows the final
     gap-decided verdict.
  2. **T-009** — acquire-time duplicate handling (`resolve_duplicate`: keep-better-copy, ambiguous →
     review), OR continue the spine: **T-010** (Jellyfin scan trigger), **T-011** (identify retry +
     backoff — now *also* owns wiring the owner's AcoustID app key into `fingerprint_dominance`).
  3. Carry-overs still open (housekeeping): "proactively flag learnable moments" → global
     `~/.claude/CLAUDE.md`; build the **artifact-visual-style skill**, then drop the redundant
     project-memory copy.

### 2026-07-14 (session 8) — T-007 built: the fingerprint-trust spine + Door B cover art

- **Built T-007, the spine** (uncommitted). De-risked the artifact's open question *first* by reading
  the installed beets source — found `chroma` **discards** the AcoustID score (keeps only recording
  MBIDs), so the seam reads it via its **own `acoustid.lookup`**. Wrote `import_seam.py`
  (`fingerprint_dominance` + `FingerprintTrustSession.choose_item` gate) and `artwork.py`. Two
  high-effort `/code-review` workflow passes; adjudicated every finding (owned accept/reject).
- **Owner chose Door B** (finish art+lyrics *in* T-007, not a follow-up) — "the art means so much to
  me." Root cause: beets `fetchart` skips singletons (`if task.is_album:`). Built `artwork.py`:
  Cover Art Archive (by release MBID, full-res) → iTunes (artist-verified) → beets-native embed.
  Explained **ShazamIO is the wrong tool** (it *recognizes* songs, which we already do via AcoustID;
  unofficial/fragile, dropped per ADR-005) — art comes from CAA/iTunes using the ID we already earned.
  Lyrics already worked (LRCLib); flipped `synced` on for Jellyfin.
- **Verified end-to-end on a real song** (a-ha "Take On Me"): auto-landed MP3 320 with
  title/artist/year/genre + **synced lyrics** + **849 KB Cover Art Archive cover**, zero clicks; weak
  song parks with candidates. **158 tests green.**
- **Owner-education:** kept the T-007 walkthrough Artifact in sync (added a "what's the runner-up?"
  panel + plain-words open-questions), and built **A2 "It filed its first song"** explainer
  (`https://claude.ai/code/artifact/99232026-d1ba-42a9-97b9-4252f834822a`) — plain-terms status +
  the Door A/B decision. Both sources versioned under `docs/primers/` (App-stack track in the README).
- **NEXT:**
  1. ✅ T-007 committed + pushed (`3065731`). This board + primers land as a follow-up `docs(hot)`.
  2. **T-008** — tune the score/gap thresholds on a larger real sample; write the measured auto-accept
     rate back into ADR-006. (The free AcoustID tier throttles the 2nd lookup — T-011 retry/backoff is
     the designed absorber; note this when measuring.)
  3. Minor follow-ups (non-blocking): genre canonicalized to a generic "Music" (lastgenre whitelist
     tuning); the 2-lookups-per-song cost (could reuse chroma's cached fingerprint later).
  4. Carry-overs still open: "proactively flag learnable moments" → global `~/.claude/CLAUDE.md`;
     build the **artifact-visual-style skill**, then drop the redundant project-memory copy.

### 2026-07-13 (session 7) — T-006 normalization done; T-007 walkthrough built, build deferred

- **Built T-006** (`6ed1841`, pushed) — the title-normalization stage. First pass had a real bug the
  review caught: a **blind** leading-`Artist -` strip cut everything before the first spaced dash,
  which destroys titles like `"Bohemian Rhapsody - Remastered 2011"`. Reframed the fix around the
  session's own conversation — the download already embeds the artist tag, so strip the prefix
  **only when it matches the known artist**; with no artist, keep the title. Also switched promo
  detection to a **token-set** rule (strip a bracket/pipe group only when every word is
  promotional) which fixed the under-stripping findings cleanly, + an empty-query guard.
  `/code-review` high workflow-backed (15 agents): 7 findings, **all** adjudicated legit and applied.
  103 tests, suite 126 green. Committed + pushed.
- **Product question surfaced + resolved (music-video vs official-audio):** owner asked whether to
  preserve a "video version" marker. Walked the **load-bearing distinction** — the normalized title
  is a *query*, not the final tag; MusicBrainz supplies the clean title regardless, and video-audio
  vs audio-only is the *same recording/fingerprint*. The one case that genuinely differs (a live
  edit) is already handled: `(Live)` is a kept qualifier, so it routes to review, not mislabel. No
  code change. Verdict: leave stripping as-is.
- **Built a pre-build T-007 walkthrough Artifact** (owner-education track, studio-charcoal/signal-
  green house style, full-bleed, interactive dominance dial). Owner asked for it explicitly to
  understand the seam *before* we build it. URL in Current State above.
- **NEXT:**
  1. **T-007 — the fingerprint-trust seam (ADR-006). Deferred to next session by owner's call.**
     We walk the design together (using the Artifact) *before* writing code. It's the spine + the
     biggest ticket; deps T-002/03/05/06 all ✓, fpcalc provisioned. First thing to prove when
     building: **how to read the AcoustID fingerprint score off the chroma result** (the spike
     measured beets' tag *distance* ≈0.11, but ADR-006 gates on the *fingerprint* score — a
     different number). If awkward to reach, the seam bends around it.
  2. Then T-008 (tune the score/gap thresholds on a real sample, write the rate back into ADR-006).
  3. Carry-overs (housekeeping, non-blocking): "proactively flag learnable moments" → global
     `~/.claude/CLAUDE.md`; build the **artifact-visual-style skill**, then drop the redundant
     project-memory copy.

### 2026-07-13 (session 6) — T-005 transcode done; both API keys landed

- **Owner grabbed both optional API keys.** Walked the Last.fm `api/account/create` form — only
  email/name/description needed; Callback URL + homepage are OAuth-only, left blank. Clarified the
  **shared secret** only signs *write* requests (scrobble/love) → we read only, so it's not stored.
  Both keys pasted into `.env`, verified loaded in-process (Last.fm 32-char, AcoustID 10-char).
  **T-018 effectively closed**; engine now boots fully provisioned.
- **Built T-005** (`b371f2a`, pushed) — the transcode stage. Sequential/blocking by design. Real
  end-to-end receipt captured (download → transcode → probe = mp3 @ 320000, tags intact). Ran
  `/code-review` high workflow-backed; adjudicated all 5 findings as legit and applied every one
  (the load-bearing one: explicit-dest-aliasing-source would've truncated the input — now guarded
  by a `resolve()` comparison). Details in the Current State entry above.
- **Working mode held** (per session 5's agreement): worked the mechanics quietly, surfaced only
  the two decisions (push? / start T-006?). No concept flagged this ticket — T-005 is plumbing;
  T-007 is where "singleton"/"confidence gate" get named.
- **NEXT:**
  1. **T-006 — title normalization.** Pure function: strip `(Official Audio|Video|Lyrics)` cruft +
     a leading `Artist - ` prefix (the Rick Astley test title `... (Official Video) (4K Remaster)`
     is a live example). Unit-testable, no network. Feeds the beets query. Gate before T-007.
  2. Then **T-007** — the ImportSession fingerprint-trust seam (ADR-006). Biggest ticket, now fully
     unblocked (T-002/03/05/06 the deps; fpcalc provisioned). Flag it as conceptually central.
  3. Carry-overs still open (housekeeping, not blocking): "proactively flag learnable moments" →
     global `~/.claude/CLAUDE.md`; build the **artifact-visual-style skill** then drop the redundant
     project-memory copy.

### 2026-07-12 (session 5) — first fan-out: T-002/03/04 built, reviewed, committed

- **Ran the first parallel pocket.** Three worktree build agents (T-002 SQLite, T-003 beets config,
  T-004 yt-dlp) — all depend only on T-001, touch disjoint files. Each committed to its own worktree
  branch; I integrated onto `main` one at a time, ran `/code-review` high (workflow-backed) on each
  diff in the working tree, adjudicated every finding (applied real ones, rejected with evidence),
  re-verified, committed. Then removed the three worktrees + branches.
- **T-002** (`b612115`): applied FK-enforce pragma, WAL journal, rowcount guards on both `update_*`;
  rejected lru_cache + startup-write (deliberate). Restart-persistence re-proven.
- **T-004** (`57e6517`): applied dead `_YOUTUBE_HOSTS` removal + `pytest.ini` pythonpath; rejected
  `bestaudio/best` fallback change. 17 tests green.
- **T-003** (`88e17a0`): applied beets-in-lifespan (so `import app.main` doesn't need beets),
  false-green-fpcalc guard, WSL isfile-not-X_OK, subprocess via `asyncio.to_thread`; rejected the
  configure_beets reconfigure finding. Full lifespan boots: config → store → all 6 plugins (DEGRADED
  only because fpcalc isn't provisioned here — the correct path).
- **Owner check-in (important):** Armand flagged overwhelm at the volume of mechanical detail
  (task lists, code-review findings). Agreed working mode: **option 1 — I work quietly on mechanics,
  surface only his decisions, BUT proactively name load-bearing concepts** (like "singleton"). Gave
  him the 5-term vocabulary (beets / singleton / fingerprint / review queue / confidence gate). Saved
  as harness memory `surface-load-bearing-concepts`. Flag T-007 as conceptually central when reached.
- **NEXT:**
  1. ✅ Pushed `main` (T-002/03/04 + board) to `origin/main`.
  2. Build the **linear spine**: T-005 (ffmpeg → MP3 320 CBR, ADR-002) → T-006 (title
     normalization, pure fn) → **T-007** (the ImportSession fingerprint-trust seam — the spine, the
     biggest ticket, gated behind T-002/03/05/06). Not a fan-out; sequential, one at a time.
  3. Carry-overs still open: "proactively flag learnable moments" → global `~/.claude/CLAUDE.md`;
     build the **artifact-visual-style skill** then drop the redundant project-memory copy;
     owner Last.fm key (T-018). ✅ `fpcalc` v1.5.1 installed to `~/.local/bin` (WSL side; the
     Phase-1 dedicated PC will need its own copy). Boots `beets engine ready`.

### 2026-07-12 (session 4, cont.) — T-001 built: FastAPI skeleton, Express dropped

- **Built + shipped T-001** (`7050bc2`). `server/app/` FastAPI package: `main.py` (app + lifespan
  config receipt logging which capabilities are wired, no secrets printed), `config.py`
  (pydantic-settings reading the git-ignored **repo-root** `.env` via `parents[2]`), `routes/health.py`
  (`GET /api/health`). Pinned `requirements.txt` (fastapi 0.139 / uvicorn 0.51 / pydantic-settings
  2.14) + `requirements-dev.txt` (httpx2 for TestClient). Express scaffold deleted.
- **Env note:** no `python3-venv` on this WSL box — used **`uv`** for the venv (`uv venv .venv`;
  `uv pip install --python .venv/bin/python`). Documented in `server/README.md`. `.venv` gitignored.
  Sandbox blocks foreground-shell → background-task localhost sockets, so verified routes via
  **`fastapi.testclient.TestClient`** (no socket) rather than curl.
- **Verified:** `/api/health` → 200 `{"status":"ok"}`, unknown route → 404, `.env` loads in-process
  (jellyfin_api_key present, lastfm/acoustid unset — matches the real file).
- **`/code-review` high (workflow-backed, 13 agents):** 6 findings. Applied 4 (stale CLAUDE.md
  "spike not build" banner + spec "(skeleton)" annotation → build phase; run-command dedup → README
  canonical; `logging.basicConfig` moved import-time→lifespan). **Rejected 2 with evidence:** the
  "`httpx2` is nonexistent, use `httpx`" finding is wrong here (starlette 1.3.1 *requires* httpx2;
  install + TestClient proven), and the dropped-`PORT`-env finding (Express boilerplate, not an
  invariant; `uvicorn --port` is the override). Owner first vetted the code-review skill's provenance
  — confirmed built-in/Anthropic-official, not a third-party download.
- **NEXT:** the first real **fan-out pocket** — T-002 (SQLite), T-003 (beets config+plugins), T-004
  (yt-dlp download) all depend only on T-001 and touch different files → spawn as parallel
  worktree build agents, I integrate + `/code-review` each. Then T-005→T-006→T-007 (the seam).

### 2026-07-12 (session 4) — spec signed off, R1 tickets generated

- **Owner signed off `docs/r1/spec.md`** ("the spec looks good") — the gate to tickets.
- **Wrote `docs/r1/tickets.md`** — decomposed the spec into **19 build-ordered tickets** in the
  file's own format (Status / Depends on / Agent / What / Done-when, each Done-when tying back to a
  §7 acceptance item). Three phases: **A engine spine** first (T-001–T-011, script-provable with no
  web layer — same discipline as the spike), then **B API+orchestration** (T-012–T-014), then
  **C UI** (T-015–T-017), + T-018 owner Last.fm key, T-019 whole-checklist `/verify` sweep.
- **Deliberate structure calls:** T-007 (the `choose_item` fingerprint-trust seam) is the spine and
  is gated behind SQLite/beets-config/transcode/normalize; T-008 makes ADR-006's numeric score/gap
  threshold its **own** ticket (measure on a real sample, then write the re-measured auto-accept
  rate back into the ADR); T-012 owns the worker thread + playlist-422 + staging cleanup; every §7
  item maps to a ticket, with T-019 catching the cross-cutting ones (localhost/nothing-exposed).
- **NEXT:**
  1. **Commit** `docs/r1/tickets.md` + this board (docs-only; `/code-review` + `/verify` don't
     apply until there's runnable code).
  2. **Flip roadmap** R1 line to "spec signed off, tickets written" (currently "spec written").
  3. **Start building — T-001** (FastAPI skeleton + `/api/health` + `.env` loading, drop Express).
     This is the first `in-build` ticket and the first `/code-review`-able diff.
  4. Carry-overs (still open): "proactively flag learnable moments" → global `~/.claude/CLAUDE.md`;
     build the **artifact-visual-style skill** then drop the redundant project-memory copy; owner
     to grab the **Last.fm API key** (now formalized as T-018). Later: Track A primers 02/04/05.

### 2026-07-12 (session 3) — spec companion Artifact, "singleton" defined, QUERY parked

- **Built a rendered R1-spec Artifact** — single-page dossier (studio-charcoal / signal-green,
  green=landed / amber=review / red=error-&-fence, mono headings, pipeline as the hero, sticky
  contents rail). Private; owner may share for a phone view. Faithful to `spec.md`, not a new
  source of truth. URL: `https://claude.ai/code/artifact/d7c07a38-dd65-49d1-b2bb-10c3a4d1d7a2`.
- **Defined "singleton"** in `spec.md` §2 (+ matching callout in the Artifact): beets is album-first;
  a YouTube song is always a lone track with no album context, so tag-distance floors ~0.11 and
  never hits `strong` → that's *why* the gate trusts the fingerprint (ADR-006). Owner asked; it was
  load-bearing but undefined.
- **HTTP QUERY (RFC 10008) tangent → resolved as a no.** Owner surfaced the new 2026 method and asked
  if it fit (smart playlists / LLM-assisted queries). Worked the trade-off: QUERY's only edge over
  `POST` is proxy-caching + semantic honesty, both worthless on a single-user `localhost`/Tailscale
  tool; ecosystem support thin. **Decision: don't build.** Parked in `docs/backlog/` with the verdict
  baked in so it isn't re-litigated.
- **Clarified the smart-playlist story** (no code, just alignment): CleanMuzik owns **no** playlist
  feature by design — Jellyfin does searching/playlists/playback; CleanMuzik writes the tags that
  power them. R1's descriptive tags already unlock genre/artist/decade filtering + Instant Mix in
  Jellyfin; rules-based auto smart-playlists come from a Jellyfin **plugin** (community, not core —
  unverified on owner's install); "by feel" needs the deferred Essentia acoustic tier.
- **Committed + pushed** `ca862f9` (spec singleton note + backlog QUERY entry).
- **NEXT (unchanged, still the gate):**
  1. **Owner sign-off on `docs/r1/spec.md`** — then generate **`docs/r1/tickets.md`** (the gate to
     `in-build`). Owner was mid-read this session.
  2. Optional: confirm on the owner's Jellyfin install what smart-playlist capability is native vs
     needs the community plugin.
  3. Carry-overs: "proactively flag learnable moments" → global `~/.claude/CLAUDE.md`; build the
     **artifact-visual-style skill**, then drop the redundant project-memory copy; owner to get a
     **Last.fm API key** (R1 setup ticket). Later: Track A primers 02/04/05; Tracks B/C.

### 2026-07-12 (session 2) — R1 spec written, ADR-008, .env wired

- **Wrote `docs/r1/spec.md`** end to end (all 7 sections; the skeleton is now real). Resolved the
  open scope forks with the owner:
  - **Input scope → one YouTube song per run.** Owner's call: prove base functionality first, then
    scale up. Batches + playlists + migrate all pushed to R2. (ADR-001/003 batch rules aren't
    exercised until then.)
  - **Match gate → fingerprint-trust (ADR-006).** Owner: "fingerprint matches it first and
    foremost; if it can't, send it to a review queue." Auto-accept on dominant AcoustID identity,
    else park. Numeric score/gap thresholds left as a build-time knob (candidate: score ≥ 0.90,
    gap ≥ 0.10 — measure, don't hard-code).
  - **Jellyfin scan → app-triggered** (owner picked option 1). App calls the Jellyfin API after a
    track lands so it appears in seconds; needs `JELLYFIN_URL` + `JELLYFIN_API_KEY`.
- **Recorded ADR-008** — native Jellyfin on Windows (not Docker) for Phase 0; watched folder
  `C:\Users\aj_am\Music\CleanMuzik` IS beets' output dir; auto-refresh-metadata = Never.
- **Roadmap** — R1 line flipped to "scoped, spec written."
- **`.env` wired** — created `.env.example` (committable template) + real `.env` (git-ignored);
  owner pasted the **Jellyfin API key** in. Confirmed `.env` is git-ignored before any secret went
  near the repo. Nothing reads it yet — captured for the build.
- **Committed + pushed** the spec + ADR-008 + roadmap + `.env.example`.
- **NEXT (next session):**
  1. **Owner sign-off on `docs/r1/spec.md`** (read-through) — then generate **`docs/r1/tickets.md`**
     from it (decompose into build tickets; this is the gate to `in-build`).
  2. Carry-overs from session 1, still open: add "proactively flag learnable moments" to the
     **global** `~/.claude/CLAUDE.md`; build the **artifact-visual-style skill** then drop the
     redundant project-memory copy.
  3. Owner to get a **Last.fm API key** (unblocks genre) — a setup ticket in R1.
  4. Later: Track A primers 02/04/05; Tracks B/C.

### 2026-07-12 (session 1) — Jellyfin installed, 3 facts locked, owner-education primers started

- **Installed Jellyfin** (native Windows, Phase 0) end-to-end with the owner over screenshots.
  Recommended **native over Docker** for Phase 0 (single laptop; Docker's portability is a Phase-1
  concern) → record as **ADR-008**. Music library → `C:\Users\aj_am\Music\CleanMuzik`. Walked the
  metadata settings: "auto-refresh from internet: **Never**" (beets is the tagger, don't let
  Jellyfin overwrite), Image Extractor on (shows beets' embedded art), remote access left on
  (Tailscale-forward-compatible; not internet-exposed).
- **Locked all three owner facts** (see Current State). Measured the existing library myself over
  `/mnt/c` (3.2 GB / 855 MP3 + webm/junk). Established the clean-folder-vs-mess distinction: the
  month-batches are **R2 input**, never hand-copied into the clean `CleanMuzik` library.
- **Decisions:** lyrics **in** for R1 (beets `lyrics` plugin + Jellyfin lyrics display). Library
  lives at `C:\Users\aj_am\Music`, **out of OneDrive** (cloud-sync trap). Noted `.webm`/broken-file
  debris + phone-source overlap as **R2 scope**.
- **Started `docs/primers/`** — full-bleed HTML owner-education artifacts, deliberately separate
  from `learnings.md`. Built & published **Primer 01 (VPN vs VPS)** and **Primer 03 (network map,
  with a Phase 0/1 toggle + the download-journey)**. Indexed in `docs/primers/README.md`.
- **Meta / process:** owner clarified where knowledge should live — **visual/build prefs → a skill**
  (not global CLAUDE.md), and the **global `~/.claude/CLAUDE.md`** should carry the *behavioural*
  principle "proactively flag learnable moments." Both **parked for a fresh session**. (Earlier this
  session, unprompted, saved harness memories `proactive-investigation-log` + `artifact-visual-style`
  and grafted the craft insight to the garden — the artifact-style one is a candidate to move into
  the planned skill.)
- **NEXT (next session):**
  1. **Write `docs/r1/spec.md`** — all inputs are in hand. Fold in: lyrics-in-R1, the
     fingerprint-trust rule (ADR-006), the `C:\...\Music\CleanMuzik` output path, `.env` secrets.
     Reconcile the Essentia "phase 2" vs roadmap "R3+" numbering while there. Record **ADR-008**
     (native Jellyfin + the watched-folder path).
  2. Add the "proactively flag learnable moments" principle to the **global** `~/.claude/CLAUDE.md`.
  3. Build the **artifact-visual-style skill**; then remove the redundant project-memory copy.
  4. Later: Track A primers 02/04/05; Tracks B/C; owner to get a Last.fm API key.

### 2026-07-11 (session 3) — Beets spike RESOLVED; auto-accept measured; repo cleanup

- **Ran the beets review-queue spike end to end** (throwaway venv in scratchpad — beets 2.12,
  yt-dlp, ffmpeg, static `fpcalc` pulled from Chromaprint GitHub, no sudo). Drove a subclassed
  `ImportSession` (`choose_item` for singletons), read `task.rec`/`task.candidates`, wrote nothing.
- **The seam works** and the number is measured: **0/3 auto-accept** on three easy, well-known
  tracks. A bare YouTube *singleton* plateaus at `rec=medium` (dist ~0.11 floor — no album context),
  never `strong`. Title-cleaning promoted a `none`→`medium` and fixed ranking but didn't cross the
  bar. → **ADR-006** (trust dominant AcoustID fingerprint in `choose_match`) + **ADR-007** (beets
  2.12 plugin loading). PRD's "~80% auto-accept" refuted for singletons.
- Debug detour (recorded): candidates were empty until I (1) called `plugins.load_plugins()` — the
  library API doesn't auto-load, and (2) enabled `musicbrainz` (a separate plugin in 2.12) so chroma
  could resolve MBIDs, and (3) re-downloaded with `--embed-metadata` (untagged files → empty-query
  400). All in `learnings.md`.
- **Repo cleanup:** deleted `client/` + `server/` `node_modules` (149M, untracked/regenerable).
  Left `server/` Express scaffold in place (tracked code — deletion is a separate call).
- **Docs written:** `spike-beets-review-queue.md` (lab notebook), `experiment-auto-accept-rate.md`
  (readable report — also rendered as a full-bleed Artifact), ADR-006/007, learnings entries.
- **Learnings side-channel:** saved a behavioural memory (`proactive-investigation-log`) — detect
  when a task becomes a multi-cycle investigation and start a log unprompted — and grafted the
  generalizable craft version to the garden (`.inbox/pending/2026-07-11-detecting-learning-moments.md`,
  pending `/garden` ingest). Also saved `artifact-visual-style` (large fonts, full-bleed).
- **NEXT:** the gate is open — before writing `docs/r1/spec.md`, get the three owner facts (Jellyfin
  watched-folder path; existing-library location/format/size; where the Last.fm/AcoustID keys live),
  and plan to re-measure the auto-accept rate on a larger sample *after* the fingerprint-trust
  `choose_match` rule exists (the 0/3 is directional, n=3).

### 2026-07-11 (session 2) — Harness scaffold, design reviews, hygiene pass

- Walked the owner (new to the architecture) through the spec-first workflow: Brief→Spec→Tickets
  →Build→Learn, the ADR/learnings ratchet, and the file-based continuity model.
- **Scaffolded `docs/`** — roadmap + r1/{spec,tickets,architecture,adr} + repo-level learnings +
  backlog. spec/tickets left as gated stubs; adr seeded 001–005 from PRD constraints.
- **Ran two independent reviews** (general-purpose sub-agents): architecture engineer (stack) and
  harness engineer (workflow). Verdict from both: proceed, stack + process are right-sized for a
  solo tool. Both converged on the **beets review-queue seam** as THE thing to settle before spec.
- **Seam resolved** (arch review, confirmed vs beets source): subclass `beets.importer.ImportSession`,
  override `choose_match(task)` — `task.candidates` (ranked matches) + `task.rec`
  (none/low/medium/strong). Strong→auto-accept; weak→record candidates, return SKIP, park.
  **Drive the importer** (keeps chroma/fetchart/embedart/lastgenre as stages) — never call
  `autotag.tag_item` directly. Parking non-blocking; beets runs in a **worker thread**; add
  **SQLite persistence** storing candidate *IDs* not objects; YouTube songs import as *singletons*
  so real auto-accept rate < PRD's "~80%" — must be measured. All folded into `architecture.md`.
- **Hygiene pass** (harness review): collapsed 4-way stack/constraint duplication to single homes
  (`architecture.md` owns the diagram, `adr.md` owns the constraints; `CLAUDE.md` + this board
  link, don't restate); added a "Start here / read-in-order" block + "spike, not build" phase
  truth to `CLAUDE.md` and this board; added a **Definition of Done** (`/code-review` + `/verify`)
  to `CLAUDE.md`; moved `learnings.md` to repo level with a write-trigger; ADR note marking 006+
  as build-born.
- **Dedup requirement raised + placed.** Owner downloads tracks ad hoc on phone + computer →
  inconsistencies + duplicate songs. Split into two problems: **(A) acquire-time dupe check** →
  **R1** (beets `resolve_duplicate`; auto-keep the better copy, **ambiguous → review queue** —
  owner's call); **(B) full existing-library dedup + re-tag** → **R2 migrate/clean** (`beet
  duplicates` + `chroma` acoustic fingerprinting, catches dupes across different filenames/tags).
  Recorded in `architecture.md` (R1 policy) and `docs/backlog/` (R2 scope). Open sub-question for
  the spec: the auto-keep tie-break (bitrate vs tag quality).
- **NEXT:** run the **beets spike** — a throwaway script driving `ImportSession` on ~2 sample
  YouTube URLs, printing `task.rec` + `task.candidates` and **measuring the real auto-accept
  rate** → record outcome as **ADR-006**. Needs beets + yt-dlp + ffmpeg installed locally + a
  couple of sample URLs. THEN the owner hands over 3 facts: Jellyfin watched-folder path,
  existing-library location/format/size, and where the Last.fm/AcoustID keys live. THEN write
  `docs/r1/spec.md`. (Also unresolved: whether to commit this session's `docs/` + `CLAUDE.md`.)

### 2026-07-11 — Pivot from showcase to personal tool; new spec; board created

- Grilled the whole idea end to end. Resolved: personal tool (no showcase, no "secret mode");
  wrap **beets** as the tag engine (not hand-rolled ShazamIO/Mutagen); descriptive metadata
  tier for v1 (genre/year/art via `lastgenre`/`fetchart`/`embedart`), acoustic tier
  (BPM/key/energy via Essentia) deferred to phase 2; **confidence-gated review queue** as the
  UI centrepiece; output **MP3 320**; **FastAPI** backend, drop Express; React kept for the UI.
- Hosting: build on the laptop at `localhost` now (phase 0), move to a dedicated always-on PC
  + **Tailscale** later (phase 1). No VPS — library must live where Jellyfin runs.
- Wrote `cleanmuzik-prd.md` (new source of truth), rewrote `CLAUDE.md`, archived the two old
  PRDs to `archive/`. Committed + pushed (`2022c5e`).
- **NEXT:** de-risk before the full build — spike the **beets review-queue mechanism** (how to
  surface candidate matches to a custom UI: beets Python API vs subprocess parse). Also confirm
  the existing-library location/format/size and the Jellyfin install target + watched-folder
  path (PRD §11).

## Where the rest of the context lives

- **Business/vault context** (pricing, prospects, decisions, positioning) lives in the
  **garden**, not here — query it with `/garden`.
- This repo's own docs: `cleanmuzik-prd.md` (spec), `CLAUDE.md` (how-to-work), `archive/`
  (superseded PRDs, history only).
