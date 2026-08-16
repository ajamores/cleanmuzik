# Backlog — post-R1 parking lot

Everything here is real but **not in a release yet**. Nothing is committed to a release by sitting
here. An item graduates only when a release moves to `specing` (see `docs/roadmap.md`): it gets
pulled up into that release's spec/tickets and leaves this folder. This is the one gate that keeps
"we found something real" (always capture) separate from "this release now includes it" (a decision
against exit criteria) — see the scope-triage rules at the top of `docs/r1/tickets.md`.

Two tiers live here:

- **Filed tickets** — findings that earned a ticket number, one file each. Triaging one into a
  release is a clean `git mv` into that release's `tickets.md`.
  - [`T-023.md`](T-023.md) — Jellyfin needs a second scan before sidecar lyrics appear *(duplicate of T-030)*
  - [`T-030.md`](T-030.md) — landed lyrics don't surface in Jellyfin until a second scan *(reconcile with T-023 first)*
  - [`T-031.md`](T-031.md) — recover the album when it's real (Topic-channel rips, same-album clusters)
  - [`T-032.md`](T-032.md) — browser reload loses all job cards (no restore-on-load)
  - [`T-033.md`](T-033.md) — boot reconciliation strands a review whose resolve was in flight at restart *(pre-existing bug, HIGH)*
  - [`T-034.md`](T-034.md) — query normalization before the text-search fallback (reversed `Title - Artist`, `ft.`/mixtape cruft) *(likely superseded by T-035)*
  - [`T-035.md`](T-035.md) — Shazam as a backup fingerprint tier when AcoustID misses *(measured 4/5; **GO — ratified as ADR-019**; build ticket still to write)*
  - ~~`T-036.md`~~ — parked audio lives in `/tmp` and gets reaped *(BUG, HIGH — **graduated same day into R1.1 as T-106**; it breaks §8 item 1, which promises a review survives a restart. File removed on filing; the evidence lives in `docs/r1.1/tickets.md`.)*
  - [`T-037.md`](T-037.md) — two tag-quality defects on a real landing: the same artist split across `JAŸ‐Z/` and `Jay-Z/` folders, and no genre tag written *(observed 2026-07-28, **untriaged**; defect 1 needs an ADR since it binds every path the app writes)*
  - [`T-039.md`](T-039.md) — inbox shows "Nothing waiting" during cold-load hydration instead of a loading state *(UX gap, untriaged)*
  - ~~[`T-040.md`](T-040.md)~~ — keep_untagged resolve fails and re-parks *(**RESOLVED 2026-08-05** — same bug as the `8ba2c2f` dup-stage defusal, fixed the day after filing and never re-tested; re-verified end-to-end that keep-untagged now lands with a blank-MBID item already in the library)*
  - [`T-041.md`](T-041.md) — signal-glow `pointermove` calls `getBoundingClientRect()` every move, forcing sync reflow — cursor jank on low-end machines *(micro-perf, untriaged; from T-105 review)*
  - [`T-042.md`](T-042.md) — loudness normalization: write portable ReplayGain tags at import *(untriaged; the pipeline does no leveling by design — currently delegated to Jellyfin's LUFS scan; needs an ADR for target level + track/album default)* — the **`replaygain`** plugin is the built-in mechanism (confirmed, 2026-08-10 beets audit)
  - [`T-043.md`](T-043.md) — `scrub` plugin: strip surviving YouTube junk ID3 frames on write *(untriaged; `from_scratch` clears the beets model, not arbitrary frames — from the 2026-08-10 beets audit)*
  - [`T-044.md`](T-044.md) — near-duplicate artist-folder tripwire: alarm on the *next* mojibake class ADR-028's surgical map doesn't yet know *(untriaged; the recorded follow-on to ADR-028 / T-301, **not** binding on T-308)*
  - [`T-045.md`](T-045.md) — theme switcher + colorway registry: pick Dark / Light / System (default Dark), persisted *(untriaged; **build after R2**; owner endorsed the ADR-018 dark skin, wants a switch + more colorways later — likely an ADR-018 amendment)*
  - [`T-046.md`](T-046.md) — Multi mode: hand-assemble a set of songs into one batch (the acquire dial's third stop, built) *(untriaged; deferred half of **ADR-029**; R2 ships Multi present-but-inert, this builds it — mostly input-UI, data model already supports it)*
  - [`T-210.md`](T-210.md) — share one MusicBrainz rate limiter across beets + the ISRC lookup (`app/isrc.py`'s gate is independent of beets', so back-to-back calls can breach MB's 1/sec) *(untriaged; from the 2026-08-10 T-203 review — low real risk per the 26-track spike, watched at T-209)*
  - [`T-208.md`](T-208.md) — collapse the MB candidate **fan-out** (5 independent `track_for_id` hydrations behind the 1/sec limit; the `mb_search.py` finding-#4 fix, applied to acquire) *(the ~4–5s lever; **engine change → deferred + conditional**, clears its own §7 gate; from T-209 + the 2026-08-13 speed council)*
  - [`T-214.md`](T-214.md) — narrate the 16–19s "Identifying" freeze as four moving sub-steps *(safe, non-engine, **perceived** speed — the biggest felt win; buildable anytime)*
  - [`T-215.md`](T-215.md) — hoist Shazam to run *during* the beets candidate lookup *(safe, non-engine, ~2s + moves the ≤8s hang tail off the critical path; rides the `shazam_fn` seam; buildable anytime)*
- **Unscoped ideas** — broader directions not yet worked into tickets:

- Playlist support (batch of tracks from one URL)
- **Migrate + clean the existing library (R2 — the PRD's second job).** Re-tag and reorganize the
  owner's scattered phone/computer downloads with the same beets engine. Includes a full-library
  **deduplication sweep**: `beet duplicates` finds copies, and the `chroma` plugin (AcoustID
  fingerprinting) catches the *same song even when filenames and tags differ* across a phone rip
  and a computer rip — because it matches on how the audio sounds, not what the file is named.
  **(2026-08-10 beets audit — use the built-in migrate plugins, don't hand-roll):** `mbsync`
  re-fetches updated MusicBrainz metadata for any item carrying an `mb_trackid` (every
  CleanMuzik-landed track has one) — the "re-tag from MB later" engine; `fromfilename` gives beets a
  usable artist/title query on legacy files whose tags are junk but filenames are clean. Scope these
  three (`duplicates` + `mbsync` + `fromfilename`) into the R2.5 migrate spec when it's written.
  Keep-which decisions route to the **review queue**, matching R1's acquire-time policy — which
  **ADR-009 settled as non-destructive: never auto-delete.** (An earlier draft here said "auto-keep
  the better copy, send ambiguous ones to review" — *withdrawn*; beets deletes the old file before
  it copies the new one, so a failed copy loses both.) R2 may revisit auto-replace only via
  copy-first/delete-after, plus the tag-richness tie-break R1 deferred. Heavier and slower than
  acquire-time dedup — gets its own review flow when R2 is specced.
  **Sizing (measured 2026-07-12):** 3.2 GB — 855 MP3 + 37 `.webm` + broken-download debris
  (`.part`/`.ytdl`/`.mhtml`) across 15 month-batch folders under `C:\Users\aj_am\Documents\`.
  Overlapping copies also live on the owner's **phone** (a dedup input, not a separate source).
  Destination after extraction: `C:\Users\aj_am\Music` — out of OneDrive, to stop cloud sync.
- Acoustic metadata tier — BPM / key / energy via Essentia
- Always-on host + Tailscale reachability (PRD §9 phase 1)
- **HTTP QUERY method (RFC 10008) — noted, not adopting.** A 2026 method: a read that carries a
  big structured filter in the *body* while staying safe/idempotent/cacheable. Came up as a possible
  verb for a "smart-playlist query" endpoint. **Decision: don't build it.** Two reasons — (1) smart
  playlists are already **Jellyfin's** job, powered by the rich tags CleanMuzik writes (R1 unlocks
  genre/artist/decade filtering + Instant Mix; the acoustic tier above adds "by feel" later), so
  CleanMuzik owns no query endpoint to put it on; (2) even if it did, QUERY's only wins over `POST`
  are proxy-caching and semantic honesty, both worthless on a single-user `localhost`/Tailscale
  tool with no cache or CDN in front — and ecosystem support is thin (Proposed Standard, no FastAPI
  first-class support). Revisit *only* if CleanMuzik ever became multi-user/CDN-fronted, which the
  plan rules out. If a library-query endpoint is ever wanted anyway, use `POST`.
