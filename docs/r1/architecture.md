# R1 Architecture — CleanMuzik

Technical decisions for R1. The *how*, where the spec is the *what*. Target stack is fixed by
`cleanmuzik-prd.md`; this file records the concrete choices as they firm up.

## Stack (from PRD)

```
React + TS + Vite  (UI, SSE progress, review queue)
      │  HTTP + Server-Sent Events
      ▼
FastAPI             (job queue, SSE, review-queue state)
      │  per track, sequentially:
      ├─ yt-dlp  → download bestaudio
      ├─ ffmpeg  → encode to MP3 320
      └─ beets   → identify (MusicBrainz + AcoustID), genre + art, embed, organize
      ▼
Jellyfin library folder (local disk) → Jellyfin serves + plays
```

- **beets is the tagging engine** — plugins do the work: `chroma` (AcoustID), `lastgenre`
  (Last.fm genres), `fetchart` + `embedart` (cover art). No hand-rolled tagger.
- **No Node/Express bridge** — the engine is Python, so the backend is Python.

## Open technical questions (resolve before / during spec)

- [ ] **beets review-queue seam — confirm, don't re-architect.** Not "Python API vs subprocess"
      (subprocess-parsing stdin/stdout is a dead end). The path: subclass
      `beets.importer.ImportSession`, override `choose_match(task)` and `resolve_duplicate(task)`.
      Each `task` carries `task.candidates` (ranked `AlbumMatch`/`TrackMatch`) and `task.rec`
      (confidence enum: none/low/medium/strong). Strong → auto-accept; weak → record candidates,
      return SKIP, park it. Plugins (chroma/fetchart/embedart/lastgenre) run as import stages, so
      **drive the importer — never call `autotag.tag_item` directly** or you lose them. The spike
      only proves this runs locally and **measures the real auto-accept rate on our own URLs**
      (YouTube songs import as weaker-matching *singletons*, so expect more review volume than
      the PRD's "~80%"). Outcome → ADR-006. `importer`/`autotag` are not beets' stable API — pin
      the beets version; treat an upgrade as re-testing this seam.
- [ ] **Parking is non-blocking.** `ImportSession.run()` blocks; a weak match must not stall the
      rest of the batch. `choose_match` returns SKIP and the parked file is re-imported later,
      solo. beets import runs in a **worker thread**, never on the asyncio event loop.
- [ ] **Persistence (SQLite).** Job/track status + parked reviews outlive a reboot. Store the
      staging path + MusicBrainz candidate IDs + rec — **not** the rich candidate objects; re-match on resume.
- [ ] Staging dir + cleanup-on-failure; idempotency (re-paste same URL → skip if already present).
- **Duplicate policy, acquire-time — DECIDED.** beets detects dupes on import via
  `resolve_duplicate(task)` (matches on MusicBrainz IDs → catches the same song under a different
  filename). Clear cases auto-resolve keeping the better copy (higher bitrate / better tags);
  **ambiguous cases go to the review queue** — the same confidence-gated UI, reused for "these two
  look identical, keep which?". Open sub-question for the spec: the exact auto-keep tie-break
  (bitrate vs tag quality). Full *existing-library* dedup sweep (`beet duplicates` + `chroma`
  acoustic fingerprinting) is **R2 migrate/clean**, not R1 — see `docs/backlog/`.
- [ ] **Secrets** — Last.fm API key (`lastgenre`), AcoustID key (`chroma`). Where they live: TBD (owner).
- [ ] Existing library location / format / size (for R2 migrate, but confirm now).
- [ ] Jellyfin install target + watched-folder path on disk.

*(This file is the single home for the stack diagram and technical seams — CLAUDE.md and hot.md
link here rather than restating.)*

## Component decisions

_(fill as they firm up — job queue shape, SSE transport details, review-queue state store)_
