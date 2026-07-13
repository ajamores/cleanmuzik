# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Start here (read in this order)

1. **`CLAUDE.md`** (this file) — how we work
2. **`cleanmuzik-prd.md`** — product source of truth (scope + design)
3. **`docs/roadmap.md`** — which release is active
4. **`docs/r1/spec.md`** — what R1 builds *(written + owner signed off)*
5. **`docs/r1/architecture.md`** — the stack diagram + open technical seams (single home)
6. **`docs/r1/adr.md`** — binding decisions; do not silently reverse one
7. **`docs/learnings.md`** — mistakes already paid for; don't repeat them
8. **`.claude/hot.md`** — live session state + what's next

**Current phase: R1 build, ticket by ticket.** The review-queue seam is proven (the beets
spike → ADR-006/007), the spec is written and signed off, and `docs/r1/tickets.md` holds the
19 build tickets. Building has begun (T-001: FastAPI backend). Work the tickets in dependency
order; each is done per the Definition of Done below.

## What this is

CleanMuzik is a **single-user personal tool** for building a clean, richly-tagged Jellyfin music
library. It does two jobs:

1. **Acquire** — paste a YouTube song or playlist URL → download audio → identify → tag →
   land it, organized, in the Jellyfin library. The everyday flow.
2. **Migrate + clean** — re-tag and organize the owner's existing library with the same engine.

Jellyfin is the central hub (library, storage, streaming, playback). The app is the front door
that gets clean, well-tagged music into it.

**The source of truth for scope and design is `cleanmuzik-prd.md`.** Read it before building.
The older `music-cleaner-prd.md` and `cleanmuzik-secret-mode-prd.md` describe an **abandoned**
design (portfolio showcase, Express-middleman stack, hand-rolled ShazamIO + Mutagen engine,
hidden "secret mode") — do **not** implement from them.

## Current state vs. plan

Read this before assuming anything exists. The repo predates the current design and is **mostly
stale scaffold**:

- `client/` — stock Vite + React 19 template (`App.tsx` is the default landing page). React is
  **kept** in the new plan; this specific UI is placeholder.
- `server/` — Express 5 app with one `/health` route. Express is **being dropped** — the new
  backend is Python/FastAPI. This directory will be replaced, not extended.
- **Not present yet:** FastAPI, beets, yt-dlp, ffmpeg integration, Jellyfin wiring, SSE, the
  real UI. All planned per `cleanmuzik-prd.md`.

Build against the PRD, not the existing `server/` code.

## Architecture (target)

Python engine → Python backend, **no Node/Express bridge**. The full stack diagram and the open
technical seams live in **`docs/r1/architecture.md`** — its single home; don't restate them here.
The three things worth carrying in your head:

- **beets is the tagging engine** — never hand-roll one. Plugins do the work: `chroma` (AcoustID),
  `lastgenre` (Last.fm genres), `fetchart` + `embedart` (cover art).
- **The review queue is the product's spine.** beets emits a confidence per track; strong matches
  auto-tag, weak ones (common for YouTube rips) go to a review queue. A UX centrepiece, not an
  afterthought.
- **Progress is SSE**, not polling.

### Hard constraints

The binding constraints — sequential processing (no parallelizing the pipeline), MP3 320 output,
one-failure-continues-the-batch, single-user/no-auth, beets-not-hand-rolled — are recorded as
**ADR-001–005 in `docs/r1/adr.md`**, their single home. A review checks new code against them;
do not silently reverse one.

## Commands

Client (`cd client`):
- `npm run dev` — Vite dev server
- `npm run build` — `tsc -b && vite build`
- `npm run lint` — ESLint

Server (`cd server`) — Python/FastAPI (the Express scaffold was dropped in T-001). The canonical
setup + run commands live in **`server/README.md`** — don't duplicate them here. In short:
`uvicorn app.main:app --reload` serves `GET /api/health`; secrets load from the git-ignored
**repo-root** `.env` (spec §6, template in `.env.example`).

There is no automated test runner wired yet; `requirements-dev.txt` adds the FastAPI `TestClient`
used to verify routes without a socket.

There is no root-level workspace tooling — packages are managed independently.

## Definition of Done (per ticket)

A ticket is done when there's a receipt, not a claim:

1. **Review pass** — `/code-review` on the diff (correctness bugs + cleanup).
2. **Observable artifact** — for pipeline tickets, `/verify`: drive the actual flow and confirm
   the real side effect (e.g. a correctly-tagged MP3 320 with embedded art landed in the Jellyfin
   folder). "The code looks right" is not done; "I watched it happen" is.
3. **Transcribe corrections** to `docs/learnings.md` as they come up.

`/code-review` and `/verify` are built-in Claude Code skills, not project code — `/code-review`
*reads* the diff, `/verify` *runs* it. They cost tokens per run and `/verify` needs the app
runnable, so they apply during build, not to the current stub phase.

## Hosting

Runs where Jellyfin runs (Jellyfin reads local disk; beets writes there) — **home, not a VPS**.
Phase 0: the owner's laptop at `localhost`. Phase 1: a dedicated always-on PC reached via
**Tailscale** (a VPN to reach an owned machine — not a VPS, which would mean hosting the library
in the cloud). See `cleanmuzik-prd.md` §9 for the phased plan.

## Session board

Active workstream state for this repo lives in `.claude/hot.md` (the repo's hot board), per the
`/hot` and `/maintenance` conventions. Keep tasks and open items there and in the PRD's open-
questions section — not in this file.
