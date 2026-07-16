# R1 Architecture — CleanMuzik

Technical decisions for R1. The *how*, where the spec is the *what*. Target stack is fixed by
`cleanmuzik-prd.md`.

> **Status: the R1 seams are settled and built** (Phase A + B complete; Phase C in progress).
> This file is a **map of what was decided and why**, not a list of open questions. Binding
> decisions live in `adr.md` — where the two disagree, **`adr.md` wins**. Ticket status is in
> `tickets.md`; neither is restated here.

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

## The seams (settled + built)

- **beets import seam — `choose_item(task)`, and the gate is fingerprint identity (ADR-006/007).**
  Subclass `beets.importer.ImportSession` and import the song as a **singleton**; the singleton hook
  is **`choose_item(task)`** (`choose_match(task)` is the *album* hook — not our path). Plugins run
  as import stages, so **drive the importer — never call `autotag.tag_item` directly** or you lose
  them. Two things the spike disproved, both load-bearing:
  - **`task.rec` cannot gate this.** A bare YouTube singleton can't reach `strong` on tag distance —
    measured floor ~0.11 vs the ≤0.04 `strong` needs (no album/track#/year to corroborate). The
    original "strong → auto-accept, weak → park" plan yields **0/3**. So the gate is **AcoustID
    fingerprint dominance**, not `rec`.
  - **chroma computes the AcoustID score then discards it**, keeping only recording MBIDs — so the
    number ADR-006 gates on never reaches a beets candidate. The seam recovers it via its **own**
    `acoustid.lookup` (`fingerprint_dominance`). Cost: 2 lookups/song; the free tier throttles the
    second, so the seam **parks rather than crashes** on `AcoustidLookupError` (T-011 adds retry +
    the owner's key).
  - Thresholds (T-008, measured on 25 real songs): **`SCORE_MIN=0.90`; the gap check is off by
    default** — a high runner-up was always the *same* recording listed twice, never a rival, so any
    gap floor only false-parked certain matches. Re-measured auto-accept **≈88%** → ADR-006 addendum.
  - `importer`/`autotag` are **not** beets' stable API — beets is pinned at **2.12**; treat an
    upgrade as re-testing this seam. Plugins need explicit `load_plugins()` (ADR-007) — the library
    API doesn't auto-load them the way the CLI does.
  - **Cover art:** `fetchart` has `if task.is_album:` and **skips singletons**, so `artwork.py`
    fetches it (Cover Art Archive → iTunes fallback) and embeds via beets' `art.embed_item`.
- **Parking is non-blocking; beets runs off the event loop (ADR-001).** `ImportSession.run()`
  blocks, so the import runs in a **worker thread** — never on the asyncio loop. `choose_item`
  returns `Action.SKIP` and the parked file is resolved later, solo. R1 is one song per job, so the
  original "must not stall the rest of the batch" concern is moot until batches land in R2.
- **Persistence (SQLite).** `jobs` + `reviews` (spec §6) outlive a reboot; candidate **MBIDs stored
  as JSON, not rich objects** — re-matched on resume (ADR-006). Live per-stage detail lives in an
  in-memory `JobRegistry` (capped 256) that does **not** survive restart; the `GET` snapshot overlays
  the two, and boot reconciliation marks crash-orphaned jobs `error`.
- **Staging + cleanup.** Removed on every terminal path **except a park** — the parked file *is* the
  copy the owner resolves; cleanup moves to resolve time (T-014). See `spec.md` §5, which is
  authoritative on the carve-out.
- **Idempotency — partial, by design.** A re-paste is caught by the acquire-time duplicate check
  (recording-id match in `choose_item`, see below) — which is *after* download and transcode, so a
  re-paste still costs a download. Pre-download URL-level skip was never built and isn't ticketed;
  it's an efficiency nicety, not a correctness gap (the dedup catches it either way, and the same
  song under a different URL wouldn't be caught by URL matching anyway).
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
- **Secrets — the git-ignored repo-root `.env`** (template: `.env.example`), loaded via
  pydantic-settings (spec §6). `LASTFM_APIKEY` (genres) and `ACOUSTID_APIKEY` (the owner's private
  lookup quota) are set. **Absent optional key = degrade, not fail**: no genre is not an error. The
  Last.fm shared secret is deliberately not stored — it signs *write* requests; we only read.
- **Existing library — measured, R2 input.** 3.2 GB / 855 MP3 + debris across 15 month-batch folders;
  sizing and destination live in `docs/backlog/`. R1 never reads it.
- **Jellyfin — native on Windows (Phase 0), library at `C:\Users\aj_am\Music\CleanMuzik`** (WSL:
  `/mnt/c/...`), "Auto-refresh metadata: Never" set so it can't overwrite beets' tags (ADR-008).
  The app POSTs `/Library/Refresh` after a track lands. Three-way contract: scanned / degraded
  (config absent → warn, track still landed) / `JellyfinScanError` (configured but failed → the job
  emits `track.error` stage=`scan`). **Note:** from WSL2, `localhost` can't reach the Windows-hosted
  Jellyfin (separate net namespace) — the `.env` stays `localhost` because the app runs on Windows
  in Phase 0; probing from WSL needs the gateway IP (see `learnings.md`).

## Component decisions

- **Job queue — a single `JobWorker` thread draining a `queue` (ADR-001).** `POST /api/jobs` only
  *enqueues*; concurrent pastes still run one at a time. The pipeline walks
  download → transcode → normalize → `import_song` → Jellyfin-scan sequentially. Routes stay
  import-light so `import app.main` doesn't pull beets (the T-001 lazy-engine contract).
- **SSE transport — hand-rolled, not `sse-starlette`.** `events.py` owns an `EventBus`: a per-job
  channel = replay buffer + `closed` flag + subscriber `asyncio.Queue`s. The worker thread publishes
  via `loop.call_soon_threadsafe` (outside the lock); `stream()` snapshots the buffer **and**
  registers its queue under one lock, so an event lands in exactly one of replay/live. Hand-rolled
  because `ping` must be a real named event. **An absent channel is not "still running"** — the
  route passes durable status as a `terminal` hint, or an evicted completed job pings forever
  (see `learnings.md`).
- **Review-queue state — SQLite `reviews` + the in-memory registry.** The durable row (staging path,
  candidate MBIDs as JSON, `rec`) is the source of truth and survives restart; the registry only
  carries process-lifetime stage detail.

*(This file is the single home for the stack diagram and technical seams — CLAUDE.md and hot.md
link here rather than restating.)*
