# R1 Architectural Decision Records — CleanMuzik

Binding decisions. Short bullets, not a formal ledger. The reviewer checks new code against
these; anything that violates one gets sent back. They exist to stop a later session (a future
agent, or the owner himself) from silently undoing a decision and reintroducing the problem it
prevented.

Format: `ADR-NNN — decision. Rationale. [date]`

> ADR-001–005 mirror the PRD's hard constraints — they exist as a reviewer checklist. From
> **ADR-006 onward**, this file records decisions *born in the build* that the PRD doesn't
> already contain (e.g. the beets `choose_match` seam, the numeric `strong_rec_thresh` value,
> native-vs-Docker Jellyfin, the watched-folder path). Those are the ones that actually earn
> their keep — a future agent could otherwise silently reverse them.

---

- **ADR-001 — Processing is sequential, one track at a time, with a delay between requests.
  Do not parallelize the pipeline.** Rationale: avoids rate limits on identification/download.
  (from PRD hard constraints) [2026-07-11]

- **ADR-002 — Output is MP3 320, and only MP3 320.** Rationale: YouTube source is ~128–160 kbps;
  MP3 320 preserves it transparently. No other output formats without a stated reason.
  (from PRD) [2026-07-11]

- **ADR-003 — One track failing must not stop the batch.** Rationale: surface a per-track error
  event and continue. (from PRD) [2026-07-11]

- **ADR-004 — Single-user, no in-app auth.** Rationale: security is handled at the network layer
  (Tailscale), not in the app. (from PRD) [2026-07-11]

- **ADR-005 — beets is the tagging engine; never reintroduce a bespoke ShazamIO/Mutagen tagger.**
  Rationale: plugins (chroma, lastgenre, fetchart, embedart) are more capable and maintained.
  (from PRD) [2026-07-11]

- **ADR-006 — A bare YouTube singleton cannot reach beets' `strong` recommendation on tag
  matching alone; auto-accept must be driven by acoustic-fingerprint identity in `choose_match`,
  not by relaxing distance thresholds.** Rationale: the spike (see
  `spike-beets-review-queue.md`) measured **0/3 auto-accept** on three well-known, AcoustID-covered
  tracks imported as singletons — even after cleaning the titles, all three plateaued at `rec =
  medium` (distance ~0.11), never `strong` (needs distance ≤ 0.04). The ~0.11 is a **structural
  floor**: a singleton has no album/track-number/year to corroborate, so tag distance can't fall
  far enough. The identity, however, *is* known — AcoustID returns the correct recording MBID with
  a high fingerprint score. So the seam's `choose_match`/`choose_item` override should **auto-accept
  when the top AcoustID match is dominant (high score, clear gap to runner-up)**, treating a strong
  fingerprint as ground truth, and route everything else to the review queue. Do **not** achieve
  auto-accept by lowering `strong_rec_thresh` globally — that would also green-light bad tag
  matches. Corollary: the PRD's "~80% auto-accept" figure does **not** hold for default-config
  singleton imports (measured 0%); the review queue is the *primary* path, not the exception. The
  real auto-accept rate must be re-measured on a larger sample once the fingerprint-trust rule
  exists. [2026-07-11]

- **ADR-007 — In beets 2.12+, MusicBrainz is a plugin that must be explicitly enabled, and the
  library API does not auto-load plugins.** Rationale: chroma resolves fingerprint MBIDs into
  candidates via the `musicbrainz` plugin (`self.mb`); with it disabled, chroma silently returns
  zero candidates. And only the CLI auto-loads plugins — a programmatic backend must call
  `beets.plugins.load_plugins()` at startup. The FastAPI service config must therefore enable
  `plugins: musicbrainz chroma …` and load plugins on boot, or matching silently degrades to
  tag-only. (born in the spike) [2026-07-11]

- **ADR-008 — Jellyfin runs native on Windows (not Docker) for Phase 0, and its Music library
  watches `C:\Users\aj_am\Music\CleanMuzik` (WSL: `/mnt/c/Users/aj_am/Music/CleanMuzik`) — which
  IS beets' output directory.** Rationale: Phase 0 is a single laptop, where Docker's portability
  buys nothing and adds a moving part; native is the lighter call. The watched folder is the
  contract between beets (writer) and Jellyfin (reader) — beets organizes into it, and the app
  triggers a Jellyfin scan after each landing so the track appears within seconds. Jellyfin's
  "auto-refresh metadata from internet" is set to **Never** so it never overwrites beets' tags
  (beets is the sole tagger, ADR-005). Revisit the native-vs-Docker call at Phase 1 (dedicated
  always-on box), not before. [2026-07-12]
