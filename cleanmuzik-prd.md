# CleanMuzik — PRD (v2, personal edition)

> **Supersedes** `music-cleaner-prd.md` and `cleanmuzik-secret-mode-prd.md`. Those describe an
> earlier, abandoned design (portfolio showcase, shared tool, hand-rolled ShazamIO + Mutagen
> engine, hidden "secret mode" easter egg). This document is the current source of truth.

## 1. What changed and why

CleanMuzik started as a portfolio showcase — a shared tool built on a deliberately chosen
React/Express/Python stack, with the YouTube-download feature hidden behind a "secret mode"
easter egg. That framing is dead. This is now a **single-user personal tool**. The owner does
not care who else can use it, does not need to hide anything, and no longer picks the stack to
study it. The only goal is: **get music into a clean, richly-tagged Jellyfin library, easily,
with a UI that's a pleasure to use.**

## 2. The two jobs

The app does two distinct things:

1. **Acquire** — paste a YouTube song or playlist URL → download audio → identify → tag →
   land it, organized, in the Jellyfin library. This is the primary, everyday flow.
2. **Migrate + clean** — point the tool at the owner's existing music library, fingerprint and
   re-tag everything with canonical metadata + embedded artwork, and organize it into the
   Jellyfin folder structure. Largely a one-time job (repeatable as the library grows).

Jellyfin is the **central hub** — library, storage, streaming, and (for now) playback.

## 3. Goals

- Paste one or many YouTube URLs (single tracks *and* playlists) and walk away
- Rich **descriptive** metadata on every track: title, artist, album, year, label, track/disc
  numbers, **genre**, and **embedded cover art** — enough for fast search and genre/artist/decade
  playlists in Jellyfin
- Files land **organized** (`Artist/Album/`) directly in the Jellyfin library
- A **sick, real-time UI**: per-track cards animating through download → identify → tag → done,
  with a **review queue** for ambiguous matches as the centrepiece
- Migrate and clean the existing library with the same engine

## 4. Non-goals (v1)

- No multi-user, no accounts, no auth (single trusted user; access secured at the network layer)
- No "secret mode" / easter-egg trigger — the app openly does what it does
- No acoustic metadata yet (BPM/key/energy) — see Roadmap phase 2
- No custom music player yet — Jellyfin plays; see Roadmap phase 3
- No cloud/VPS hosting — the library lives at home (see §9)
- No formats other than MP3 for output (see §8)

## 5. Architecture

The engine is Python (beets, yt-dlp, ffmpeg), so the backend is Python and there is **no
Node/Express middleman** — the previous design's only purpose for Node was to shell out to
Python, which a Python backend does natively.

```
React + TS + Vite  (sick UI, SSE progress, review queue)
        │  HTTP + Server-Sent Events
        ▼
FastAPI  (Python backend, job queue, SSE, review-queue state)
        │  drives, per track, sequentially:
        ├─ yt-dlp   → download bestaudio
        ├─ ffmpeg   → extract/encode to MP3 320
        └─ beets    → identify (MusicBrainz + AcoustID), fetch genre + artwork,
        │             embed art, organize into Artist/Album/
        ▼
Jellyfin library folder (local disk)  →  Jellyfin serves + plays
```

### 5.1 Tech stack

| Layer | Technology | Notes |
|---|---|---|
| Frontend | React, TypeScript, Vite | Keep. The UI is the craft. Likely Tailwind + a motion lib for the animated pipeline. |
| Backend | **Python, FastAPI** | Replaces Express. Native async + SSE fits real-time progress. |
| Download | **yt-dlp** | Handles single tracks and playlists (expands to N tracks). |
| Transcode | **ffmpeg** | Extract/encode to MP3 320. |
| Tag engine | **beets** | Identify, fetch metadata + art, organize. See §6. |
| Fingerprint | beets `chroma` plugin (AcoustID / Chromaprint `fpcalc`) | Identifies rips with poor/missing tags. |
| Genre | beets `lastgenre` plugin (Last.fm) | MusicBrainz alone is thin on genre. |
| Artwork | beets `fetchart` + `embedart` | High-res art, embedded into the MP3. |
| Library/player | **Jellyfin** | Central hub. Finamp is a good mobile client. |
| Remote access | **Tailscale** (phase 1) | Mesh VPN to reach the home server. Not a VPS. |

## 6. Metadata strategy

**Descriptive tier (v1).** beets core does MusicBrainz matching; plugins fill the rest:
`chroma` (AcoustID fingerprinting for unknown rips), `lastgenre` (genres), `fetchart` +
`embedart` (cover art). Result per track: title, artist, album, year, label, track/disc #,
genre, embedded art — the data that powers fast search and genre/artist/decade playlists.

**Acoustic tier (phase 2, self-built).** BPM, musical key, energy, danceability — for smart
"by feel" playlists. AcousticBrainz (the old free source) is frozen since 2022, so this means
running **Essentia** locally over each track. Deliberately deferred; it must not block v1.

## 7. Match confidence + review queue

This is the product's spine. beets' autotagger produces a **match confidence** per track.

- **Strong match** → auto-tag, organize, land in Jellyfin. No human needed. (The ~80% case;
  "paste a playlist and walk away.")
- **Weak / ambiguous match** (common for YouTube rips — live versions, remixes, "Official
  Video", multiple candidate releases) → drop into a **review queue** in the UI, where the
  owner picks the correct release / artwork from candidate matches.

This reconciles "walk away" with "I want good metadata." The auto-accept threshold maps to
beets' `strong_rec_thresh`. **Open design question / spike:** how to surface beets' candidate
matches to a custom UI — drive beets via its Python API (finer control over the importer) vs.
subprocess + parse. Resolve before building Epic 3.

## 8. Audio format

**Output: MP3 320.** Rationale: universal device compatibility, best-supported ID3 tags +
embedded artwork, uniform with a likely-existing MP3 library. Quality is capped by the source —
YouTube serves ~128–160 kbps Opus/AAC — so MP3 320 preserves the source transparently (adds no
audible loss on top); it cannot add quality YouTube never had. Accepted and fine for a
YouTube-sourced personal library. For an album where fidelity truly matters, rip it lossless
outside this tool.

## 9. Hosting — phased

The library must live on the machine Jellyfin runs on (Jellyfin reads local disk; beets writes
there). So the processing app runs wherever Jellyfin runs — **home, not a VPS**. A VPS is a
*place to run things*; a VPN is a *way to reach* a machine you own. This project needs the
latter.

- **Phase 0 (now):** Everything on the owner's current laptop, `localhost`. Prove the pipeline
  and metadata quality. No always-on, no remote access.
- **Phase 1 (later):** Migrate to a dedicated always-on box (a PC the owner plans to buy) and
  add **Tailscale** for private phone access from anywhere. Nothing exposed to the public net.

## 10. Roadmap

| Phase | Scope |
|---|---|
| **0 — Pipeline on laptop** | FastAPI + React skeleton; yt-dlp → ffmpeg → beets → Jellyfin working at localhost; descriptive metadata; single-URL then playlist; the animated progress UI; the review queue. Also: migrate the existing library. |
| **1 — Real home server** | Move to dedicated always-on PC; Tailscale remote access. |
| **2 — Acoustic metadata** | Local Essentia analysis → BPM/key/energy tags → smart playlists. |
| **3 — Custom player** | A bespoke React player against the Jellyfin REST API. |

## 11. Open questions to resolve before building

- **Existing library**: where does it currently live, what format/size, so migration (job 2) and
  the MP3-320 uniformity decision are grounded in reality.
- **beets integration mechanism**: Python API vs subprocess (§7 spike) — decides how the review
  queue is built.
- **Jellyfin**: install target on the laptop (native vs Docker) and the watched-folder path that
  becomes beets' output directory.

## 12. Superseded material

`music-cleaner-prd.md` and `cleanmuzik-secret-mode-prd.md` are retained only for history. Their
stack (Express middleman), engine (hand-rolled ShazamIO + Mutagen), and "secret mode" easter-egg
framing are **no longer the plan**. Do not implement from them.
