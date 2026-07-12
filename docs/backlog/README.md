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
