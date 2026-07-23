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
- **Unscoped ideas** — broader directions not yet worked into tickets:

- Playlist support (batch of tracks from one URL)
- **Migrate + clean the existing library (R2 — the PRD's second job).** Re-tag and reorganize the
  owner's scattered phone/computer downloads with the same beets engine. Includes a full-library
  **deduplication sweep**: `beet duplicates` finds copies, and the `chroma` plugin (AcoustID
  fingerprinting) catches the *same song even when filenames and tags differ* across a phone rip
  and a computer rip — because it matches on how the audio sounds, not what the file is named.
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
