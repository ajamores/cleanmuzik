---
type: meta
title: "Hot — cleanmuzik"
updated: 2026-07-13
last-commit: 6ed1841
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

**Phase: R1 IN BUILD — T-001…T-006 done, T-007 next (deferred to next session by owner).** Spec
signed off, `docs/r1/tickets.md` holds 19 build-ordered tickets. **T-001–T-006 built, reviewed,
committed + pushed** to `origin/main`. Next: **T-007 (the fingerprint-trust seam — the spine, the
biggest ticket)** — owner and I will walk the design together next session before building; a
pre-build walkthrough Artifact is done (URL in session log). See `docs/r1/tickets.md`.

## Current State (2026-07-13)

- **Branch `main`** — committed **and pushed** to `origin/main` (through T-006, `6ed1841`).
  Working tree: only this board pending. `server/app/` is now a real 6-stage backend (health / db /
  beets_engine / download / transcode / **normalize**); agent worktrees cleaned up.
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
