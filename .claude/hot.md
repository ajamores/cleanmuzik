---
type: meta
title: "Hot — cleanmuzik"
updated: 2026-07-12
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

**Phase: R1 spec WRITTEN — ready to generate tickets.** The beets spike is resolved, all three
owner facts are locked, and `docs/r1/spec.md` is now written and committed. Next real deliverable
is `docs/r1/tickets.md` (decompose the spec into build tickets). See `docs/r1/spec.md`.

## Current State (2026-07-12)

- **Branch `main`** — R1 spec + ADR-008 + roadmap + `.env.example` committed this session.
- **`docs/r1/spec.md` WRITTEN** — full 7-section build-ready spec. R1 scope locked to
  **one YouTube song per run** (batches → R2, playlists → R2, migrate → R2). Match gate =
  **fingerprint-trust auto-accept (ADR-006)** else review queue. App **triggers a Jellyfin scan**
  after landing. MP3 320 → `…\Music\CleanMuzik`. Lyrics in. FastAPI routes + SSE event catalogue +
  SQLite schema all specified. Two things left open by design: the numeric fingerprint score/gap
  thresholds (build-time knob — measure, don't guess) and owner sign-off on the spec.
- **`.env` created + populated** (git-ignored) — **Jellyfin API key is set**
  (`JELLYFIN_URL=http://localhost:8096`). `LASTFM_APIKEY` still blank (genre won't fetch till the
  owner gets one; not a failure). `ACOUSTID_APIKEY` optional (built-in key works). `.env.example`
  committed as the template.
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
- Still no pipeline code: `client/` stock Vite, `server/` Express to be dropped for FastAPI.

## Session log

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
