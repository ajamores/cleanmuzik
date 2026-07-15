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

  - **ADR-006 addendum — thresholds tuned + auto-accept re-measured (T-008).** Re-measured on
    **25 real songs**: 15 from the owner's existing library (deliberately including tag-less,
    bare-title files — the worst case) and 10 fresh YouTube rips from a deliberately international
    playlist (Brazilian, Latin, Amapiano, French/UK/US R&B). Result: **22 correct auto-accepts,
    0 wrong, 3 genuine no-matches** (all parked correctly). Every correct match scored
    **0.955–0.995**; every no-match scored **0.0** — a clean, wide split with no ambiguous middle.
    **Tuned thresholds (now the code defaults in `import_seam.py`): `SCORE_MIN = 0.90` (held from
    the original guess — it sits comfortably in the no-man's-land), `GAP_MIN = 0.0` (gap check
    retained as an injectable knob but OFF by default).** The gap finding is load-bearing: a
    gap-to-runner-up requirement **never once helped** across all 25 songs — a high runner-up was
    in *every* case the SAME recording listed twice in AcoustID (a re-release/duplicate
    submission), never a different rival song, because two genuinely different recordings do not
    both fingerprint-match one audio at ≥ 0.9. So any gap floor only false-parked matches we were
    certain of (canonical case: Kanye "Through The Wire" — score 0.987, runner-up 0.977, the same
    song twice). The `_matching_candidate` identity check (auto-accept only a beets candidate whose
    recording MBID *is* the fingerprint winner) remains the real safety backstop; the gap was
    always the weakest of the three checks. **Re-measured auto-accept rate ≈ 88% (22/25)** — this
    finally vindicates the PRD's "~80%" intuition, but via *fingerprint identity*, not tag distance
    (the spike's 0% still stands for default-config tag matching). **Operational note → T-011:**
    the seam's own lookup currently runs on pyacoustid's *shared built-in* application key
    (`1vOwZtEn`, 8 chars) and throttles hard under batch load (5 of 30 sample lookups failed on
    rate-limit, all recovered on retry). The fix is already in hand: the owner's `ACOUSTID_APIKEY`
    is a working **application / lookup** key (verified 2026-07-14 — `acoustid.lookup` returns
    `status=ok`), so wiring it into `fingerprint_dominance`'s `acoustid.lookup` moves the
    score-critical lookup onto a private quota. (beets' *internal* chroma lookup during candidate
    generation still uses beets' own built-in key — a separate change.) Combine with
    retry/backoff. [2026-07-14]

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

- **ADR-009 — Acquire-time duplicate handling is non-destructive in R1: never auto-delete the
  owner's existing library file.** This deviates, deliberately, from spec §5's "auto-keep the
  better copy and drop the other." Rationale: beets 2.12's `DuplicateAction.REMOVE` deletes the old
  file (`item.remove()` + `util.remove()`) in `manipulate_files` *before* it copies the new one, with
  no rollback — a copy failure after the delete loses **both** copies. For a music library that
  data-loss window is unacceptable. Instead, the import seam keeps the existing copy (`SKIP`) whenever
  an existing copy is at **>= bitrate**, and otherwise **parks the strictly-higher-bitrate incoming
  copy to the review queue** for the owner to choose ("you already have this — keep which?"). No file
  is ever deleted automatically. The comparison is **bitrate-only** at acquire time: it's the one axis
  that's honest before beets applies tags, and for the same recording both copies get identical tags
  anyway, so tag richness can't legitimately differentiate an acquire-time duplicate — the
  tag-richness / acoustic-fingerprint tie-break belongs to **R2 migrate**, where two already-tagged
  files are genuinely compared. Consequence worth noting: the upgrade is a human-confirmed action in
  R1, not automatic, and in practice it almost never fires (the library is all MP3 320). True
  auto-replace — copy-first then delete-after — is deferred to R2. **Detection is by MusicBrainz
  recording id via a direct library query in `choose_item`, NOT beets' import duplicate stage:** that
  stage's probe is built from the match's `TrackInfo` (recording id under `track_id`) *before* the
  `track_id`→`mb_trackid` mapping, so a `duplicate_keys` query on `mb_trackid` always finds nothing
  (verified). `duplicate_keys.item = mb_trackid` is set only to make beets' stage an inert no-op so it
  can't act on a false artist+title match behind our back; the real detection is our own
  `MatchQuery("mb_trackid", …)` at accept time. Complete for R1 by construction (every landed copy
  carries an MBID); untagged legacy files are R2 migrate input. Owner signed off the non-destructive
  call. (born in the build, T-009; two owner reviews found the REMOVE data-loss window and then the
  silently-dead import-stage detection) [2026-07-15]
