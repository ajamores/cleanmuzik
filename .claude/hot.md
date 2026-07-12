---
type: meta
title: "Hot — cleanmuzik"
updated: 2026-07-11
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

## Current State (2026-07-11)

- **Branch `main` — UNCOMMITTED work in flight.** `git status`: modified `CLAUDE.md`; untracked
  `docs/` and `.claude/`. Nothing committed this session — owner's call.
- **Harness scaffold now exists** (`docs/`): `roadmap.md`, `r1/{spec,tickets,architecture,adr}.md`,
  `learnings.md` (repo-level), `backlog/`. `spec.md` + `tickets.md` are **gated stubs** — not
  written yet, and deliberately so (no tickets before an agreed spec). `adr.md` seeded with
  ADR-001–005 from the PRD's hard constraints; ADR-006+ reserved for build-born decisions.
- **Two design reviews done** (architecture + harness sub-agents) — both say *proceed*; both name
  the beets review-queue seam as the one gate before spec. Findings folded into the docs.
- Still **spec, not build**: `client/` stock Vite, `server/` Express `/health` scaffold to be
  dropped for FastAPI. No pipeline code exists yet.
- Recent history (unchanged): `2022c5e` reframe to personal tool + new stack; `51e5a57` server
  config; `be440ee` init files.

## Session log

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
