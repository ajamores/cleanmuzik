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
- **Duplicate policy, acquire-time — SETTLED BY ADR-009 + T-009 (built). `adr.md` is authoritative;
  this is the summary.** Two things the original plan got wrong, both corrected:
  - **Detection is our own direct library query, NOT beets' `resolve_duplicate(task)`.** beets builds
    its probe from the match's `TrackInfo`, where the recording id sits under `track_id` — *before*
    the `track_id→mb_trackid` mapping — so a `duplicate_keys=mb_trackid` query matches **nothing** and
    detection silently never fires. We query `lib.items(MatchQuery("mb_trackid", rec_id))` ourselves
    inside `choose_item`; beets' own stage is kept as an inert no-op.
  - **R1 is NON-DESTRUCTIVE and never auto-deletes.** The earlier "clear cases auto-resolve keeping
    the better copy, drop the other" wording is **withdrawn** — it held a data-loss window (beets'
    `manipulate_files` deletes the old file *before* it copies the new one; a failed copy loses
    **both**). Instead: keep the existing copy when it's at **>= bitrate**; **park** a strictly
    higher-bitrate upgrade to the review queue for the owner to confirm. Compare is **bitrate-only**
    at acquire time (tags aren't applied yet). Auto-replace (copy-first/delete-after) and the
    tag-richness tie-break are deferred to **R2**.

  Full *existing-library* dedup sweep (`beet duplicates` + `chroma` acoustic fingerprinting) is
  **R2 migrate/clean**, not R1 — see `docs/backlog/`.
- [ ] **Secrets** — Last.fm API key (`lastgenre`), AcoustID key (`chroma`). Where they live: TBD (owner).
- [ ] Existing library location / format / size (for R2 migrate, but confirm now).
- [ ] Jellyfin install target + watched-folder path on disk.

*(This file is the single home for the stack diagram and technical seams — CLAUDE.md and hot.md
link here rather than restating.)*

## Component decisions

_(fill as they firm up — job queue shape, SSE transport details, review-queue state store)_
