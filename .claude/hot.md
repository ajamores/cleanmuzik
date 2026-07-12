---
type: meta
title: "Hot — cleanmuzik"
updated: 2026-07-11-s3
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

**Phase: spike, not build.** Read-to-orient, not ready-to-build until the beets review-queue
seam is proven. See `docs/r1/architecture.md`.

## Current State (2026-07-11 · s3)

- **Branch `main`** — spike session's docs committed this session. `node_modules` (client 117M +
  server 32M) deleted from disk — untracked/gitignored, fully regenerable; nothing lost.
- **The beets review-queue spike is RESOLVED** — the gate before spec is cleared. Seam proven
  end-to-end; auto-accept rate **measured at 0/3** on easy singletons. Two decisions recorded:
  **ADR-006** (auto-accept via dominant AcoustID fingerprint identity, not relaxed thresholds; the
  review queue is the *primary* path — the PRD's "~80%" is false for singletons) and **ADR-007**
  (beets 2.12: MusicBrainz is a separate plugin; library API doesn't auto-load plugins). Full
  writeup: `docs/r1/experiment-auto-accept-rate.md` (readable) + `spike-beets-review-queue.md` (lab
  notebook). Rendered as an Artifact too.
- **Harness scaffold** (`docs/`): `roadmap.md`, `r1/{spec,tickets,architecture,adr,spike-*,experiment-*}.md`,
  `learnings.md` (now populated with spike gotchas), `backlog/`. `spec.md` + `tickets.md` still
  **gated stubs** — but the gate is now open (spike done).
- Still **spec, not build**: `client/` stock Vite, `server/` Express `/health` scaffold to be
  dropped for FastAPI. No pipeline code exists yet.

## Session log

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
