# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

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

## Architecture (target, per PRD)

The engine is Python, so the backend is Python and there is **no Node/Express bridge**.

```
React + TS + Vite (UI, SSE progress, review queue)
      │  HTTP + Server-Sent Events
      ▼
FastAPI (job queue, SSE, review-queue state)
      │  per track, sequentially:
      ├─ yt-dlp → download bestaudio
      ├─ ffmpeg → encode to MP3 320
      └─ beets  → identify (MusicBrainz + AcoustID), fetch genre + artwork,
      │            embed art, organize into Artist/Album/
      ▼
Jellyfin library folder (local disk) → Jellyfin serves + plays
```

- **beets is the tagging engine** — not hand-rolled. Plugins do the heavy lifting: `chroma`
  (AcoustID fingerprinting for rips with bad tags), `lastgenre` (genres via Last.fm), `fetchart`
  + `embedart` (embedded cover art). Never reintroduce a bespoke ShazamIO/Mutagen tagger.
- **Progress is SSE**, not polling — the UI renders per-track status live.
- **The review queue is the product's spine.** beets emits a match confidence per track. Strong
  matches auto-tag and land in Jellyfin; weak/ambiguous ones (common for YouTube rips) go to a
  review queue where the owner picks the correct release/art. This is a deliberate UX
  centrepiece, not an afterthought.

### Hard constraints (design *with* these)

- **Sequential processing**, one track at a time, with a delay between requests — avoids rate
  limits on identification/download. Do not parallelize the pipeline.
- **One failure must not stop the batch** — surface a per-track error event and continue.
- **Output is MP3 320.** Quality is capped by the YouTube source (~128–160 kbps); MP3 320
  preserves it transparently. Don't add other output formats without a reason.
- **Single-user, no auth.** Security is handled at the network layer (Tailscale), not in-app.

## Commands

Client (`cd client`):
- `npm run dev` — Vite dev server
- `npm run build` — `tsc -b && vite build`
- `npm run lint` — ESLint

Server: **currently** the Express scaffold (`cd server && npm run dev`, i.e. `ts-node index.ts`),
but this is being replaced by a FastAPI service. Once the Python backend exists, document its
run command here (expected: a `uvicorn` invocation). There is no test runner set up in either
package yet; `server`'s `npm test` is a placeholder that exits 1.

There is no root-level workspace tooling — packages are managed independently.

## Hosting

Runs where Jellyfin runs (Jellyfin reads local disk; beets writes there) — **home, not a VPS**.
Phase 0: the owner's laptop at `localhost`. Phase 1: a dedicated always-on PC reached via
**Tailscale** (a VPN to reach an owned machine — not a VPS, which would mean hosting the library
in the cloud). See `cleanmuzik-prd.md` §9 for the phased plan.

## Session board

Active workstream state for this repo lives in `.claude/hot.md` (the repo's hot board), per the
`/hot` and `/maintenance` conventions. Keep tasks and open items there and in the PRD's open-
questions section — not in this file.
