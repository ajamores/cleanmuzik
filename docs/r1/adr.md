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

  **Addendum — "never auto-delete" bounds the APP, not the owner (T-014 resolve).** The rule above
  was written against the *acquire* path, where the app would be deleting a file on its own initiative
  with no one watching. It does not speak to the *resolve* path, where the owner is looking at both
  copies and picks. An explicit owner click is the consent the rule was protecting; requiring the
  library to accumulate a file the owner has just said they don't want would be the rule outliving its
  reason. So `POST /api/reviews/{id}/resolve` on a `rec="duplicate"` review offers three choices, and
  the destructive one is reachable **only** by an owner click, never by a threshold or a heuristic:
  - `keep_existing` — discard the download. (Non-destructive; the same outcome the acquire path already
    auto-takes at >= bitrate.)
  - `replace` — delete the existing library file, land the incoming upgrade. **The one deletion R1
    performs.** The ADR's data-loss window still applies and is why this is NOT beets'
    `DuplicateAction.REMOVE`: land the new copy **first**, verify it, and only then remove the old one.
    Copy-first/delete-after was deferred to R2 as an *automatic* path; under an owner click, on one
    named file, it is in R1's reach.
  - `keep_both` — land the incoming copy alongside the existing one, distinguished by an
    **owner-supplied suffix appended to the title tag** (not the filename — see spec §5). Exists because
    detection is by MusicBrainz recording id, which is not infallible: a remaster or re-release commonly
    shares a recording id with the original, and AcoustID maps near-identical audio onto the same
    recording. When the app's "same recording" call is wrong, the owner is the only one who can see it,
    and this is the escape hatch. Non-destructive.

  What does NOT change: nothing is deleted without a click, the acquire-time comparison stays
  bitrate-only, and full cross-library acoustic dedup remains R2. (Owner decision, T-014 briefing —
  the spec defined `choice` as `candidate_id|reject`, which could not express any of the above.)
  [2026-07-16]

  **Amendment — always park, never silently skip; defuse beets' own duplicate stage (2026-08-04).**
  Two stacked bugs lost a song (`FwKp-HkKUMA`, 2026-08-03) with no trace.

  *Bug 1 — silent skip on equal bitrate.* The original text distinguished two duplicate outcomes by
  bitrate: equal-or-lower skipped silently, strictly-higher parked. Since ADR-002 mandates MP3 320
  for all output, every library copy is already 320 — the park path was structurally unreachable
  and the skip path fired on *every* duplicate. Fix: `_resolve_duplicate` now **always parks**,
  regardless of bitrate. The "all-skipped" defensive path in `jobs.py` now reports `STATUS_ERROR`
  instead of a false `STATUS_DONE`.

  *Bug 2 — beets' duplicate stage was never truly neutralized.* Setting `duplicate_keys.item =
  mb_trackid` was supposed to make beets' own import duplicate stage a no-op. It wasn't:
  `TrackInfo.copy()` maps the recording ID to `track_id`, NOT `mb_trackid`, so the temp item beets
  builds for the dup query has `mb_trackid = ""`. Any library item with an empty `mb_trackid` — i.e.
  every keep-untagged landing — matches. Beets then sets `task.duplicate_action = SKIP`, which makes
  `task.skip` return `True`, and `finalize_outcomes` records "skipped" instead of "landed" — even
  when `choose_item` accepted the match and found no actual duplicate. A single keep-untagged item
  in the library silently blocked *every* subsequent import. Fix: override `get_duplicate_action` on
  the session to return `DuplicateAction.KEEP`, fully defusing beets' stage. We detect and resolve
  duplicates ourselves in `choose_item` by recording ID — beets' stage is redundant and, as shown,
  actively harmful.

  **`replace` refuses when >1 library file shares the recording id — this is the intended R1
  semantics, not a stopgap. Do not "improve" it into an auto-pick.** `keep_both` can leave two
  files of one recording id in the library on purpose (an original + a deliberately-kept alternate).
  A later `replace` on a third download then can't tell which of the two "the existing file"
  (spec §6, singular) means. T-014 refuses **before anything lands** — names the paths, and points
  the owner at `keep_both` / `keep_existing` / remove-one-yourself. The owner ruled this correct:
  the two-copy case is rare (needs a prior `keep_both` *and* a later re-download), it sits on the
  one path in R1 that deletes with no undo, and "when unsure, don't guess — ask" is the rule the
  whole feature rests on. The only non-refusing alternative (auto-delete the lowest-bitrate copy) is
  more logic on the deletion path and can still delete the copy the owner meant to keep — rejected.
  **Condition attached:** the owner accepts hitting this wall *provided the review UI (T-017) lets
  them look over parked items and decide fast* — see T-017 / spec §5. (Owner decision; the bug that
  forced it — `_replace_existing` deleting *both* copies — was caught by T-014's own `/verify`.)
  [2026-07-17]

- **ADR-010 — A weak-match review candidate is `title + artist + score`. No album, no year, no
  cover art. Don't "fix" the nulls.** The spec promised five fields per candidate from day one
  (`4a2f60f`); **three of them were never reachable** and every path silently rendered them null.
  Rationale — the data genuinely isn't there: beets builds a singleton candidate via
  `item_candidates` → `tracks_for_ids` → `track_for_id` → `track_info(recording)`, which translates
  a MusicBrainz **recording** payload (title, artist, track_id, length, ISRC). Album, year and cover
  art are properties of a **release**, and one recording appears on many — so nothing in the
  candidate carries them, and no column can store what was never fetched. Reaching them means an
  extra MusicBrainz browse-releases call **per candidate**, plus a heuristic to pick *which* release.
  That was rejected as disproportionate: T-008 measured **88% auto-accept (22/25, 0 wrong)**, and the
  ~12% that park are overwhelmingly *no-match* songs whose candidates come from a title text search
  and are plainly different songs — title + artist separates them. The case art would serve (two
  candidates identical but for their release) is rare, and art wouldn't reliably settle it anyway: a
  compilation cover for the right recording looks wrong, an album cover for the wrong recording looks
  right. **`score` (= 1 − beets' tag distance) is the discriminator** and costs nothing — it is
  already populated at park time. Consequences: `candidate_row()` carries only the fields it can
  fill (a contract key that is structurally always null is a lie, not a placeholder); T-017's picker
  is title/artist/score against the normalized query; **the duplicate panel is NOT narrowed** — its
  "you already have this" side reads an existing *library item*, a tagged file on disk that has
  album, year and embedded art for free, no lookup involved. Cover art still lands **on the file**
  via `fetchart`/`embedart` and is visible in Jellyfin, which is where music is actually looked at;
  it is absent only from the picker. Accepted cost: two identical-reading candidates must be chosen
  between on `score` alone. Revisit only if the queue's real traffic turns out to be
  same-song-different-release (it isn't today). Supersedes `_candidate_rows`' original note that
  "T-014/T-017 fill it when the owner actually views the queue" — they don't, by decision.
  (Owner decision; found by reading T-016's diff against its ticket text, not by any code review —
  see the Definition of Done's acceptance check in `CLAUDE.md`.) [2026-07-17]

  - **ADR-010 addendum — `score` must be *persisted*, or this decision is unimplementable (T-028).**
    The decision above rests on `score` being the discriminator and "free". It was free at park
    time and thrown away immediately: the DB stored bare MBIDs (`db.py:14`), so `GET /api/reviews`
    re-hydrated from MusicBrainz and returned **`score: null` on every row** (`reviews.py:307` — a
    recording lookup carries no tag distance). The discriminator therefore existed only during the
    live `track.review_required` event, while spec §7 requires *"restart preserves reviews"* — so
    the queue's normal case, worked later, was precisely the case with no discriminator. **This is
    the same failure as ADR-011 and as ADR-010's own origin: a decision whose payload cannot deliver
    it.** It was caught before T-017 built on it, by running the DoD acceptance check on T-017's
    ticket rather than reviewing a diff — which is the third time that check has found what no code
    review could, and the reason it is a separate step. Remedy: persist scores at park time as a
    **MBID → score map** (`candidate_scores_json`), chosen over an id+score array because it cannot
    drift out of order with the id list and a missing key degrades to `None` — the existing
    behaviour — so legacy rows and duplicate parks need no special case. (Owner decision,
    2026-07-19.) [2026-07-19]

- **ADR-011 — REJECTED (same night it was written). `original_date: yes` is NOT the fix for reissue
  years; it is inert on this product's path.** Kept, not deleted, because the reasoning below is
  sound and the *problem* is real — only the remedy was wrong, and the next person to notice a
  wrong year will reach for exactly this option. **Why it does nothing:** beets consults
  `original_date` only in `AlbumInfo.item_data` (`autotag/hooks.py:325`), the album-apply path.
  R1 imports every track as a **singleton** (`import_seam.py:845` → `imp["singletons"].set(True)`),
  which builds a **`TrackInfo`** — a different class (`hooks.py:400`) with no such override and no
  `original_year` field for one to read. Setting the option changes no byte of any file we write.
  **How it got recorded as decided:** it was written up and accepted on argument, then reverted on
  the review pass an hour later. Nothing in the 273-test suite asserts on year, so the suite stayed
  green throughout and supplied no signal. This is ADR-010's failure mode exactly — *a decision
  recorded whose payload cannot deliver it* — committed on the same night ADR-010's lesson was
  being cited, which is the useful part of keeping it: **the acceptance check must be run against
  the code path the product actually takes, not the one the option's documentation describes.**
  The open problem moves to **T-025**, where reaching an original date needs a MusicBrainz release
  lookup per recording — the same cost ADR-010 declined for candidate enrichment, so T-025 must
  price it before building. Superseded-by: **ADR-014** (T-025's actual fix: one release lookup on
  the auto-accept path; the junk-year half is ADR-013's `from_scratch`). [rejected 2026-07-19]

  <details><summary>Original rationale, preserved (the problem statement still holds)</summary>

  beets defaults this off (`config_default.yaml:102`), so the year written
  is whichever *release* MusicBrainz resolved the fingerprint to — a remaster, compilation, or
  anniversary reissue. Observed in the first browser session: a track the owner knew to be much
  older landed stamped **2024**. The recording match was correct — same performance, right audio;
  only the date came from a reissue. Rationale: a personal library is browsed and sorted by era, so
  "when did this song come out" is the question the year field is asked, and a reissue year answers
  a question nobody posed. It is also the failure mode that quietly erodes trust in the whole
  tagging engine — the audio is right, the art is right, and the one visibly wrong field makes the
  rest suspect. Consequences: set in `configure_beets()` alongside `directory`/`paths`/`plugins`, so
  it applies to every import including the migrate flow. **Not retroactive** — tracks landed before
  this need a re-tag pass (the migrate flow, unbuilt). Accepted cost: a genuine remaster or remix
  for which the *later* date is the honest answer will now be stamped with the original's; rare, and
  overridable per track. Revisit if the library turns out to be remaster-heavy (it isn't).
  (Owner decision, prompted by the owner noticing the wrong year on a landed card — not by any
  test or review; nothing in the suite asserts on year.) [2026-07-18]

  </details>

- **ADR-012 — `ftintitle` is a seventh plugin, and the exception to ADR-007's "no more, no less"
  is deliberate.** `PLUGINS` in `beets_engine.py` was fixed at the spec §2 identify/tag/art/lyrics
  set. This adds one outside that set, so it needs a decision on the record rather than a quiet
  edit. **The problem:** `PATHS["singleton"] = "$artist/$title"` names the folder from `item.artist`,
  and MusicBrainz's **recording artist credit phrase** puts the featured artist there — so
  `Nines feat. Tiggs da Author/NIC.mp3` becomes a distinct artist in Jellyfin, and a future Nines
  track never groups with it. Every collaboration spawns another phantom artist, silently and
  cumulatively. This is precisely the library fragmentation the tool exists to prevent, which is why
  a plugin outside the §2 set earns its place. **Not `artist_credit`** — beets defaults it off
  (`config_default.yaml:103`) and we never set it; flipping it is not the fix and was not tried.
  **Configuration:** `auto: yes` (import-stage, no manual command), `drop: no` (the credit is moved,
  never discarded), `format: "(feat. {})"` (parenthesised — reads better in Jellyfin's track list and
  survives being parsed back out), and **`preserve_album_artist: no` set explicitly** — see the
  fragility note below.

  **Verified against the singleton path before acceptance, per ADR-011's lesson.** Three checks, run
  on the real values from the real landed file, not inferred from the plugin's docs:
  1. **The stage fires on singletons.** `session.py:237` appends every `plugins.import_stages()`
     unconditionally and `plugin_stage` (`stages.py:245`) has no singleton branch;
     `SingletonImportTask.imported_items()` (`tasks.py:699`) returns `[self.item]` outright, unlike
     the base class which returns `[]` for a `TrackMatch`. This is the structural difference from
     `original_date`, which was inert because it lived on a class this path never builds.
  2. **It runs before `manipulate_files`** (`session.py:240`), so the artist is corrected *before*
     the path template computes — the folder is written as `Nines/`, not renamed afterwards.
  3. **Observed output**, driving the plugin with the file's actual tags:
     `artist='Nines feat. Tiggs da Author' title='NIC'` → `artist='Nines' title='NIC (feat. Tiggs da Author)'`.

  **Why `preserve_album_artist: no` is explicit and not left at its default.** `ft_in_title()` opens
  with `if self.preserve_album_artist and albumartist and artist == albumartist: return False`, and
  the option defaults **True**. On our path it currently doesn't trip — but only because
  `TrackInfo.item_data` carries **no `albumartist`** (`hooks.py:400`), so `TPE2` is whatever
  yt-dlp's `--embed-metadata` left, and on the observed file it is **absent**; empty is falsy, so the
  guard short-circuits before it ever compares. That is a load-bearing accident: if a future yt-dlp
  writes `TPE2` with the full "feat." string, the plugin silently becomes a no-op with a green suite
  and no signal — ADR-011's failure mode wearing a different hat. Setting the option off removes the
  dependency on an absent tag. (Same leftover-tag mechanism as T-021's junk `TCON`; the same dump
  that confirmed `TPE2` absent also showed `TCON = 'Entertainment'`.)

  Consequences: **not retroactive** — `Nines feat. Tiggs da Author/` stays on disk until a re-tag
  pass (the migrate flow, unbuilt); the owner accepted this explicitly rather than scoping a
  backfill here. Accepted cost: a track whose *real* title contains a featured credit is left alone
  (`contains_feat` guards against doubling), and an artist genuinely named with a "feat."-like token
  would be mis-split — neither observed. Revisit if the split ever mangles a real artist name.
  (Owner decision, 2026-07-19, prompted by `Nines feat. Tiggs da Author/NIC.mp3` in the first
  browser session. Supersedes ADR-007's "no more, no less" for this one plugin only — the §2 set
  remains closed otherwise.) [2026-07-19]

- **ADR-013 — `from_scratch: yes` on import: a landed track's tags come only from MusicBrainz
  (plus the tag plugins), never from yt-dlp's embedded metadata.** The download embeds the source's
  metadata via `--embed-metadata` (`download.py:203`) so beets has a non-empty query — but on the
  **singleton** path that junk *survives onto the landed file*. `track_info()` (`musicbrainz.py:459`)
  builds a `TrackInfo` with no genre and no year, `RECORDING_INCLUDES` (`_utils/musicbrainz.py:68`)
  fetches no releases, and `TrackMatch.apply_metadata` (`match.py:253`) does
  `item.update(info.item_data)` where `item_data` **drops None fields** — so any field MusicBrainz
  doesn't supply keeps whatever yt-dlp wrote. Observed: genre = YouTube's **category**
  (`TCON = "Music"` / `"Entertainment"`, T-021) and a wrong **year** (a 1996 track stamped `2026`,
  the current year — T-025; *not* a MusicBrainz reissue date, which is why ADR-011's `original_date`
  was inert). `from_scratch: yes` makes `apply_metadata` call `item.clear()` first, so only
  MusicBrainz-derived fields land. **Safe:** `Item.clear()` iterates `_media_tag_fields` only, which
  by construction **excludes audio properties** (`models.py:717` — "excludes fields that represent
  audio data, such as `bitrate` or `length`"), and it runs at apply time, *before* the
  `lastgenre`/`lyrics`/art plugin stages, so it never wipes a fetched genre, lyric, or cover.
  Interactions checked: `ftintitle` still fires (it reads the applied MB `item.artist`), dedup still
  works (`mb_trackid` is cleared then re-set from the match), and `lastgenre` now fetches fresh
  because the junk `TCON` no longer short-circuits it at `"keep any, no-force"`
  (`lastgenre/__init__.py:462`). Chosen over the narrower `lastgenre force: yes` (which fixes only
  genre) because it is one systemic line that also kills the junk year and immunizes against any
  other stray `--embed-metadata` field. Discharges **T-021** and the junk half of **T-025**.
  Accepted cost: a field yt-dlp got right but MusicBrainz lacks now lands blank — correct for this
  tool, where MusicBrainz is authoritative and YouTube metadata is untrusted. **This includes the
  album family** (`album` / `albumartist` / `tracknumber`), which a singleton MusicBrainz match does
  not supply, so a landed single now carries no album — confirmed on the verify (`Coming of Age`
  landed with a blank album, `track=0/0`). The owner ruled this correct for R1: the library is
  individual tracks organized by `$artist/$title`, album is not load-bearing, and yt-dlp's "album"
  for a YouTube rip is usually the video title or a Topic-channel artifact. **The genuinely-valuable
  case — several tracks from one real album (e.g. a Topic-channel release) should recover and group
  under that album — is a wanted future feature, deferred to T-031, not a reason to keep the junk
  now.** (Owner decision, 2026-07-19; found by tracing T-021's genre and T-025's year to one
  mechanism — the same leftover-`--embed-metadata` tag ADR-012 already noted for `TPE2`; the
  album-family scope was surfaced by a code-review finding and ratified against the verify
  evidence.) [2026-07-19]

- **ADR-014 — Stamp the original-ish release year via one MusicBrainz call on the
  auto-accept/resolve path. The year field is worth the per-item lookup ADR-010 declined for
  candidate enrichment. Supersedes rejected ADR-011.** After ADR-013 clears the junk year,
  MusicBrainz gives a singleton **no** year (a recording lookup fetches no releases), so a landed
  track has a blank year — and year is a first-class Jellyfin browse/sort field. On a landed track
  (both the auto-accept and the owner-resolve paths, via `finalize_outcomes`), look the accepted
  recording up **once** with `inc=releases+release-groups` and read a date from it: the recording's
  own `first_release_date` (MusicBrainz's authoritative "when this recording first came out")
  preferred, else the earliest date across its releases — release-group `first_release_date` before
  per-release `date`, with the most complete date winning a same-year tie. **This is not the cost
  ADR-010 rejected:** that was a browse-releases call *per candidate* on the review path; this is one
  call on the ~88% auto-accept path, for the one field visible on every Jellyfin browse. The stamp
  is a post-run tag write on the landed file (one extra write on top of beets' own; accepted for a
  single-user tool that imports one song at a time), and it rolls its reported value back to blank
  if that write fails, so the `track.done` payload never claims a year the file lacks.
  **Best-effort, and honestly a proxy, not a guarantee:** MusicBrainz models each remaster/reissue
  master as a *separate recording*, so "earliest release of *the matched recording*" is the original
  year only when AcoustID matched the original master (the common case for a rip of the original
  upload); a recording that appears only on later compilations yields a reissue year, and a
  recording with no dated release lands blank. Verified against live MusicBrainz before building — a
  text-searched recording gave 1993 for a 1975 song (the worst case, mitigated on our path because
  the recording MBID comes from the AcoustID fingerprint, not a text search). A lookup failure or
  missing date **never un-lands** the track — it just leaves the year blank, exactly as `_embed_art`
  treats a missing cover. Injectable (`date_fn`) so tests need no network. **Why not
  `original_date: yes`** — see ADR-011: it is read only on `AlbumInfo`, and R1 imports singletons.
  Accepted cost: an occasional reissue year on a recording AcoustID mapped to a reissue master; the
  owner accepted this over a blank year, on the evidence that it is net better than blank-or-junk and
  strictly better than the status quo. (Owner decision, 2026-07-19, after being shown the proxy's
  limits.) [2026-07-19]

- **ADR-015 — The landing detail (where the song went + its tags) is delivered on the terminal SSE
  event, NOT persisted to a durable row. Reverses T-020's spec §6 "durable receipt" amendment.**
  T-020 added two `jobs` columns (`landed_path`, `landed_tags_json`) and surfaced them on the
  `GET /api/jobs/{id}` snapshot, so a card that lost `track.done` could recover *where the song
  went* after a restart. That durable receipt then generated **four consecutive `/code-review`
  rounds of defects** (a landed song shown as `error`; an announce-before-commit window; a receipt
  dropped on a null-path REPLACE; a snapshot gate that hid it; and finally the live vs reconnect
  recovery paths drifting out of sync) — all symptoms of one cause: the path was written to a
  column, threaded through an atomic status-coupled write, re-read on a snapshot, and recovered on
  *two* client paths, when it was **already in hand at the moment of landing**. Decision: put
  `path`/`tags` directly into the terminal event — `track.done` already carried them; `track.error`
  now does too, on a post-landing scan failure — and the client sets them from that one event. The
  durable receipt, its migration, the snapshot block, and the second client recovery path are
  deleted. Rationale — this is a **single-user localhost tool** and the song is **never lost**: on
  any scan failure the file is at its deterministic beets library path (`<Artist>/<Title>.mp3`), and
  a manual re-scan is already a sanctioned recovery (spec §6, T-030). The one thing durability bought
  — recovering the exact path after a *restart between the terminal event and the owner reconnecting*
  — is a rare intersection for a locally-run tool, and even inside it the file is safe at a known
  location. **Accepted cost — the path is best-effort live delivery, not a guarantee.** The card
  shows it whenever the terminal event is delivered live (the common case). Whenever the event is
  *not* delivered live — a stream drop that overlaps completion, or a restart with an empty replay
  buffer — the card settles to a bare status (`done`/`error`) with no path, because the reconnect
  handler (`checkOnce`) settles from the status snapshot and does not wait for the buffered event to
  replay. That is fine and deliberate: the file is at its deterministic library path regardless, a
  re-scan surfaces it in Jellyfin, and the path on the card is a nicety, never the only record of
  where the song went. (An earlier draft of this ADR claimed in-process reconnect was "unaffected /
  lossless" — corrected 2026-07-23: `checkOnce` closing the stream can pre-empt the replay, so the
  honest statement is best-effort. Owner's call: accept the wider gap over adding recovery code —
  simplicity and basic functionality over the path display.) Also collapses T-020's two hand-mirrored
  scan-failure branches into one `_finish_scan_failed` helper (the drift risk `/code-review` round 4 flagged). Supersedes the spec
  §6 snapshot amendment and the `jobs.landed_*` columns. (Owner decision, 2026-07-22, after a
  step-back review of whether T-020 was over-engineered: requirements, footprint, and simpler-design
  agents converged that the round-3/4 machinery exceeded the ticket's reconnect-scoped "Done when".)
  [2026-07-22]

- **ADR-016 — UI tickets pass a design gate before code: owner-reviewed scenario screens.** A ticket
  that introduces or changes a user-visible **flow or state** produces quick, flat HTML screens — one
  per scenario, **including the failure and edge states** — published as an artifact, and the owner
  signs off on the flow *before* component code is written. The gate runs ahead of the Definition of
  Done, not inside it. **Scope:** flow/state changes only, **not** CSS/visual-only tweaks. The screens
  stay flat HTML with **no live state** — the moment they try to *be* the app, the gate costs more than
  it saves. **Does not replace `/verify`:** platform-behaviour bugs a static mockup cannot show
  (EventSource held open by the Vite proxy, native `<input type=url>` rejecting a paste) still need a
  real browser; the gate narrows what's left for the browser, it doesn't remove it. Rationale — R1's
  UI defects clustered in a class **no diff-scoped gate can see**: contradictory or missing states (a
  card reading *"landed"* and *"landing failed"* at once — the 2026-07-23 rail bug; "Unknown title"
  painted over a correct match), and **scope larger than the need**. T-020 is the case: a durable
  landing receipt that ran **four consecutive `/code-review` rounds** and **three step-back agents**,
  resolved not by fixing the code but by *deleting the feature* (ADR-015). Those four rounds were a
  **scoping conversation held in code review instead of in a design** — six flat screens up front
  (running / landed / landed-but-scan-failed / stream-dropped / restart-empty-buffer) would have put
  "the path is a nicety, don't build durable recovery for it" in front of the owner on day one, which
  is exactly where ADR-015 landed four rounds later. Tests assert per-branch logic; `/code-review`
  reads a diff; neither shows the owner the flow. A screen-per-scenario surfaces state contradictions
  and over-scope while they are cheap. (Owner decision, 2026-07-23, out of the R1 front-end
  retrospective. Pairs with the standing `TrackCard` architecture review — the gate catches flow
  errors before build; the architecture review reduces how many corners exist to find.) [2026-07-23]

- **ADR-017 — The review lifecycle lives in a durable, top-level inbox, not inside the ephemeral
  `TrackCard`. Job cards are transient; the review queue is the app's durable surface.** A card shows
  pipeline progress and then gets out of the way; when it parks, it hands off to a top-level
  **Needs-review inbox** backed by `GET /api/reviews` and stops owning the review. Rationale: R1 built
  the review lifecycle *inside* `TrackCard` (T-016/T-020), but the card list is ephemeral React state
  (`App.tsx`) that boots empty, so a parked review was **invisible and unreachable on a fresh load** —
  the durable `GET /api/reviews` (T-014) sat unwired, a no-candidate park rendered a dead-end panel with
  no buttons, and a boot-orphaned review (T-033) had no surface at all. The spec §7 promised parked
  reviews *"can still be resolved"*; the card-owned model didn't deliver it. This **reverses** the
  card-owns-review model: the review's existence is independent of any card's lifetime. Also the direct
  means of paying down the `TrackCard` "one component runs the whole job state machine" debt. Corollary:
  because the inbox reads the queue directly, a review is reachable even when its job's card shows an
  error (which is why the T-033 boot-orphan becomes *reachable* here, though T-104 still fixes the
  underlying state disagreement). (Owner decision, 2026-07-23, R1.1 spec; design gate signed off —
  `docs/r1.1/spec.md`.) [2026-07-23]

- **ADR-018 — Signal Path is CleanMuzik's visual identity; do not re-skin without a decision.**
  Dark-native "broadcast engineer's rack": IBM Plex Sans + Plex Mono (faces inlined, no CDN), a
  **desaturated** cyan accent `#3fb6d8` chosen so the amber/green/red **semantic** colours (needs-review
  / landed / failed) always out-shout it, a segmented-meter progress rail, wordmark **A** (a
  soundwave-in-a-ring seal + script "Muzik"), and exactly **one** ambient background signal line at ~7%
  opacity (frozen under `prefers-reduced-motion`) — **no spectrum bars, no other ambient motion.** Cover
  art shows only where it genuinely exists (landed tracks + the owned side of a duplicate); the
  weak-match picker stays text+score because the review event can't carry art (ADR-010). Rationale:
  chosen from a three-way pitch (Signal Path / Pressing Plant / Card Catalogue) for the calmest
  daily-driver voice, its mono-data discipline fitting durations/bitrates/scores, and the meter giving
  the progress rail — the product's spine — a native language. Full tokens + markup:
  `docs/r1/design/signal-path-tweaked.html`. (Owner decision, 2026-07-23, R1.1 skin sign-off.) [2026-07-23]

  **Amendment — the "console" direction supersedes the Signal Path screens; the EQ beat bars
  reverse the "no spectrum bars" line (2026-08-04).** T-105 first ported the approved gate faithfully.
  Seeing it live, the owner judged it templated ("AI slop") and, with taste-skill and two `claude-fable`
  passes, took it somewhere bolder: a **broadcast-console** skin. What changed, and what held:

  *Reversed.* The single ambient signal line at ~7% is gone; in its place a **36-bar EQ beat
  animation** across the base of the console. This **overrides** the original clause "**no spectrum
  bars, no other ambient motion**" — an explicit owner call on seeing both live, not a drift. Reduced-
  motion still freezes it. The wordmark treatment A (soundwave seal + script "Muzik") is replaced by a
  **big centred crest** (OutKast-style badge, 3D crown, CLEAN/MUZIK block letters).

  *Held.* The decision's *spine* is intact: dark-native, desaturated cyan `#3fb6d8` accent kept
  deliberately quiet so the amber/green/red semantic colours out-shout it, the segmented-meter progress
  rail (now segmented-LED), Plex Sans + Plex Mono inlined. **Cover-art discipline (ADR-010) is intact**
  — and was *tightened* in the 2026-08-05 review follow-up: the owned-side duplicate swatch, which had
  rendered unconditionally, was removed because it asserted art where none need exist (commit `819f22c`).

  *Canonical form.* Because the console direction was built live past the gate, its source of truth is
  the **shipped code** (`11b6302` + `819f22c`), not a flat screen. `signal-path-tweaked.html` and
  `t105-design-gate.html` are the superseded predecessors, kept for lineage only. The rename in ADR-018's
  title still holds in spirit — this is a visual identity you do not re-skin without a decision; the
  identity is now the console, not Signal Path. (Owner decision, 2026-08-04; review tightening 2026-08-05.)
  [2026-08-04]

- **ADR-019 — Shazam (`shazamio`) returns as a *backup identification tier* when AcoustID misses.
  This deliberately reverses its abandonment; it does NOT reverse ADR-005.** The tier order is
  `AcoustID → Shazam → manual re-search → keep-untagged`. Shazam answers only *"what is this?"*; its
  artist + title feed the existing MusicBrainz search and **beets remains the tagging engine
  (ADR-005 intact)**. The abandoned `music-cleaner` / secret-mode PRD used ShazamIO **as the engine** —
  that stays rejected. Same library, different job; the distinction is the whole decision.
  - **Three conditions, binding.** (1) **Identification only** — Shazam never writes tags, never picks
    a release, never bypasses MusicBrainz. (2) **Fail-soft** — on any error, timeout, rate-limit or
    no-match, the track parks exactly as it does today. (3) **A Shazam-derived match may never
    auto-land** — it populates review candidates for the owner to confirm and cannot by itself reach
    the 0.90 auto-accept bar (ADR-006), no matter how well its query scores at MusicBrainz. These are
    *conditions of the decision*, not implementation details: together they are the reason the tier is
    safe on a small sample, because its worst case is the current behaviour.
  - **Condition 3 was added 2026-07-27, after conditions 1–2 were shown to have a hole.** Run against
    Frank Ocean's *Strawberry Swing* — a **cover sung over Coldplay's original instrumental** —
    Shazam did not miss. It returned **Coldplay, Viva La Vida, ISRC `GBAYE1600219`**: confident, wrong,
    and none of "error, timeout, rate-limit or no-match". Fail-soft never engages. `Coldplay /
    Strawberry Swing` then scores **100** at MusicBrainz, so under conditions 1–2 alone the tier
    converts a track the system had **correctly refused to guess at** into a confidently mistagged
    auto-land. This is a class, not a one-off: anything built over another artist's master —
    interpolations, mixtape cuts, most of *nostalgia, ULTRA* — fingerprints as the original, because
    most of the mix genuinely *is* the original. Shazam gets a vote, not a verdict. The 4/5 rescue rate
    is unaffected; the tier still earns its place. (Measured, table in `docs/backlog/T-035.md`.)
  - **Normalisation is load-bearing, not incidental.** Shazam appends `(feat. X)` to titles; MusicBrainz
    keeps featured artists in the credit, not the recording title. Passing Shazam's fields through
    **verbatim scored 0 hits on 3 of 4**; stripping the trailing `(feat. …)` took all 4 to **score 100**.
    Phrase-quote the fields — an unquoted `"<title> <artist>"` search returns garbage (top hits
    *DJ Muggs — "Jay Z"*, *MERO — "Hussle Nipsey"*). ASCII-folding stylised artist glyphs (`JAŸ-Z`)
    affects ranking, not hit/miss. ISRC is a cheap *first* probe, never the bridge: it hit for JAY-Z and
    missed for Nipsey.
  - **Rationale — evidence, then shape.** Over the owner's real parked queue Shazam identified **4 of 5
    distinct tracks**, all clearing MusicBrainz at **score 100** (measurement + table in
    `docs/backlog/T-035.md`). The sample is **n=5**, which would be too thin to justify anything that
    could mis-tag — it is sufficient here *because* of the fail-soft condition. This also supersedes
    **T-034's auto-match Layers 0/2**: identifying by audio beats un-mangling a dirty YouTube string.
  - **Accepted risk, eyes open.** `shazamio` hits Shazam's private, reverse-engineered endpoints and may
    break with no notice; it adds a network dependency. The owner has explicitly accepted this
    ("willing to live with that it might not work because it's not an official library"). Mitigation is
    the fail-soft condition plus keeping Shazam behind a seam that can be removed without touching the
    pipeline — if it rots, the tier goes quiet and the queue returns to its present size.
  - **Does not remove the manual escape hatch (T-103) — it strengthens the case for it.** Two residual
    classes, neither an obscure artist: the Nines `"Franklin"` **music-video edit** (a particular *cut*
    of audio; Shazam identified the same artist correctly elsewhere) and the **cover-over-the-original
    -instrumental** case above, where Shazam answers confidently and wrongly. Manual re-search /
    keep-untagged owns both. Frank Ocean's *Strawberry Swing* is the live fixture: audio intact,
    AcoustID silent, Shazam wrong, and the correct recording sitting in MusicBrainz at score 100
    waiting for a human to point at it.
  (Owner decision, 2026-07-25, on the T-035 rescue-rate measurement.) [2026-07-25]
- **ADR-020 — A parked review gets two first-class exits: *re-search* and *keep-untagged*. Reject stays
  required; pasting an MBID is a quiet advanced affordance, not the primary gesture.** Ratifies the
  T-103 design the owner signed off on the six flat screens in
  `docs/r1.1/design/review-rescue-flow.html` (ADR-016 gate passed 2026-07-29).
  - **The hole it closes.** Today a parked review's only real exit is **Reject**, which throws away good
    audio. That is wrong whenever the owner *knows the answer and the machine doesn't* — which is not an
    edge case but two recurring classes: an empty candidate list, and a **wrong-but-present** one. The
    second is the trap: a confident-looking list of five candidates is indistinguishable from a useful
    one until you read it. Frank Ocean's *Strawberry Swing* and Nines *Outro* are both live fixtures
    with independently-known correct MBIDs (`908e389b…` and `f5d1bcfb…`, each at MusicBrainz score 100).
  - **Exit 1 — re-search (the everyday gesture).** The owner corrects the artist/title and the app
    re-queries MusicBrainz in-app, repopulating candidates. The form is **pre-filled with what the
    machine guessed**, deliberately: seeing that it read `Title - Artist` backwards is what makes the
    correction obvious. This is the mainline exit and the one that must feel cheap.
  - **Exit 2 — keep-untagged (the last resort).** The file lands with owner-supplied tags and **no**
    MusicBrainz match, with the trade-off stated on the card: no cover art, no auto-genre, because both
    require a match. For bootlegs, mixtape rips and YouTube-only mixes that genuinely aren't in the
    database. *In the library beats in the trash*, and it can be re-tagged later.
  - **Binding consequences.** (1) `_validate_weak_match` (`reviews.py:168`) must relax — today it refuses
    any recording that isn't already a candidate, which is exactly what makes re-search impossible; the
    landing machinery it would call (`resolve_import` / `_forced_match` in `import_seam.py`) already
    lands an arbitrary recording. (2) **An empty re-search result is not a dead panel** — it offers
    *search again* and *keep-untagged*, never a terminal state. (3) Keep-untagged must not fabricate a
    match: no invented MBID, no borrowed release, and the absence must be visible in the library, not
    papered over. (4) Reject survives unchanged — this adds exits, it does not remove the one that
    discards.
  - **Why this and not more automation.** ADR-019's Shazam tier and the deferred LLM-disambiguator tier
    (`docs/backlog/T-035.md`) both change *how often* this exit is reached, never *whether* it is needed:
    each has a class it answers confidently and wrongly. A manual exit is the only one whose failure
    mode is the owner's own judgement. **This ADR is therefore a prerequisite for both**, not an
    alternative to either.
  - **Blast radius.** Unblocks **T-106**'s last gate, whose end-to-end resolve cannot be demonstrated
    through the route until re-search exists (see T-106's status line) — the two verify together. Feeds
    **T-102**, which owns the inbox row that renders these exits.
  - **Amendment (2026-07-29, from building exit 1): consequence 2's trigger was wrong, its rule
    stands.** "An empty re-search result is not a dead panel" assumed an empty result is how "not in
    MusicBrainz" presents. Measured: it almost never is. A deliberate-nonsense search returned **25
    results** (MusicBrainz matches loose tokens), so the real shape is *many results, all wrong, best
    score ~0.40* — the wrong-but-present dead-end again, one level down. The empty state stays and
    stays correct where it occurs, but **keep-untagged must not be gated on it**: exit 2 is reachable
    whenever the owner says so, not only when a result count hits zero. And no threshold is added to
    infer absence from a low score — inventing a confidence bar is what ADR-006/ADR-010 refuse, and it
    would misfire on the Nines fixture (correct answer at 0.757 among five near-identical rows). Full
    measurement in `docs/learnings.md`.
  (Owner decision, 2026-07-29, on sign-off of the six-screen flow.) [2026-07-29]

- **ADR-021 — The LLM adjudicates identity (veto/confirm) and authors the opinion layer
  (genre/mood/style); beets + MusicBrainz remain the engine of record. Narrows ADR-005 — does not
  repeal it.** Splits ADR-005's two halves. The *identification* half reopens: an LLM replaces the
  bare `_matching_candidate` + `SCORE_MIN` boolean at `import_seam.py :: choose_item`, injected like
  `dominance_fn` so tests stay offline. The *writer / organizer* half must **not** reopen — beets
  keeps landing, dedup, NTFS-on-WSL path sanitization, `%aunique` collision handling (the
  hard-to-rebuild plumbing ADR-009/010/015 + T-029 hardened over four rounds). **Containment is
  structural, not a prompt:** on the auto-land path the LLM may only **CONFIRM** the fingerprint's
  top recording or **VETO-to-park** — `chosen_mbid` is enum-constrained to the supplied candidate
  MBIDs, `_matching_candidate` survives as a hard veto, and accept requires
  `dominance.top_score >= SCORE_MIN` **AND** `verdict == accept` **AND**
  `chosen_mbid == top_recording_ids[0]`. It may **never** override to a recording the fingerprint
  didn't return (veto-to-park is worst-case-equals-today; override-to-different is how it would
  corrupt a match the fingerprint got right). Facts (recording MBID, ISRC, year) stay MusicBrainz's;
  the LLM never authors them — it hallucinates every one, and dedup + T-037 rest on a *real* MBID.
  Rationale: spike lock 1b measured **0/17 overrides** and caught the Pa Salieu "Frontline" → Vanessa
  Bling mistag on real audio; lock 7 measured the path ~12× faster. Evidence:
  `docs/research/engine-rethink-spike.md`; design: `engine-rethink-council.md §1`.
  (Owner ratified 2026-08-09 on the spike gate.) [2026-08-09]

  - **Amendment (2026-08-10) — veto-only containment SUPERSEDED by "senses vote" (2-of-3).** The full
    B-flow spike (exp 8 + exp 9, `engine-rethink-spike.md`) reversed this ADR's core containment. The
    original clause — *"the LLM may never override to a recording the fingerprint didn't return"* — is
    **withdrawn**. New rule: **auto-land requires ≥2 independent senses (yt-dlp title / AcoustID
    fingerprint / Shazam) to agree on the identity; any disagreement parks.** The LLM *may* now land a
    recording the fingerprint didn't return **iff two other senses corroborate it.** *Why the reversal:*
    exp 9's marquee case (Pa Salieu "Frontline") — which A/veto-only could only **park** — B **resolved
    correctly and auto-landed** precisely by trusting yt-dlp + Shazam over a wrong fingerprint. The
    veto-only rule was strictly *safer* but strictly *less capable*; the 2-of-3 rule keeps the Pa Salieu
    catch's safety (a lone dissenting sense still parks) while gaining the fix. **Still binding from the
    original:** facts (MBID/ISRC/year) come only from a real lookup, never LLM-invented (now ADR-021 Rule
    2); Shazam never auto-lands *alone* (it is one of the ≥2 votes, never the sole one). **Eyes-open:** the
    override-when-2-agree is validated at n=1; wider real-use sampling is owed. This also supersedes the A
    shape of `docs/r1.5/spec.md`, which must be rewritten for B. (Owner decision 2026-08-10 on the exp 8/9
    head-to-head.) [2026-08-10]

- **ADR-022 — Landing is strictly serial (pool = 1); the rest of the pipeline may parallelize
  per-stage. Narrows ADR-001 — does not repeal it.** ADR-001's blanket "sequential, do not
  parallelize" reopens as a *per-stage* constraint: **download** pool 1–3 with delays/jitter
  preserved (a first-class rate-limiter, not incidental spacing), **transcode/fingerprint** parallel
  to cores, **identify** fans out for LLM/Shazam while AcoustID/MusicBrainz queue on their own
  limiters. **Land stays pool = 1** — the moment there is a second worker, `choose_item`'s live dedup
  (ADR-009) double-lands. Land serialization is the single point at which ADR-001's rate-limit and
  dedup protection now lives. Rationale: measured wall-clock put the cost in *identify*, not download
  (`engine-rethink-council.md §2a`), so per-stage parallelism is the real lever — but only above the
  serial land point. **Not yet safe to build:** no fan-out ships until the throttle probes (spike
  exp 5/8) run; R1.5 lands the adjudicator serially. Parallelism is an R2.x/R3 layer over the single
  serialization point, **not** an R2 blocker. (Owner ratified 2026-08-09 on the spike gate.) [2026-08-09]

- **ADR-023 — Genre/mood is authored by the LLM against an owner-curated enum that MUST include an
  explicit `uncertain` member; drop the `lastgenre` plugin.** Remove `lastgenre` from `PLUGINS`
  (`beets_engine.py:52`). Author `genre` + `mood`/`style` as a post-run tag write in
  `finalize_outcomes`, mirroring `_stamp_original_year`. Constrained to a curated enum whose
  `uncertain`/`unsorted` member is **load-bearing, not optional**: without it a forced enum converts
  Last.fm's honest blank into a confident wrong fill on contested micro-genres (drill / road-rap /
  grime / afroswing / dancehall all post to the same channels — "GRM Daily", "Link Up TV" — which
  name the *scene*, not the *sub-genre*). Fail-soft (blank on error), deterministic (temperature 0 +
  cache keyed by recording MBID). Last.fm is **demoted to a witness** (one input), not deleted. This
  opinion layer is a genuine LLM strength (no ground truth to contradict) and is the foundation the
  future "AI librarian" direction stands on (see `cleanmuzik-prd.md §2.1`). Rationale + risk R3:
  `engine-rethink-council.md §4`. (Owner ratified 2026-08-09 on the spike gate.) [2026-08-09]

- **ADR-024 — Shazam runs in an isolated 3.12 subprocess, and now runs on EVERY track (widens
  ADR-019).** Two decisions the R1.5 Shazam sense (T-202) forced onto the record; both reverse or
  widen something already written, so per the no-silent-reversal rule they are logged here.

  **(a) The Shazam recognition runs as a subprocess against the 3.12 venv `server/.venv-shazam`,
  not in-process.** The app runs on Python 3.14, which has **no `shazamio-core` wheel**, so the
  recognition cannot be imported into the worker. `app/shazam.py` (3.14 side) spawns
  `app/shazam_runner.py` — a standalone script that imports `shazamio` + stdlib and **nothing from
  `app`** — with the 3.12 interpreter. The boundary is a *process*, not an import, on purpose: it
  (1) keeps the app on 3.14 while the wheel only builds on 3.12, and (2) quarantines the
  reverse-engineered dependency (ADR-019's explicitly accepted risk) behind a wall that can be
  **SIGKILLed on timeout without touching the worker** — the child is spawned in its own process
  group (`start_new_session=True`) and a hang is killed with `killpg`, so nothing it spawned
  survives. **Subprocess contract:** `argv[1]` = audio path in → one JSON §6 record on **stdout**
  (ffmpeg decode noise goes to stderr and is ignored); the runner always exits 0 once it prints a
  record, so a non-zero exit means the runner itself failed to run (e.g. `shazamio` missing) and the
  parent maps that to a non-vote. **Hard wall-clock timeout, default 8s, tunable** (per-call arg +
  `SHAZAM_TIMEOUT_S`): a hang → `{matched:false, error:"timeout"}` returned within the cap, because
  on the serial pipeline an un-killed hang blocks every later track (exp 8 saw ~28s tail spikes) — a
  hang is *killed*, not treated as "unavailable". **Pin-3.12 (run the whole app on 3.12) and
  vendor-wheel (build/vendor `shazamio-core` for 3.14) are documented fallbacks only**, taken only if
  the subprocess path fails in build; it did not (verified live end-to-end, 3.14 app → 3.12 subprocess
  → `matched:true` + real ISRC `USDJ20301465` on the JAY-Z corpus track). Any error / empty / timeout
  ⇒ Shazam is a *non-vote*; it is never written as a tag on its own authority (enforced downstream at
  the T-205 gate). Records `art_url`/`lyrics` into the §6 record but **writes neither** (spec §3 —
  art/lyrics land via the existing beets path; the fields are captured for the record only).

  **(b) Shazam now runs on EVERY track — widening ADR-019's "backup tier".** ADR-019 defined Shazam
  as a *backup identification tier* reached only **when AcoustID misses** (tier order `AcoustID →
  Shazam → …`). R1.5 runs the Shazam call on **every** track, unconditionally, as one of three
  independent senses fed to the reconcile call (spec §2). This **reverses ADR-019's tier order** — it
  is no longer a fallback behind a fingerprint miss but a first-class parallel sense — so it is
  recorded here rather than changed silently. Authorized by spec §2 and safe **only under the serial
  pipeline** (ADR-022, pool = 1): per-track Shazam is affordable at one-track-at-a-time cadence and its
  tail latency is capped by the (a) timeout. ADR-019's three binding conditions are **untouched and
  still hold**: identification only (never writes tags / picks a release / bypasses MusicBrainz),
  fail-soft, and — the load-bearing one for this widening — **a Shazam-derived match may never
  auto-land alone**; under R1.5 it is one of the ≥2 senses the 2-of-3 gate requires (ADR-021 amended,
  spec §5), never the sole vote. The *Strawberry Swing* cover class ADR-019 condition 3 was written
  for (Shazam confidently returns the wrong recording's real ISRC) is caught by that gate, not by this
  tier. (Owner-authorized via spec §2/§5; filed on building T-202.) [2026-08-10]
