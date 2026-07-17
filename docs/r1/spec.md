# R1 Spec — CleanMuzik

> **Status: WRITTEN — 2026-07-12.** The test of done: *an agent that has never seen this
> project could read this file and build the right thing without asking a question.* If a
> section would still make it guess, that section has a hole — fix it here, don't guess in code.

Product brief this narrows: `cleanmuzik-prd.md`. Binding constraints: `docs/r1/adr.md`. The
stack diagram + technical seams: `docs/r1/architecture.md`. Mistakes already paid for:
`docs/learnings.md`.

---

## 1. Goal of R1

Ship the **thinnest end-to-end slice that proves the engine**: paste **one** YouTube song URL,
and a correctly-tagged **MP3 320** — with embedded cover art, genre, year, and lyrics — lands
in the Jellyfin library folder and appears in Jellyfin within seconds, with a live progress UI
showing it happen. When beets can identify the song by acoustic fingerprint it lands with zero
clicks; when it can't, the song waits in a **review queue** where the owner picks the right
match. R1 is one track wide on purpose: it proves the download → transcode → identify → tag →
organize → serve spine before any batch, playlist, or migrate machinery is layered on top.

## 2. In scope

- **One YouTube *song* URL per run** (a single track, not a playlist). Paste → Go → landed.
- **Download** via `yt-dlp` (bestaudio), **transcode** to **MP3 320 CBR** via `ffmpeg`.
- **Title normalization** before matching — strip `(Official Audio)` / `(Official Video)` /
  `(Lyrics)` cruft and a leading `Artist - ` (learnings: promotes the correct candidate to #1).
- **beets import as a singleton**, driving the importer (never `autotag.tag_item` directly), with
  plugins enabled and loaded at startup (ADR-007): `musicbrainz`, `chroma`, `lastgenre`,
  `fetchart`, `embedart`, `lyrics`.

> **What "singleton" means (and why it shapes the gate).** beets is built album-first: its
> confident path imports a *whole album folder* at once, cross-checking track count, track order,
> track numbers, album, and year — the shape of the whole release pins each track down. A
> **singleton** is beets' term for a single track imported *on its own*, with none of that album
> context. R1 imports are **always** singletons: you paste one song URL, you get one file, there is
> no album folder. That is exactly why the match gate can't be beets' normal confidence score — a
> lone track's tag *distance* structurally floors around ~0.11 and never reaches `strong` (needs
> ≤0.04), no matter how well-known the song. So R1 trusts the **acoustic fingerprint** instead,
> which identifies the recording without needing album context. See §5 and ADR-006.

- **Fingerprint-trust auto-accept (ADR-006):** auto-tag when the top AcoustID match is dominant
  (high score, clear gap to the runner-up); otherwise → review queue. This is the match gate.
- **Review queue:** parked songs show their candidate matches; the owner accepts one, picks an
  alternate, or rejects. Resolving lands the track. The queue survives a backend restart.
- **Acquire-time duplicate check** (`resolve_duplicate`): a song already in the library is caught
  by MusicBrainz ID; clear cases auto-keep the better copy, ambiguous cases → review queue.
- **Live progress UI:** a single track card animating through download → transcode → identify →
  (auto-tag | review) → done, driven by **SSE** (ADR: no polling).
- **Jellyfin scan trigger:** after the file lands, the app calls the Jellyfin API so the track
  appears in Jellyfin within seconds — no manual scan.
- **Lyrics** fetched by the `lyrics` plugin and embedded; owner enables Jellyfin's "save lyrics
  into media folders" display separately.
- **Persistence (SQLite):** job status + parked reviews outlive a reboot (store MusicBrainz
  candidate **IDs**, not candidate objects — re-match on resume).
- **Runs at `localhost` on the owner's laptop** (Phase 0). Native Jellyfin on Windows (ADR-008).

## 3. Explicitly out of scope

The fence. Everything below is deliberately *not* R1 — it waits for a later release even though
some of it is tempting to fold in now.

- **Playlists / playlist-URL expansion** → R2. R1 rejects a playlist URL rather than expanding it.
- **Batches / multiple URLs at once** → R2. R1 takes exactly one song URL per run. (ADR-001/003 —
  sequential, one-failure-continues — are *batch* rules; with one song they're satisfied trivially
  and simply aren't exercised until R2.)
- **Migrate + clean the existing library** (the 15 month-batch folders) → R2. R1 never reads or
  touches them.
- **Acoustic tier** — BPM / key / energy via Essentia → deferred. *(Numbering note: PRD §6 calls
  this "phase 2" on the PRD's capability-phase axis; `docs/roadmap.md` calls it "R3+" on the
  release axis. Same feature, two different axes — it is simply post-R1. See §8.)*
- **Custom music player** → R3. Jellyfin plays.
- **Tailscale / remote access / always-on host** → Phase 1. R1 stays on `localhost`, nothing
  exposed to the network.
- **In-app auth / multi-user** — never (ADR-004); security is the network layer.
- **Output formats other than MP3 320** (ADR-002).
- **A manual artwork picker / upload** — art comes from the chosen release via `fetchart`. Hand-
  picking or uploading custom art is not R1.

## 4. User flow (R1)

1. Owner opens the app at `localhost`, pastes **one** YouTube song URL, clicks **Go**.
2. The app creates a job and opens an SSE stream for it. A **track card** appears.
3. The card animates through live stages as the backend works the song **in a worker thread**
   (never on the event loop):
   - **Downloading** — `yt-dlp` pulls bestaudio (with `--embed-metadata`, so beets has a non-empty
     query and a fallback; a bare `-x` rip strips tags → empty MusicBrainz query → HTTP 400, per
     learnings).
   - **Transcoding** — `ffmpeg` → MP3 320 CBR.
   - **Identifying** — title normalized, then beets fingerprints (`chroma` → `fpcalc` → AcoustID →
     MusicBrainz MBID) and ranks candidates.
4. **The gate (ADR-006):**
   - **Fingerprint dominant** → the card shows the matched title/artist/album + art, auto-tags,
     and proceeds to **Landing**. No click.
   - **Weak / ambiguous fingerprint** → the card flips to **Needs review**; the song is parked in
     the review queue and the batch (of one) is not blocked.
5. **Review (only for parked songs):** the review panel shows the candidate matches — per
   candidate: title, artist, album, year, cover thumbnail — plus the normalized query. The owner
   **accepts** the top match, **picks an alternate**, or **rejects** (discard the song). Resolving
   resumes the import applying the chosen candidate.
6. **Landing:** beets applies tags, `lastgenre` adds genre, `fetchart` + `embedart` embed cover
   art, `lyrics` embeds lyrics, and beets organizes the file into `Artist/Album/` under the
   library root. Acquire-time dedup runs here (§5).
7. **Appears in Jellyfin:** the app calls the Jellyfin scan API; within seconds the track shows up
   in Jellyfin. The card reads **Done** with the final path and tags.
8. **On any failure:** the card shows a per-track error naming the failing stage; the staging file
   is cleaned up. (With one song, nothing else is in flight to continue.) **A park is not a
   failure** — a song sent to the review queue **keeps** its staging file; see §5.

## 5. Behaviour details

- **Match confidence gate (ADR-006).** beets' tag distance alone cannot make a bare YouTube
  singleton `strong` (measured floor ~0.11; `strong` needs ≤0.04). So the gate is **not** a
  relaxed `strong_rec_thresh` — it is fingerprint identity. In the singleton hook `choose_item(task)`:
  read the AcoustID result behind the top candidate; **auto-accept** when the top match's
  fingerprint **score is high AND the gap to the runner-up is wide** (dominant); otherwise record
  the candidate IDs + `task.rec` and return `Action.SKIP` to park it. Do **not** lower distance
  thresholds globally. The exact numeric score/gap thresholds are a build-time knob to be tuned and
  then recorded (candidate: score ≥ 0.90, gap ≥ 0.10) — measure on real songs, don't hard-code
  blind.
- **Review queue.** The queue holds **two different questions**, distinguished by the row's `rec`,
  and they resolve differently (bodies in §6):
  - **"What is this song?"** (weak/ambiguous match) — the UI shows each candidate's title, artist,
    album, year, and cover thumbnail, plus the normalized query that was searched. Owner actions:
    **accept top**, **pick alternate**, **reject** (discard). Resolving re-runs the import applying
    the chosen MusicBrainz candidate (re-matched from the stored candidate **ID**, not a cached
    object).
  - **"You already have this — keep which?"** (`rec: "duplicate"`, parked by T-009 when the download
    is a strictly-higher-bitrate copy of a library track). Owner actions: **keep existing**,
    **replace** (lands the upgrade, then deletes the old file — the only deletion R1 performs, and
    only on this click), or **keep both** with an **owner-supplied suffix appended to the title
    tag**. The suffix goes on the tag rather than the filename because Jellyfin displays tags —
    distinguishing two files only on disk leaves two identical-looking rows in the library. beets
    derives the path from the tags, so the filename follows. Keep-both exists because recording-id
    detection isn't infallible (a remaster often shares a recording id): it's the owner's escape
    hatch when the app's "same recording" call is wrong. See ADR-009's addendum.

  The queue is SQLite-backed and survives a restart.
- **Staging retention — a parked song KEEPS its staging file.** Staging is removed on every
  terminal path *except* a park: the parked file **is** the copy the owner resolves, and
  `reviews.staging_path` points at it. Deleting it on the way into the queue makes the resolve
  unimplementable (accept → nothing to land). Cleanup for a park happens at **resolve time**
  (T-014), on both branches — accept (beets consumes it) and reject (discard). A park is **not**
  a failure and must not be swept by the failure rule below.
- **Duplicate handling, acquire-time.** When the incoming song matches one already in the library by
  MusicBrainz recording id (a **direct library query in `choose_item`** — catches the same song under
  a different filename; beets' own import duplicate stage can't see MBID dupes, see ADR-009). **R1 is
  non-destructive and never auto-deletes an existing file (ADR-009, T-009 build decision — supersedes
  the "drop the other" wording below):** keep the existing copy when it's at **>= bitrate** (drop the
  redundant download, no second copy); otherwise **park the strictly-higher-bitrate upgrade to the
  review queue** ("you already have this — keep which?") for the owner to confirm. The comparison is
  bitrate-only at acquire time (tags aren't applied yet and tie for the same recording). The original
  intent — *auto-keep the better copy and drop the other; tie-break higher bitrate, then more complete
  tags, still ambiguous → review* — held a data-loss window (beets deletes before it copies), so
  auto-replace (copy-first/delete-after) and the tag-richness tie-break are deferred to **R2 migrate**.
  Full cross-library dedup by acoustic fingerprint is also R2.
- **Failure of one stage.** Any stage error (download, transcode, identify, tag, land, scan) emits
  a per-track `track.error` event naming the stage and a human-readable message, and the staging
  file is removed — **except where the song was already parked** (staging is retained, see the
  retention rule above; a park committed before a later stage raised must not lose its file). AcoustID is flaky/rate-limited — the identify stage **retries with backoff**
  before it's called a failure (learnings; `chroma` swallows lookup errors so a failed lookup
  otherwise looks like "no match").
- **Output.** MP3 320 CBR, and only that (ADR-002). Embedded: cover art, genre (if the Last.fm key
  is set — see §6; absent key = no genre, not a failure), year, lyrics, plus the standard
  title/artist/album/track ID3 tags.

## 6. Interfaces

### API routes (FastAPI)

| Method | Path | Body / params | Returns |
|---|---|---|---|
| `POST` | `/api/jobs` | `{ "url": "<one youtube song url>" }` | `{ "job_id": "<id>" }`. Rejects playlist URLs with 422. |
| `GET` | `/api/jobs/{job_id}/events` | — | **SSE stream** (see below) for that job. |
| `GET` | `/api/jobs/{job_id}` | — | Job status snapshot (for reconnect / SSE fallback). |
| `GET` | `/api/reviews` | — | Parked reviews: `[{ review_id, job_id, query, candidates[] }]`. |
| `POST` | `/api/reviews/{review_id}/resolve` | see the two body shapes below | `{ "ok": true }`; resumes the import. |
| `GET` | `/api/health` | — | `{ "status": "ok" }`. |

#### `resolve` body — two shapes, keyed by the review's `rec`

The review queue holds two different questions, so resolve takes two different answers. A client
reads `rec` (returned by `GET /api/reviews`) to know which it's answering; the route validates the
body against the row's `rec` and 400s a mismatch rather than guessing.

**Weak/ambiguous match** (`rec` = a beets recommendation name — `none`, `low`, `medium`, …):

```jsonc
{ "choice": "<candidate_id>" }   // apply that MusicBrainz candidate and land it
{ "choice": "reject" }           // discard the song; staging is removed
```

**Duplicate** (`rec: "duplicate"` — "you already have this; the download is higher bitrate"). Per
ADR-009's addendum, the destructive branch is reachable only by an explicit owner click:

```jsonc
{ "choice": "keep_existing" }                       // discard the download, keep the library copy
{ "choice": "replace" }                             // land the upgrade, THEN delete the old file
{ "choice": "keep_both", "suffix": "(2015 Remaster)" }  // land alongside, distinguished by suffix
```

- **`replace` lands before it deletes.** Never the reverse, and never beets'
  `DuplicateAction.REMOVE` — that deletes first and loses both copies if the copy then fails
  (ADR-009). Verify the new file is in place, then remove the old.
- **`suffix` is required for `keep_both`** and is appended to the **title tag** before the import
  applies — *not* to the filename. Jellyfin displays tags, not filenames: two files distinguished
  only on disk still render as two identical rows in the library, which is the confusion the choice
  exists to prevent. beets then derives the path from the tags (`singleton: $artist/$title`, or
  `$track $title` under `default`), so the filename follows for free and beets' own path sanitizer
  handles characters that are illegal on disk. Bound the input: cap the length, strip control
  characters and path separators, and reject empty/whitespace-only — it is owner-typed text that
  reaches a filesystem path. (Single-user localhost, ADR-004: this is about not producing a file the
  owner can't find, not a security boundary.)

### SSE events (event name → payload)

One stream per job. Names are stable; the UI keys the track card off them.

- `job.queued` → `{ job_id, url }`
- `track.downloading` → `{ job_id, pct? }`
- `track.transcoding` → `{ job_id }`
- `track.identifying` → `{ job_id }`
- `track.review_required` → `{ job_id, review_id, query, candidates: [ { candidate_id, title, artist, album, year, art_url, score } ] }`
- `track.tagging` → `{ job_id, chosen: { title, artist, album, year } }`
- `track.done` → `{ job_id, path, tags: { title, artist, album, year, genre, has_art, has_lyrics } }`
- `track.error` → `{ job_id, stage: "download|transcode|identify|tag|land|scan", message }`
- `ping` → `{}` — periodic keepalive so proxies don't drop the stream.

### Disk layout (beets output)

Library root (the Jellyfin watched folder, ADR-008):
`C:\Users\aj_am\Music\CleanMuzik` — WSL path `/mnt/c/Users/aj_am/Music/CleanMuzik`.

beets `paths` config:

```yaml
directory: /mnt/c/Users/aj_am/Music/CleanMuzik
paths:
  default:   $albumartist/$album%aunique{}/$track $title
  singleton: $artist/$title          # R1 songs that carry no album release
  comp:      Compilations/$album%aunique{}/$track $title
```

A single that MusicBrainz resolves to a real release lands under `default` (it has an album); a
truly album-less song lands under `singleton`. beets creates missing directories.

### Secrets (`.env`, git-ignored)

| Key | Needed by | R1 behaviour if missing |
|---|---|---|
| `ACOUSTID_APIKEY` | `chroma` | **Optional** — beets' built-in AcoustID key works (proven in the spike). Set only for higher rate limits. |
| `LASTFM_APIKEY` | `lastgenre` | Genre isn't fetched; the track still lands with all other tags. Owner obtains this via a setup ticket. |
| `JELLYFIN_URL` | scan trigger | No auto-scan; degrade to a logged warning (track still lands on disk). |
| `JELLYFIN_API_KEY` | scan trigger | Same as above. |

### Persistence (SQLite)

- `jobs(id, url, status, created_at)`
- `reviews(id, job_id, staging_path, query, candidate_ids_json, rec, status)` — store MusicBrainz
  candidate **IDs**, not the rich candidate objects; re-match on resume.

## 7. Acceptance checklist (R1 is "done" when…)

- [ ] Pasting **one** YouTube song URL and clicking Go streams live per-stage progress
      (download → transcode → identify) over **SSE**, with no polling.
- [ ] A song whose AcoustID fingerprint is **dominant** auto-tags and lands with **zero clicks**.
- [ ] A song whose fingerprint is **weak/ambiguous** appears in the **review queue** with candidate
      matches; picking one lands it, rejecting discards it.
- [ ] The landed file is **MP3 320 CBR** at
      `C:\Users\aj_am\Music\CleanMuzik\<Artist>\…` with **embedded cover art, genre** (when the
      Last.fm key is set), **year, and embedded lyrics**, plus correct title/artist/album tags.
- [ ] The track appears in **Jellyfin within seconds** of landing via the app-triggered scan — no
      manual scan.
- [ ] Re-pasting the **same** URL is caught as a **duplicate** (no silent second copy); an ambiguous
      duplicate routes to the review queue, where **keep existing** discards the download,
      **replace** lands the upgrade and then removes the old file, and **keep both** lands it
      alongside under the owner's suffix. Nothing is deleted without a click (ADR-009 addendum).
- [ ] A forced failure in any stage surfaces a **per-track error naming the stage** and cleans up
      the staging file.
- [ ] Restarting the backend **preserves parked reviews** (SQLite); they can still be resolved.
- [ ] A **playlist URL is rejected** (422), not silently expanded.
- [ ] Everything runs at **`localhost`** on the laptop; nothing is exposed to the network.

---

*Verification (per Definition of Done): each checklist item is proven by `/verify` driving the
real flow and observing the side effect — a correctly-tagged MP3 320 in the Jellyfin folder,
visible in Jellyfin — not by "the code looks right." Transcribe any correction to
`docs/learnings.md`.*
