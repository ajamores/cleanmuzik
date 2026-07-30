# Thin surfaces — ffmpeg · Jellyfin API · Last.fm · Cover Art Archive + iTunes

Four external dependencies that **do not warrant a page each** — one is a single fixed command, one
is already covered at length in `spec.md`, one is not in service, and one is a small fallback
fetcher. Each gets the same four questions in a few lines rather than padded to look substantial.

**Promote any of these to its own page the moment it earns one** — a measured cost model, a real
rate limit, or a gotcha that costs a session. Tag convention in [`README.md`](README.md).

---

## ffmpeg — the MP3 320 transcode (`app/transcode.py`, T-005)

**Capability:** decode anything yt-dlp lands (`.webm`/`.m4a`) → MP3 320 CBR, tags carried across.

**The command is the contract** `[source]` `app/transcode.py:76-87`:

```
-y  -i <src>  -map_metadata 0  -vn  -c:a libmp3lame  -b:a 320k  -id3v2_version 3  <dest>
```

Each flag is load-bearing: `-map_metadata 0` carries yt-dlp's embedded tags (without them beets runs
an empty query → HTTP 400); `-vn` drops the thumbnail stream; `-b:a` with **no `-q:a`** is CBR per
**ADR-002**; `-id3v2_version 3` is the widely-read tag version.

**Hard limits:** none that bite. A single-song transcode is seconds; anything past
`TRANSCODE_TIMEOUT_S` means ffmpeg has hung, and the timeout raises `TranscodeError`.

**Cost model:** local CPU, seconds, **blocking** — never on the asyncio event loop (ADR-001).

**Gotchas:**
- **`ffmpeg` is a system binary**, resolved via `shutil.which`; not a pip dependency.
- **`-y` overwrites.** `dest` must not resolve to the input file — guarded explicitly, because with
  `-y` ffmpeg would happily truncate its own source.
- **A zero exit code is not proof.** The module re-checks `dest.is_file()` afterwards.
- ffmpeg's diagnosis lives on the **last few stderr lines**; surface those, not the whole log.

---

## Jellyfin API — the post-land scan trigger (`app/jellyfin.py`, T-010)

**Capability:** one call, `POST {JELLYFIN_URL}/Library/Refresh` with an API key, so a landed track
appears without the owner clicking anything. Jellyfin is otherwise **not** an integration — it reads
the library off local disk, which is why hosting is home-not-VPS.

Depth lives in `spec.md` (17 mentions) and ADR-008. Only the engine-level facts here.

**The gotcha that cost the most: `localhost` from WSL2 does not reach a Windows-hosted service.**
Jellyfin runs native on Windows at `localhost:8096`; WSL2 has its own network namespace, so from WSL
that is connection-refused `[measured]` 2026-07-14.

- Reach the Windows host at the **WSL2 gateway IP** — `ip route show default | awk '{print $3}'`.
  **It is not stable across reboots; derive it, never hardcode.** (`172.20.0.1` on one session.)
- The durable answer is mirrored networking (`.wslconfig` → `networkingMode=mirrored`).
- **This is a verification-environment quirk only.** On the Phase-0 laptop the app runs on Windows
  where the configured `localhost` is correct, so `.env` keeps `http://localhost:8096`; only in-WSL
  `/verify` probes need the gateway override.

**Why it stayed invisible:** the scan is the **one step that crosses a host boundary** — the library
path doesn't, because beets writes `/mnt/c/...` directly. So `JELLYFIN_URL` was structurally
unreachable from T-001 onward with nothing to reveal it. → the lesson: `learnings.md` 2026-07-14 and
the T-019 entry.

**Other gotchas:**
- **A scan failure must not lose the landing.** A post-landing scan failure once ended the job
  `error` with no `path`/`tags` — the file *had* landed. Both now travel on the error branch.
- **Lyrics need a second scan** (backlog **T-023**/**T-030**, duplicates — reconcile before
  building). Same `/Library/Refresh` the app already fires; the app's scan appears to run **before
  Jellyfin indexes the just-written `.lrc`**. Confirmed on Jellyfin **10.11.11** `[measured]`
  2026-07-19. Not a tagging gap — the `.lrc` sidecar and the embedded tag are both present at land
  time.
- **Don't redesign error reporting while the service is down.** A proposal to change scan-failure
  reporting evaporated the moment Jellyfin came back — it was a preference, not a fix.

**Cost model:** one HTTP request, short timeout, fire-and-forget. No rate limit in play.

---

## Last.fm via `lastgenre` — genre tags

**Status: not in service.** `LASTFM_APIKEY` is unset, so **tracks land without genre today**, which
is a documented non-failure. This is the other half of backlog **T-037** (no genre tag written).

**Capability:** `lastgenre` fetches genre tags from Last.fm and writes them during import.

**The one real gotcha, and it is not obvious** `[source]` `app/beets_engine.py:114-119`:

> **`lastgenre` binds its Last.fm key from the module global `beets.plugins.LASTFM_KEY` at import
> time — NOT from user config.** Setting it the way every other plugin key is set does nothing. The
> engine assigns `plugins.LASTFM_KEY` directly for exactly this reason.

**Hard limits / cost model:** **unknown, and honestly so.** Last.fm publishes rate limits for its
API; none have been measured here because the plugin has never run with a key. Establish before
relying on genre — one request per import is the `[assumed]` shape, unverified.

---

## Cover Art Archive + iTunes — the art fallback (`app/artwork.py`, T-007 Door B)

**Capability:** fetch cover art when beets' `fetchart` hasn't. Two sources, tried in order
`[source]` `app/artwork.py:33-34`:

1. **Cover Art Archive** — `https://coverartarchive.org/release/{mbid}/front`. Needs a **release**
   MBID, which is exactly what a recording-based candidate does **not** carry (see
   [`musicbrainz.md`](musicbrainz.md) §4).
2. **iTunes Search** — `https://itunes.apple.com/search`, by artist + title, **with the hit's artist
   verified** before the image is accepted.

**Gotchas:**
- **A custom User-Agent is sent** (`CleanMuzik/0.1 …`) — Cover Art Archive rejects generic ones.
- **iTunes returns a 100px URL**; `_itunes_url_candidates` derives larger variants from it rather
  than accepting the thumbnail.
- **Artist verification is not optional** — an iTunes title search alone happily returns a different
  artist's release.
- `requests` is pinned as a **direct** dependency for this module, even though `fetchart`/`lyrics`
  pull it transitively.

**Hard limits / cost model:** **unmeasured.** Neither service's rate limit has been hit or
investigated; at one song per run under ADR-001 it is unlikely to matter. `[assumed]` — 1–2 requests
per landing, worst case a handful for the iTunes size variants.

---

## What would promote one of these

- **ffmpeg** — a format the pipeline can't decode, or a real transcode-quality decision beyond
  ADR-002.
- **Jellyfin** — resolving T-023/T-030 properly, or anything beyond the single refresh call.
- **Last.fm** — the moment a key is set and genre actually lands. **This is the likeliest next
  promotion**, and it arrives with T-037.
- **Cover Art Archive / iTunes** — a measured rate limit, or art selection becoming a real decision
  rather than a fallback.
