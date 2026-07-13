# Backlog — unscoped ideas

Parking lot for ideas that aren't in a release yet. Nothing here is committed. When an idea
graduates, it gets scoped into a release spec and leaves this folder.

- Playlist support (batch of tracks from one URL)
- **Migrate + clean the existing library (R2 — the PRD's second job).** Re-tag and reorganize the
  owner's scattered phone/computer downloads with the same beets engine. Includes a full-library
  **deduplication sweep**: `beet duplicates` finds copies, and the `chroma` plugin (AcoustID
  fingerprinting) catches the *same song even when filenames and tags differ* across a phone rip
  and a computer rip — because it matches on how the audio sounds, not what the file is named.
  Keep-which decisions that aren't clear-cut route to the **review queue** (same policy as the R1
  acquire-time check: auto-keep the better copy, send ambiguous ones to review). Heavier and
  slower than acquire-time dedup — gets its own review flow when R2 is specced.
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
