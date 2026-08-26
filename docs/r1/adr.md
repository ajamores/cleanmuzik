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
  survives. **Subprocess contract:** `argv[1]` = audio path in → the JSON §6 record as the **last
  non-empty stdout line** (the parent parses that line, not the whole stream, so shazamio's
  reverse-engineered decode stack can emit noise to stdout ahead of it without breaking the parse);
  the runner always exits 0 once it prints a record, so a non-zero exit means the runner itself
  failed to run (e.g. `shazamio` missing) and the parent maps that to a non-vote. **Hard wall-clock
  timeout, default 8s, tunable** (per-call arg + `shazam_timeout_s` in `.env`, bounded `> 0` via
  Settings so a zero/negative cap can't silently disable the sense): a hang →
  `{matched:false, error:"timeout"}` returned within the cap, because
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

- **ADR-025 — The reconcile model is `claude-haiku-4-5` at `temperature=0`; do NOT "upgrade" it to
  the newest Opus/Sonnet without removing `temperature` and re-validating the §7 corpus.** The R1.5
  reconcile call (`app/reconcile.py`, T-204) pins model `claude-haiku-4-5` and sends `temperature=0`
  (spec §5's determinism requirement). This is a **deliberate exception to the global "default to the
  latest, most capable Claude model" rule**, recorded so a future session doesn't silently reverse it:
  (1) the current frontier family (Opus 5 / 4.8 / 4.7, Sonnet 5) **rejects any sampling parameter with
  a 400** — sending `temperature=0` to them errors the call, so "just bump the model" breaks the seam;
  (2) Haiku 4.5 is the model the whole architecture-B spike ran on, so it is the model the **§7
  acceptance corpus (= the exp-9 cases) was validated against** — changing it invalidates that mapping;
  (3) it is the cost/latency fit for a per-track call (spec §5, ~$0.05–0.20 for the corpus). **To
  change the model:** drop `temperature=0` (frontier models are deterministic-ish without it and 400
  on it), then re-run the T-209 §7 sweep to confirm Pa-Salieu-lands / Strawberry-Swing-parks still
  hold on the new model — never a blind swap. Structured output is a **forced `tool_choice` on a single
  `record_verdict` tool** whose `chosen_candidate` is an enum over the present candidate indices + null
  (no free-text identity field), so the LLM can only point at a real-MBID candidate by index and can
  never author an MBID (spec §5; the spike's free-text `{artist,title,mbid}` schema is the forbidden
  shape). Confidence is **structurally absent** from the `Verdict` dataclass, so it cannot travel past
  the seam (spec §5, confidence never load-bearing). (Filed on building T-204.) [2026-08-10]
- **ADR-026 — A spike's numbers pass a council review before they enter a spec.** Before any figure
  produced by a research spike (speed, accuracy, confident-wrong rate, …) is promoted into a spec — as
  an acceptance criterion *or* as justification to take on / defer scope — it passes a design-council
  pass whose sole job is to confirm the spike **ran earnestly**: that it measured the same end-to-end
  work the integrated pipeline actually does, on comparable live inputs, and not a flattering isolated
  slice. Rationale — R1.5's ~8.6× / <6s speed claim measured the new senses alone against a fixture,
  ignored the work the real pipeline already does on the track, and rode into §7 as an acceptance
  criterion; it was caught only at T-209 verify, forcing a mid-verification amendment (`docs/learnings.md`
  2026-08-13). The same design council that later corrected the fan-out analysis would have caught the
  inflated number at the source. **Scope:** spike-produced numbers headed *for a spec* — not every
  benchmark, and not numbers that stay in the research doc. Binds alongside **ADR-016** (design gate) as
  a standing process gate; rationale + placement in `docs/workflow.md`. [2026-08-13]
- **ADR-027 — The R2 batch/backfill data model: one `playlists` row + N member `jobs`, joined by a
  nullable `jobs.playlist_id`, with an app-side membership store as the source of truth.** The
  association every R2 ticket reads (T-302/304/305/306/307/312 all import this shape). A batch reuses
  the per-song `jobs` row and the whole R1/R1.1 pipeline + review lifecycle unchanged; the only new
  spine is the join. **Entity shape** (in `db.py`): `playlists(id, youtube_playlist_id UNIQUE, title,
  jellyfin_playlist_id NULLABLE, created_at)`; `jobs` gains three nullable columns `playlist_id` (FK →
  `playlists.id`), `position`, `youtube_video_id`; a `playlist_members(playlist_id FK, youtube_video_id,
  position, jellyfin_item_id NULLABLE, UNIQUE(playlist_id, youtube_video_id))` membership store.
  **`jobs.playlist_id` is an app-enforced association, not a DB FK** — SQLite's ALTER ADD COLUMN cannot
  attach a REFERENCES clause, so despite `PRAGMA foreign_keys = ON` the link is upheld by discipline
  (T-302 only ever sets it to a just-upserted playlist id); the *reverse* link
  `playlist_members.playlist_id` IS a real enforced FK (that table is created whole in `_SCHEMA`).
  **Membership and the member `jobs` row are deliberately not 1:1**: a dedup-skip (T-303) adds a
  membership row with **no new job** (it reuses an existing landed job elsewhere), so there is no
  member→job FK and seam 5 reconciles the two stores as *complementary* views (jobs-by-status for
  processed tracks, membership for skipped/added), not redundant ones. Membership `position` carries no
  uniqueness constraint (a skip re-adds at the entry's own index, which can collide), so `list_members`
  orders `position, rowid` for a deterministic tie-break. Both hot read paths (dedup `EXISTS` on
  `youtube_video_id`, tally group-by `playlist_id`) are indexed on `jobs` at migration time.
  **`jobs.playlist_id IS NULL` is the R1 switch** — a single-song paste writes a null-`playlist_id` job
  and runs R1 byte-for-byte (acceptance item 11); a regression there is a build failure, not a
  trade-off. **Schema vs. migration are two different mechanisms and must not be conflated** (this was a
  cold-review BLOCKER): the two new tables go in `_SCHEMA` as `CREATE TABLE IF NOT EXISTS` (they don't
  exist on the live DB; the guard creates-then-no-ops) — required because SQLite's `ALTER TABLE … ADD
  COLUMN` cannot add a `UNIQUE` column, and both need one; the three `jobs` columns go in
  `_ADDED_COLUMNS` (ALTER ADD COLUMN, legal because each is nullable-with-no-default). The T-206 lesson
  forbids smuggling a new *column* into an existing table's CREATE — it does not forbid `CREATE TABLE IF
  NOT EXISTS` for a genuinely new table. **The membership store is read three ways:** re-paste skip-check
  (T-307), aggregate counters (T-305/T-312), and backfill (T-306). **The backfill chain is locked:**
  `review → job → playlist → jellyfin_playlist_id`. **Six seams the schema alone doesn't settle** (all
  surfaced by cold-review; the timing/durability/idempotency decisions the mockups and downstream
  tickets depend on):
  1. **Jellyfin item-ID post-scan resolve (T-304).** Jellyfin's scan is async, so a landed file's item
     id exists only after it indexes. Resolve by polling Items-by-path on a **bounded interval with a
     hard timeout**, and it **must not block the sequential worker** (a blocking wait per track serializes
     a 50-track batch into minutes of dead `/Library/Refresh` waits). **On timeout: write the app-side
     membership now with `jellyfin_item_id = NULL` (a *pending append*) and defer the Jellyfin append for
     the next scan to reconcile — never a silent drop.** **Owner-settled [2026-08-15]:** poll
     every **2s up to a 10s hard cap** (30s was judged too long a stall for the sequential worker), then
     defer; the reconcile pass retries pending appends on the next batch's scan. The `playlist_members`
     row with `jellyfin_item_id IS NULL` is that pending append's durable home. **Push (webhook/SSE) is a
     live candidate to weigh at T-304, not a dismissed one [owner steer, 2026-08-15]:** Jellyfin's
     Webhook plugin is push and, per the owner, likely low-effort to install and configure — so evaluate
     it against polling when the resolve is actually built. The **cost to weigh against that ease** is
     architectural, not effort: push means a **second Jellyfin integration point** (a plugin on the
     server + an inbound endpoint on this app), which the spec's one-seam rule deliberately resists.
     Polling Items-by-path keeps the single seam with no server-side setup; ship polling for R2, and
     switch to push at T-304 only if the plugin proves as cheap as expected AND the second seam is judged
     worth it (or polling proves too slow).
     **[Resolved 2026-08-16, T-304 build] — polling confirmed, plugin rejected.** The push assumption
     was evaluated against the plugin's actual behaviour and does not hold: the Webhook plugin's
     **`ItemAdded` notification is not a real-time push** — it is fired by a Jellyfin *scheduled task*
     ("Webhook Item Added Notifier") that batches on an interval, with **reported 15–45 min delays**
     ([#367](https://github.com/jellyfin/jellyfin-plugin-webhook/issues/367)) and open reliability bugs
     on that exact event: no-fire ([#252](https://github.com/jellyfin/jellyfin-plugin-webhook/issues/252),
     [#232](https://github.com/jellyfin/jellyfin-plugin-webhook/issues/232)) and mis-fire on playback stop
     ([#358](https://github.com/jellyfin/jellyfin-plugin-webhook/issues/358)). So push is **slower and
     flakier** than the 2s/10s-cap poll — not faster — and because `ItemAdded` can silently no-fire, a
     webhook design would **still need polling underneath** as a correctness net (both, not instead). The
     one-seam poll is the simpler *and* faster answer; **do not re-litigate at T-306.**
     **[Superseded inline timing — 2026-08-16, T-304 build; 4-lens council + owner, ratified.]** The
     owner-settled "poll every 2s up to a 10s hard cap, then defer" was written for an *inline* resolve —
     polling a **just-landed** track's own index on the worker. That timing is retired: a batch of N such
     waits adds ~10s×N of dead time to the strictly-sequential worker (ADR-001), the exact per-track tax the
     owner flagged. The insight that retires it: **a track's own index is always the least-settled thing in
     the system (0s old), so the cheapest id to resolve is never your own — it's a predecessor's**, landed a
     full pipeline-cycle ago and already indexed. So the worker **never polls at all**. Instead: (a) at land,
     write the pending membership row immediately (`jellyfin_item_id NULL` + `landed_path`) and move on —
     ~0 added critical-path time; (b) **opportunistically drain** a few of the *oldest* pending appends on
     each subsequent land (single non-blocking `resolve_item_id` each — a **local** Jellyfin call, outside
     ADR-001's rate-limit concern — so the playlist fills live-ish as the batch runs); (c) a **durable
     background reconcile tick** (~25s) + a **boot sweep** own the *tail* — a batch's last tracks have no
     later land to trail them, so the tick, not the opportunistic drain, is the correctness floor that
     guarantees they eventually join. The 2s/10s poll is gone entirely; a resolve is now a *single attempt*
     retried across passes. **`resolve_item_id` / `append_to_playlist` are the two seam functions** (same
     `jellyfin.py`, no second integration point). **The pending-append durable home also persists the landed
     canonical path as `playlist_members.landed_path` (nullable)**, because the reconcile pass resolves a
     deferred item via `Items?Path=` and has **no other durable handle** (Jellyfin indexes by on-disk path);
     this is an *operational* retry-handle, **not** the transient *display* path ADR-015 made non-durable
     (different table, different consumer, sole durable copy of the datum). It is added via `_ADDED_COLUMNS`
     (ALTER), **not** the `playlist_members` CREATE — a cold-review catch: that table SHIPPED in T-300 and is
     on the owner's live DB, so a column on the `CREATE TABLE IF NOT EXISTS` would silently never land (the
     exact T-206 lesson; the "new table, no shipped DB" reasoning was wrong — R2-as-a-*release* isn't shipped,
     but the *table* is). Both columns are ALTER-legal (`landed_path` nullable; `append_attempts` NOT NULL
     *with a DEFAULT*). A bounded `append_attempts` (cap 20) turns a never-indexable file into a **visible**
     give-up (a warning; surfaced in the batch view at T-305/T-312), never an infinite retry or a silent drop
     — silent loss being the one failure a walk-away owner cannot catch. **M3U weighed and rejected here:** an
     on-disk `.m3u` of paths (letting Jellyfin import the playlist on scan, skipping item-id resolution) was
     researched against Jellyfin's own `PlaylistResolver` — it does **not** skip the index wait (Jellyfin
     won't link a path until it has independently indexed the file), trades the clean pollable checkpoint for
     a silently-empty playlist with no signal, is **read-only in the UI since 10.9**, and has a 10.9-line
     history of playlists wiped on scan ([#11625](https://github.com/jellyfin/jellyfin/issues/11625),
     [#12110](https://github.com/jellyfin/jellyfin/issues/12110)). The item-id API is the lower-risk path;
     **do not re-open M3U.** (The built-in `LibraryChanged` websocket, which *pushes* new item ids, is a
     possible future latency upgrade — but its 30s default debounce makes it slower than the poll out of the
     box, and it adds a second integration surface; not for R2.) **The `queued`-job re-enqueue on restart is
     out of scope here** — a mid-batch crash still errors un-run tracks (T-104); "walk away, come back across
     a restart" for *unprocessed* tracks is T-312. What T-304 guarantees restart-safe is the **pending
     append**: its row is durable and carries its path, so the boot sweep drains it.
     - **Amendment [2026-08-17, T-313 build — two councils vs. the shipped code, owner-approved]: the
       give-up *counter* is retired; the poll *target* gains the playlist's own membership.** T-304's
       `append_attempts` (cap 20) was **a retry tally used as a clock**, and it shipped three bugs: a
       fast batch of cached videos burned the cap in seconds and **dropped healthy tracks**; the
       append-before-stamp window **double-added** on a crash; and a `resolve_item_id` that returned a
       bare `None` **could not tell "not indexed yet" from "Jellyfin unreachable,"** so an outage spent
       the whole budget and stranded everything. The reframe, keeping incremental fill (append each
       track as it lands — **batch-at-end was adversarially reviewed and rejected**):
         - **`resolve_item_id` is now 3-state** — `RESOLVED` / `NOT_INDEXED` / `UNREACHABLE` (a
           `ResolveResult` whose invariant makes `RESOLVED(None)` unconstructible, so a malformed 2xx
           can never POST `Ids=None`). UNREACHABLE defers untouched and spends nothing.
         - **The append is pre-checked and idempotent** — the reconcile pass reads the playlist's
           current item ids once per pass (`get_playlist_item_ids` → `GET /Playlists/{id}/Items`) and
           appends only an absent item, then stamps. The stamp is now a record of *observed*
           membership, not the sole idempotency guard, so a crash between POST and stamp cannot
           double-add. An unreadable pre-check (`None`) defers the whole playlist — **never a
           blind-append.** The no-penalty/defer treatment extends to the append organ (`JellyfinAppendError`
           / degraded no-op), or bug 3 survives there.
         - **`append_attempts` → `playlist_members.stuck_since` (nullable TEXT).** The counter is
           **retired**: a dead column on pre-T-313 DBs (never read, never dropped — a rebuild is
           needless risk), absent on fresh ones; benched rows re-enter the pending set by design (they
           were outage victims). Its replacement is a **wall-clock** ceiling (~45 min of
           *reachable-but-unindexed* passes) that flags a row **visible-and-still-retried**, never
           benched. UNREACHABLE passes spend nothing, so an outage can never mark a healthy row stuck,
           and a never-indexable file surfaces (the surface itself is T-305/T-310) instead of vanishing.
       **"Poll not push" stands.** The first-party `LibraryChanged` websocket remains a *future
       accelerator over this same ledger* (kills only 2 of the 3 bugs — the double-add is transactional,
       orthogonal to the readiness signal — and a half-open socket reintroduces the silent-stop the
       Webhook plugin was rejected for), **not** built for R2. Supersedes backlog **T-047**.
     - **Amendment [2026-08-17, T-314 build — live spike against the real Jellyfin, owner-approved]: the
       playlist seam was non-functional live; two API-shape assumptions were wrong.** The whole
       create→resolve→append path had only ever run against fake-http unit tests; T-313's `/verify` was
       first live contact and it failed. Fixes:
         - **Playlist ops are user-scoped.** Jellyfin playlists belong to a user account: `POST /Playlists`,
           the append `POST /Playlists/{id}/Items`, and the T-313 pre-check `GET /Playlists/{id}/Items` all
           400 / return an odd empty body **without a `userId`**. The tool ships without one, so
           **`resolve_user_id` auto-discovers it** (`GET /Users` → admin-else-first, cached per (url,key),
           degrades to None) — chosen over a `JELLYFIN_USER_ID` setting (single-user; nothing to configure).
           `create_playlist` sends `UserId`; append + pre-check send `userId`; each degrades in its own
           idiom when the id can't be resolved (create → NULL id, append → `JellyfinAppendError` so the row
           stays pending, pre-check → None so the pass defers — never blind-appends).
         - **`resolve_item_id`'s `Items?Path=` filter is IGNORED by the live server** — it returned the
           whole recursive library, so T-304's `items[0]` was the library-root *folder*. Replaced by an
           **exact client-side path match** over the audio items (`IncludeItemTypes=Audio&Recursive&
           Fields=Path`). The T-313 3-state contract is preserved. *"Poll not push" and the reconcile ledger
           are unchanged* — this is purely the HTTP shape of the two Jellyfin calls. Verified live: a real
           track landed in a real playlist through the app code (T-314 `/verify`).
  2. **Landed-video dedup store + predicate (T-303).** One store — the `jobs` row's `youtube_video_id`,
     written at **enqueue** (T-302) — and the exact, status-filtered test
     **`EXISTS(job WHERE youtube_video_id = ? AND status = 'done')`**. The `status='done'` filter is
     load-bearing: without it a **parked or failed** never-landed entry reads as "already owned" and a
     re-paste skips it forever. Never fuzzy; a genuinely different upload is treated as new (US13).
     - **Amendment [2026-08-17, T-303 build — owner-approved]: the predicate needs a *where*, not just a
       *whether*.** `EXISTS(status='done')` proves a video is **owned** but not **where its file is** — and
       the skip's whole job is to *add that file to the playlist*, which `add_member` cannot do without a
       resolvable `landed_path` (a pathless membership row is T-304's undrainable dead letter). So the
       durable store grows a **fourth `jobs` column, `landed_path`** (nullable, ALTER-legal), stamped at
       land in `_finish` (every landing — R1-single and batch — routes through it, so it is the one
       video→path map). The skip reads `landed_path_for_video` = *newest `done` job for the video whose
       `landed_path IS NOT NULL`*. **This narrows, not reverses, ADR-015:** ADR-015 keeps the landing off
       the row as a **display** receipt (the card reads the `track.done` event); this is an **operational**
       dedup handle read by a re-paste months later — different consumer, sole durable copy, exactly as
       `playlist_members.landed_path` already is for the append machinery. The reconcile snapshot route
       still surfaces no path (ADR-015 intact for the client). An **owned-but-unlocatable** landing (a
       pre-migration row, or a REPLACE-resolve that landed with a null path) reads `None` and is
       **re-processed**, never skipped into a dead-letter membership row. The skip lands a **distinct
       `status='skipped'`** (not `done`), because the T-305/T-312 tally counts skips as their own bucket
       off `jobs.status`.
  3. **Jellyfin playlist create timing.** Create the Jellyfin playlist at **`batch.queued`** (expansion,
     T-302), **not** on first land — else an all-parked batch never gets a `jellyfin_playlist_id` and its
     later backfill (T-306) has nowhere to append. **Owner-settled [2026-08-15]: create-at-queued.**
     The alternative (backfill creates-if-missing) is kept only as a **guard** in T-306 for the
     should-not-happen null case, not as the primary path.
     - **Create/resolve split across T-302/T-304 — council-settled [2026-08-16] (4 lenses: ticket-DoD,
       backend-architecture, ADR-fidelity, integration-risk — unanimous; owner-settled the failure
       contract).** Seam 3 is *inside T-302's accept path*, so the **`create_playlist` capability is built
       and called in T-302**, not deferred to T-304 — else T-302 integrates onto `main` with an
       all-parked batch carrying a NULL `jellyfin_playlist_id`, the exact state this seam forbids, for the
       whole T-302→T-304 window (a silent seam-3 reversal at the ticket boundary). Create is cohesive with
       the `upsert_playlist` that decides whether a create is even needed (a re-paste returns the existing
       row with its id already set) and cleanly separable from the seam-1 machinery (a plain `POST
       /Playlists` returning an id, no scan-timing coupling). **T-304 keeps only the hard, coupled parts:
       post-scan resolve, append, and pending-append reconciliation.** The one-seam rule (no *second*
       Jellyfin integration point) is about integration points, not authorship — `create_playlist` and the
       future `append` are disjoint functions in the *same* `jellyfin.py` seam, landed in dependency order.
     - **Failure contract — owner-settled [2026-08-16]: `create_playlist` degrades to `None` on BOTH
       config-absent AND a present-but-failed POST** (deliberately *unlike* `trigger_scan`, which raises on
       a present-but-failed scan). A create fires at the accept door and gates **all N enqueues**, so a
       transient Jellyfin blip must not abort a 50-track paste — the batch still upserts, expands, enqueues,
       and lands canonically on disk; `jellyfin_playlist_id` stays NULL and lands squarely in the T-306
       create-if-missing guard above. `trigger_scan` raises because a scan failure is a nameable *per-track*
       stage; a create failure has a whole-batch blast radius, which warrants the degrade. Warn on the
       degrade so a Jellyfin-less (or -flaky) run is never silent.
  4. **Membership uniqueness + per-entry order.** `UNIQUE(playlist_id, youtube_video_id)`; append is a
     **no-op when membership exists** (`ON CONFLICT DO NOTHING`, returns "already a member"). Per entry
     the fixed order is **membership-check → library video-dedup → process**, so a re-paste of an
     already-in-playlist owned video cannot double-add.
  5. **Durable batch state (T-312).** The batch tally + terminal state must be **derivable from
     `jobs.playlist_id` (grouped by status) + the membership store**, not only accumulated in the
     in-memory event bus — so "walk away and come back" survives a **restart**, not just an in-process
     reload. `batch.progress` is computed from this durable state.
  6. **`playlists` create-or-reuse is an atomic upsert.** `INSERT … ON CONFLICT(youtube_playlist_id) DO
     NOTHING` then SELECT (one transaction) — not SELECT-then-INSERT, which races a double-paste into an
     `IntegrityError` on the UNIQUE key. A re-paste reuses the original row (same id, same title, same
     `jellyfin_playlist_id`), which is what makes T-307 idempotent.

  Recorded before the design gate (T-310) because retrofitting the association into live job data later
  is unrecoverable (spec §Implementation "Batch model" + §Further Notes). Implemented in T-300 (schema +
  DAO); the two flagged owner decisions carry recommended defaults above. [2026-08-15]
- **ADR-028 — The artist-credit written to a matched landing is normalised to the owner's single
  canonical identity before beets applies it: NFC floor + an enumerated confusable map (today only
  `Ÿ`→`Y`) + a hyphen-class fold. This is deliberate *identity normalisation*, not mojibake repair, and
  it binds every write path.** The T-037 decision (T-301); T-308 implements it. Council-reviewed
  2026-08-15 (four lenses + chair, `docs/research/` transcript in the run journal; owner picked the
  layered+observable reach).
  - **The diagnosis the ticket carried is corrected on the record.** T-037 (`docs/backlog/T-037.md`)
    calls the `Ÿ` a mojibake "**in our write path**." It is not, and cannot be: a plain ASCII `Y`
    (`0x59`) cannot decode into `Ÿ` (U+0178) under any codec (U+0178 needs `0x9F` in cp1252 or
    `0xC5 0xB8` in UTF-8). All four council lenses independently grepped `server/` — no decode/encode/
    `errors=`/`latin-1`/`cp1252` fault exists; the only decode in the seam is `os.fsdecode` on the file
    *path*. **MusicBrainz serves the stylised credit `JAY‑Z` (with a Unicode hyphen U+2010), and beets/
    mediafile write it faithfully.** Nothing we own mangled a clean `Y`. Framing this as "our decode is
    broken" is a landmine: a future reader hunts a bug that cannot exist, or deletes the fold as
    redundant and re-splits the library. So the decision is framed as reconciling MB's per-release
    *artist credit* to the owner's one canonical Jellyfin identity.
  - **(a) Fold scope — surgical, layered.** An **NFC** canonical-composition floor (lossless, idempotent,
    identity-preserving — it also closes the *same* split class where a precomposed `Beyoncé` and a
    decomposed `Beyonce`+U+0301 land two folders) beneath a **declared, extensible confusable→canonical
    map**, today exactly one pair: **`Ÿ` (U+0178) → `Y` (U+0059)**. Every other diacritic passes
    byte-for-byte untouched (Beyoncé, Björk, Sigur Rós, Mötley Crüe, Motörhead unchanged). The map grows
    **one diagnosed pair at a time — never a heuristic detector.** **Explicitly rejected on the record:**
    (i) **NFKC** — does not even decompose `Ÿ`→`Y` (U+0178 has no compatibility decomposition), so it is
    *ineffective for this defect* while still firing invisibly elsewhere; (ii) **TR39 confusable-folding**
    — silently *false-merges* two genuinely distinct artists, damage that reads as a "complete"
    discography and is harder to detect than the split it replaces; (iii) **ASCII-strip** — manufactures
    new splits from the owner's own correctly-accented folders (Beyoncé→Beyonce), i.e. the exact bug T-037
    exists to kill.
  - **(b) Hyphen policy — fold to ASCII.** Fold the hyphen class **U+2010 (hyphen) and U+2011
    (non-breaking hyphen) → U+002D**, matching the owner's existing `Jay-Z/` (plain keyboard hyphen).
    Accepting MB's U+2010 lands fresh writes at the byte-distinct `JAY‑Z/`, undoing the completed one-time
    sweep on the next download. **En dash U+2013 and em dash U+2014 are explicitly excluded** — legitimate
    distinct punctuation, out of scope for this fold.
  - **(c) Placement — one shared helper at the two matched-metadata sites, mutating the value upstream of
    BOTH tag and path.** Path-only is rejected: Jellyfin groups its artist view by the embedded
    `artist`/`albumartist` *tag*, so a clean folder around a mangled tag re-splits on Jellyfin's side.
    T-308 adds a **`canonicalize_credit(match)`** helper in `server/app/import_seam.py` mirroring the
    proven, tested **`_with_title_suffix` (import_seam.py:1547)** — deep-copy `match.info` (a beets-cached
    `TrackInfo` shared across candidates; mutating in place leaks), fold the credit fields **`artist`,
    `albumartist`, and their `_credit` variants**, return a new `TrackMatch`. Per that helper's own
    docstring, beets applies `info.item_data` onto the item, so the single edit drives **both** the ID3
    write **and** the path template (`$albumartist` / `$artist`) — one edit, both effects. Wire it at the
    **two** sites that write an MB credit, *before* `session.run()` applies the match:
    **(1) `_accept` (import_seam.py:634)**, the shared tail of the fingerprint gate and the 2-of-3
    reconcile gate; **(2) `ResolveSession.choose_item` (import_seam.py:1520)**, which appends to
    `_accepted` directly and **bypasses `_accept`** — **T-308's binding note: it MUST route through the
    same helper**, or the resolve path silently keeps writing the stylised credit. **Not** a beets
    event-listener (the app registers **zero** today — `register_listener` grep is clean — so it is
    unproven machinery, and a write/move-time hook can fix the tag *after* the path is already computed,
    reintroducing the clean-tag/wrong-folder split). **Not** `KeepUntaggedSession` (import_seam.py:1597) —
    owner-typed intent, no MB match, the defect is byte-mechanically impossible there.
  - **(d) Symptom vs. root — the fold is binding; the root-hunt is a non-blocking probe.** They are
    complementary but not equal: the fold is the deliberate, root-*appropriate* fix at the last gate we
    control. A one-shot timeboxed probe — log the raw `match.info` credit codepoints on the next
    Jay-Z-class landing — may retire hypotheses or shrink the map, but **must NOT gate T-308, and the fold
    stays even if an upstream fix is ever located.** Observability is part of the decision: **emit one
    structured log line whenever the fold changes any codepoint**, so a fold that fires (or mis-fires) is
    never silent.
  - **Do NOT cite ADR-019 as precedent.** ADR-019's ASCII-fold is a *search-query* fold that affects
    MusicBrainz *ranking, not identity*. This is a *write-path* fold that **deliberately changes** the
    artist's canonical folder = its Jellyfin identity — the opposite direction. The two only look alike.
  - **Dissents preserved.** (1) *Shipping Pragmatist:* ship exactly the two diagnosed faults — the NFC
    floor and observability are insurance against unobserved futures; every glyph the fold touches is a
    chance to damage an identity. (Owner overrode: took the layered+observable reach; NFC is lossless and
    the cost is a few lines.) (2) *Listener camp (3 of 4 on mechanism):* a single event-listener would
    cover every session uniformly — their legitimate kernel (don't scatter divergent copies, don't miss
    the resolve path) is absorbed by the **one** shared helper wired at both matched sites; the standing
    risk is that T-308 verification must prove **both** `_accept` and `ResolveSession.choose_item` route
    through it. (3) *Maintainability:* a **near-duplicate-folder tripwire** (flag a freshly-landed artist
    folder that is a confusable/near-duplicate of an existing one the map did *not* repair) — **filed as a
    follow-on ticket, not binding on T-308**, else ADR-028 fixes Jay-Z and hides the next class exactly as
    T-037 was hidden.
  - **Rule statement (what T-308 implements, what a reviewer checks).** Before beets applies a matched
    `TrackInfo` — at `_accept` (:634) and `ResolveSession.choose_item` (:1520), on a deep-copied
    `match.info` via the one shared `canonicalize_credit` helper — normalise the credit fields (`artist`,
    `albumartist`, `_credit` variants) by (i) NFC-composing, (ii) mapping the enumerated confusable set
    (currently only `Ÿ`→`Y`), (iii) folding the hyphen class (U+2010, U+2011 → U+002D), leaving all other
    diacritics and en/em dashes untouched, and emit one structured log line when any codepoint changes.
    Verify: `JAŸ‐Z` → `JAY-Z`; `Beyoncé` / `Sigur Rós` pass byte-for-byte unchanged; decomposed
    `Beyonce`+U+0301 → precomposed `Beyoncé`; a log line fires only on the folding cases. (Owner-settled
    reach 2026-08-15: layered + observable.) [2026-08-15]

- **ADR-029 — Acquire intent is EXPLICIT (a payload field the backend honours), never silently inferred
  from URL shape; the control is a round detented selector — Single (default) / Playlist / Multi.** The
  R1/R2 accept path decides everything from the pasted URL's *shape* (`routes/jobs.py:63-77`,
  `download.is_playlist_url`/`names_one_song`): a `watch?v=X&list=PL…` — the address-bar copy of a song
  opened *inside* a playlist, the most common playlist-ish paste — falls through as **one song** and the
  playlist is **silently stripped** (`noplaylist=True`). The owner cannot say what they mean, and the app
  guesses "one song" on exactly the paste most likely to mean "the playlist." **Authored via a 5-agent
  design council (2026-08-16): 4 lenses — interaction/UX, industrial/visual, frontend+a11y, product/scope —
  + chair.**
  - **The load-bearing fix is the contract, not the control.** Acquire intent becomes an **optional
    `intent` enum on `POST /api/jobs`** (`single | playlist`; `multi` reserved, not wired). Present → the
    backend **honours the resolved choice** and stops re-deriving from shape for the ambiguous case; **absent
    → today's shape inference is the fallback, so R1 is byte-for-byte unchanged** and a single song stays
    `playlist_id = null`. Intent lives **only at the accept/expand front door — it must NOT leak into the
    pipeline**, or it breaks the single nullable-column switch that guarantees R1 non-regression (ADR-027).
    Without this field the control is cosmetic and the silent-strip survives behind prettier UI.
  - **The control (owner-picked form, 2026-08-16): a round detented SELECTOR, not a spin-pot.** A
    potentiometer is the idiom for a *continuous* sweep (gain/tone); intent is three *discrete, non-ordinal*
    states, which real gear selects with a detented one-of-N switch. So a click-stepped round dial (an **ARIA
    radiogroup**, arrow-key steppable — never `role=slider`, never arc-drag), rendered in the console skin
    (ADR-018): hard corners, cyan pip on the active stop, 1px seat-press. Owner explicitly wanted "a really
    cool dial to design"; the council honoured the instinct and steered only the spin→detent mechanism (a
    smooth knob for 3 named modes reads as hardware cosplay and has no clean keyboard/SR/touch path).
  - **Behaviour.** (1) **Single is the resting default every load** — *reset on load, never persisted across
    sessions* — so the walk-away flow is untouched; a bare `watch?v=` fires zero prompts. (2) An unambiguous
    paste may **inference-seed** the stop, but mode **never silently overrides unambiguous shape**. (3) **The
    dial IS the intent — there is NO inline confirm** (owner-decided 2026-08-16, superseding the council's
    proposed prompt). A `watch?v=X&list=PL…` paste on **Single** lands **just the song, no prompt**; a **quiet,
    non-blocking note** points to Playlist for discoverability ("Playlist attached — taking just this song;
    want all N? Turn the dial to Playlist"). To take the whole list the owner turns the dial to **Playlist**.
    Rationale: the visible mode already answers "which did you mean?", so asking again is redundant chrome, and
    the old silent-strip is no longer *silent* — the dial shows Single on screen. **Trade recorded:** a
    playlist-intended link pasted while the dial sits on Single yields one song; the remedy is the visible dial,
    and the note teaches it. (4) **Playlist** mode expands with no prompt; a bare single URL under Playlist
    lands as **one song** with the same quiet note, not a hard error (so a left-on Playlist can't over-expand a
    single paste). (5) **Multi ships present-but-inert** ("soon") now, reserving the geometry; its build
    (hand-assembled set → one ADR-027 batch, `youtube_playlist_id` null) is **backlog** (T-046).
  - **Dissent/safeguard preserved.** *Product-scope* warned any standing pre-commit control taxes the 99% flow
    and a left-on Playlist mode would silently expand the next single paste. Resolved: the selector is
    persistent (owner's control + Multi's only discoverability) **but** resets to Single each load and is
    inference-seeded; and each mode's single-URL behaviour is *land one song* (Single obviously; Playlist per
    (4)), so **neither footgun can fire** — the Single-strip is visible-not-silent, and Playlist can't
    over-expand a single. (The council proposed an inline confirm to neutralise these; the owner removed it as
    redundant given the visible dial — behaviour (3)/(4) carry the same guarantee without the prompt.) Runner-up
    shape (pure detect-and-confirm, no standing control) was rejected only because it strands Multi's discoverability.
  - **Scope.** **T-302** gains the `intent` field + one accept-path branch (small; kill the shape re-guess
    for the explicit case only). **T-310** grows by the dial screens (D1–D4: three resting stops, the
    song+list-on-Single quiet note, the Multi "soon" state — batch card untouched); design-gate screens signed
    off first (ADR-016). The full **Multi** input build is a separate backlog ticket (**T-046**). [2026-08-16]

- **ADR-030 — The acquire path serves THIN MusicBrainz candidates and hydrates only the recording that
  lands; a thin candidate must never reach disk un-hydrated.** (T-208.) Identifying one song fired ~11
  serialized MusicBrainz `recording/<id>` lookups behind MB's 1/sec limit — 80–90% of the identify gate and
  its entire variance (T-218). The waste had **two** independent sources that meet in
  `beets.autotag.match.tag_item`: chroma's `item_candidates` (one `track_for_id` per fingerprint id) and the
  MusicBrainz plugin's inherited `item_candidates` (one search, then a hydration per result). Both already
  hold everything scoring reads — `track_id/title/artist/length` — in a response they *already* fetched (the
  MB search response; the AcoustID lookup's `meta=recordings`), and throw it away to re-fetch each id. Both
  are patched (`app/mb_thin.py`, installed from `configure_beets()` after `load_plugins()`) to build a **thin
  `TrackInfo`** from the in-hand data instead. Auto-land: ~11 MB calls → **1** (the winner); the search and
  the AcoustID lookup are themselves untouched.
  - **Hydrate-at-accept is load-bearing, not an optimization detail.** A thin candidate carries only the
    scored fields; ISRC, genre, artist/work relations and the release ids cover art keys off exist only on a
    full `track_for_id`. So the ONE recording that lands is re-fetched at the single point both gates cross
    (`import_seam._ensure_full_match`, called from `_accept` **and** `ResolveSession.choose_item`, which
    bypasses `_accept`) **before** `canonicalize_credit` and any tag write. A thin winner that landed
    un-hydrated would write a four-field file — no error, green suite, and *intermittent* (the surviving
    candidate is thin-or-full nondeterministically under beets' plugin ThreadPool). A hydration miss **parks**
    (resolve **raises**); it never lands thin. Do not "simplify" this guard away — that reintroduces the exact
    silent-degradation this ADR exists to forbid, and it is the reason hydration lives at accept, not inside
    `match_for_recording`. Marked by a `cm_thin` field on the `TrackInfo`; a per-track cache
    (`_cached_track_for_id`) collapses the same-MBID-twice repeat T-218 found.
  - **Parity is the correctness contract.** A thin row's `title`/`artist`/`length` must equal what full
    hydration produces — they feed `track_distance` (candidate order, the persisted score) and the reconcile
    LLM's evidence. Titles/artists are built with the MB plugin's **own** helpers
    (`_key_with_preferred_alias`, `_parse_artist_credits`), with a guarded hand-join fallback for the lighter
    fields a search row can omit; `length` stays `None` when absent, never 0.0 (a wrong length corrupts
    ranking worse than a missing one). The chroma path **forks** `acoustid_match` to capture the metadata
    stock discards — pinned byte-for-byte to beets 2.12.0 by a source-hash drift guard
    (`STOCK_ACOUSTID_MATCH_SHA256`, `test_mb_thin.py`) so a beets upgrade forces a re-review, not a silent
    divergence.
  - **Park serves the top 3, never the full fan-out; the ISRC row is never capped out.** T-218 showed
    weak-match guesses are often wrong (the real answer off the list — the owner re-searches), so persisting a
    full candidate list is waste. `_cap_park_rows` keeps the top `PARK_CANDIDATE_LIMIT` (3) of the ranked
    list, force-keeping the ADR-021 ISRC-correction candidate if the ranking pushed it past the cap;
    re-search (`POST /api/reviews/{id}/search`) is the real fallback. Park-time **re-hydration of the 3 was
    deliberately NOT added** — thin rows already carry title/artist for the live card, `GET /api/reviews`
    re-hydrates on load, and adding 3 MB calls per park would re-introduce the fan-out cost this ticket
    removes. Resolve still lands full via `_ensure_full_match`.
  - **Acceptance was a measured compare, owner-relaxed from byte-identical (2026-08-23).** The gate is a
    per-song land/park + tag + timing side-by-side of the new engine vs the current one over the spike corpus,
    with per-song differences surfaced for owner judgement — not a zero-diff assertion (single-user tool; the
    owner reviews landings, and this also captures the timing win). **Deferred fold-ins:** the fpcalc
    de-dupe (reuse chroma's cached fingerprint — orthogonal, touches the score-critical dominance sense, held
    out so score drift in the compare is attributable only to candidate parity) and the inert `cache_control`
    reconcile-prompt tweak (verified a no-op on Haiku 4.5: 4096-token cache minimum vs a ~1.1k per-track
    prompt — the ADR-011 failure mode; dropped, not built). Local MB mirror (removes the limit entirely) stays
    R3. [2026-08-23]

- **ADR-031 — The MusicBrainz retry ladder is bounded to one retry; the identify tail is beets' retry
  backoff, not an uncapped socket.** (T-210.) After ADR-030 killed the MB call *count* (~11 → 1–2), the
  remaining time cost was the *latency tail*: a single `get_recording`/`track_for_id` could still spike
  18–34s (once 98s). The premise T-210 was filed on — an uncapped fetch needing a timeout — was wrong: beets'
  `TimeoutAndRetrySession.request` already sets `timeout=10` per request. The tail is the **retry ladder**.
  That session mounts a `RateLimitAdapter` carrying `Retry(total=6, backoff_factor=0.5,
  status_forcelist=[500,502,503,504,429])`; on a slow/flaky MB endpoint that is up to six attempts with
  exponential backoff (~0.5 → 16s, summing past 30s), and each attempt can itself burn the 10s socket
  timeout. `app/mb_retry.install_bounded_mb_retries()` (installed from `configure_beets()` after
  `load_plugins()`, beside the ADR-030 patches) re-stamps the adapter's `max_retries` in place via
  `Retry.new(total=1)` — **only the count changes**; the backoff factor, the 5xx/429 status list, the 0.25s
  adapter spacing, and the session-level 1/sec limiter are all preserved. One retry keeps a single absorb for
  a genuine transient 5xx while collapsing the deep backoff tail: the common 503-storm spike (~30s of pure
  backoff sleep across six attempts) is gone, and only a rare genuinely-hung endpoint still costs ~two socket
  timeouts (~20s) rather than the ~30s+ ladder. `total=1` (not `0`) is deliberate — it keeps one transient
  absorb; the residual cost of that choice is finding-#1 below.
  - **Degradation-to-miss is inherited, not added.** After a bounded ladder exhausts, beets *raises*. Both
    hot-path callers already turn that into a clean miss: `_stamp_original_year` wraps `fetch_original_date`
    and lands the track without a year (ADR-014 tolerates a blank year), and beets'
    `maybe_handle_plugin_error` turns a raising `track_for_id` into `None` (we never set `raise_on_error`, so
    the default guard is live) → a dropped hydration, which ADR-030's hydrate-at-accept **parks**, never lands
    thin. So a shorter ladder never crashes and never stalls the batch — it just reaches the existing miss
    faster. The candidate *search* was always exception-capable; bounding retries changes *when* it gives up,
    not *that* it can.
  - **This caps the tail; it does not lower the median.** A slow-but-successful MB call is unaffected (capped
    at the existing 10s socket timeout, as before). The win is predictability — no more one track blowing up a
    batch — not a faster typical track; the steady per-track floor (transcode + LLM + senses) is T-219/T-035's
    ground, not this one.
  - **The one non-latency effect (accepted).** Bounding 6 → 1 is not *purely* tail-capping: a transient
    5xx/429 or reset that the six-deep ladder would have ridden out on attempt 2–6 now exhausts after one
    retry, so a lookup that previously recovered can miss. It degrades exactly as above — a blank year or a
    parked (re-searchable) track, **never a wrong tag or a crash** — so the failure mode is recoverable, and at
    single-user volume MB is almost always healthy (the T-203 spike never tripped its limiter). We keep the one
    absorb (`total=1`, not `0`) precisely to ride out the single-blip case; the residual is the rare
    multi-failure-then-success sequence. Worth it for the tail cap. The other half of T-210 — a single shared rate limiter across `isrc.py` and beets
    (the Pa Salieu double-hit correctness concern) — is **orthogonal and stays open**; this decision is the
    speed half only. Local MB mirror (removes the limit and the retries entirely) stays R3. [2026-08-25]

- **ADR-032 — A corroborated fingerprint auto-lands without the reconcile LLM; fp + yt agreement IS the
  2-of-3 bar, re-derived in code.** (T-219.) After ADR-030/031 killed the MusicBrainz call count and capped
  its latency tail, the reconcile LLM became the largest *steady* per-track cost — ~3–6s on **every** track
  (T-218: ~3.5s/call, rock-stable). The muziktest head-to-head (T-218) showed its Confidence gate skips the
  AI entirely on the corroborated majority (8 of 12 matched tracks fast-pathed). Ported here as
  `FingerprintTrustSession._corroboration_fast_path`, run in `choose_item` **before** `_reconcile`: when the
  fingerprint is dominant (score ≥ `score_min`, gap ≥ `gap_min`) and its winning recording is a beets
  candidate (`fp` supports) **and** the YouTube source signals corroborate that candidate on artist AND title
  (`yt` supports, via `normalize.loose_match`), the track lands through the shared `_accept` tail with **no
  Shazam call, no ISRC lookup, and no LLM call**. Everything weaker falls through to the full gate unchanged.
  - **Why this is safe, not a shortcut.** The 2-of-3 rule (ADR/T-205, the safety spine) lands on **two
    present senses agreeing**, re-derived in code — never the LLM's self-report. The fast-path computes fp+yt
    in exactly the terms `_agreeing_senses` uses (recording-MBID identity for `fp`; loose artist+title
    containment for `yt`), so a track it lands is one the gate would also have found two senses for. It is
    **additive**: it only ever *skips* the LLM on a strong+corroborated match, and it can only *land* (never
    park differently) — a `None` return falls straight through. The Pa Salieu marquee case (fp dominant on the
    **wrong** recording, yt dissents) does not corroborate, so it still goes to the LLM. This does **not**
    reintroduce the "trust fp when dominant" shortcut ADR-030's *Not* section forbids: dominance alone never
    fast-paths — the source title must independently agree.
  - **What genuinely changes (accepted).** The fast-path drops the LLM from the corroborated path, which
    removes two LLM behaviours *for that path only*: (i) its **veto** — the LLM can no longer park a
    strong+corroborated match on a judgment-only signal (album/year mismatch); (ii) its **override** — where
    the audio is a remaster (fp → recording X) but Shazam→ISRC resolves the *original* recording Y of the same
    song, the LLM might have landed Y, whereas the fast-path lands X. Both are accepted: a ≥0.90 fingerprint
    identifies the **actual audio bytes** (T-008: every correct match measured ≥0.955, every non-match 0.0),
    so landing the fingerprint's own recording is the faithful identity, and the original *year* is stamped
    independently by `_stamp_original_year` (ADR-014) regardless of which recording landed. The corroboration
    requirement (yt must agree) is what makes "trust the fingerprint" safe here where dominance alone is not.
  - **Acceptance is the ADR-030 measured compare, owner-adjudicated.** Engine-touching (it changes the land
    decision path), so the bar is the same per-song land/park + tag + timing side-by-side over the spike
    corpus, differences surfaced for owner judgement — expected result: land/park and tags unchanged **except**
    corroborated tracks that now land without the LLM (and any remaster-vs-original recording-MBID shift per
    the point above, which the owner adjudicates). Unit-level additivity is proved by the fall-through tests
    (`test_fast_path_falls_through_*`) and the no-LLM land test (`test_fast_path_dominant_fp_and_yt_agree_lands_without_llm`).
    T-035 (Shazam fallback tier) is the orthogonal coverage sibling, unaffected. [2026-08-25]
  - **AMENDED by T-222 (ADR-033), 2026-08-26 — the fast-path now gathers Shazam.** The "no Shazam call"
    above was the T-219 latency win *before* Shazam became the tag/art source of record. T-220/ADR-033 needs
    the Shazam record in hand on the corroborated majority (it is where tags + the correct cover come from),
    so `choose_item` now runs the **cheap Shazam recognition on every track** (restoring ADR-024's letter).
    **What the fast-path still skips is the *expensive* part** — the ISRC resolve and the LLM adjudication —
    so the veto/override trade above stands exactly as written; only the recognition (a ~1–2s subprocess) is
    added back. The land *decision* is unchanged (still fp+yt, no Verdict). Owner-approved on the T-222 build,
    2026-08-26. [amended 2026-08-26]

- **ADR-033 — Shazam is the tag + art source of record; retire beets from tag-writing (mutagen writes);
  MusicBrainz kept only as a thin, rare AcoustID-only fallback. Reverses ADR-005; supersedes the R1.5
  "art/lyrics land via the beets path" rule (ADR-024 note / spec §3). Does NOT touch the identification
  gate.** — **Owner ratified 2026-08-26.** Epic [`T-220`](../backlog/T-220.md).

  The engine already identifies with three senses (yt-dlp title / AcoustID / Shazam) and a 2-of-3 vote
  (ADR-021 amendment, T-205), already runs Shazam on every track (ADR-024, T-202), and already fetches
  Shazam's tags **and** its `coverarthq` URL every track — then discards them, re-deriving tags through
  MusicBrainz hydration (`_ensure_full_match` → `get_recording`, T-208) and art through `fetchart` / the
  Cover Art Archive (spec §3). That re-derivation is the acquire path's dominant latency and its entire
  MusicBrainz-outage exposure, and the release-picking in `fetchart` is the wrong-cover class (the
  *Greatest Hits* cover on a *Trouble Man* soundtrack track, T-218 head-to-head — measured while Shazam
  already held the correct soundtrack cover URL). This ADR changes only the land tail (`_accept`): the
  **source** of the tags and cover that get written, and what writes them. The senses, the 2-of-3 gate,
  the LLM adjudicator, and the T-219 fast-path are unchanged.

  **The decisions:**
  1. **Tags + art come from the accepted identity, not a re-lookup.** When the landed identity is
     Shazam-corroborated (Shazam among the ≥2 agreeing senses), its artist / title / album / year / genre
     come from the Shazam record already in hand, and its cover from Shazam's `art_url` (→ YouTube
     thumbnail, centre-cropped, when absent). No MusicBrainz hydration, no `fetchart`.
  2. **AcoustID-only case keeps exactly one thin MusicBrainz call (owner option 1, 2026-08-26).** When
     Shazam missed but AcoustID + the title still corroborate, one `get_recording` by the AcoustID
     recording MBID supplies tags + art — **no fan-out** (the T-208 discipline), fail-soft to
     provisional/review, never blocking. ~99% of tracks (Shazam hits) never touch MusicBrainz, so its
     outage no longer stalls acquisition; AcoustID's unique coverage (Tower of Power, Ryder × Skepta) is
     preserved. MusicBrainz is retained as a rare non-fan-out fallback, **not deleted** — "off the critical
     path," not "gone."
  3. **beets is retired from tag-writing (reverses ADR-005).** Matching already lives in the senses; with
     tag-writing moved to a mutagen ID3/MP3-320 writer, beets and its `musicbrainz` / `chroma` /
     `fetchart` / `embedart` plugins have no remaining job. The AcoustID rescue sense moves to the
     `acoustid` library directly; the one AcoustID-only `get_recording` uses `musicbrainzngs` directly —
     so no beets survives. ADR-005's rationale ("plugins are more capable") is spent: we are no longer
     matching in beets, and we deliberately want *fewer* capabilities on the write path, not more.
  4. **Write what Shazam supplies free; never a standalone fetcher for a field.** artist / album / title /
     cover always; year + genre when the Shazam response carries them; lyrics best-effort when clean. No
     MusicBrainz year lookup, no Last.fm call, no lyrics-plugin fetch.
  5. **Genre auto-writes from Shazam; ADR-023's LLM-enum genre is deferred to the polish pass.** ADR-023
     (LLM-authored genre against a curated enum) was ratified 2026-08-09 but **never built** — genre today
     comes from the `lastgenre` / Last.fm plugin (`beets_engine.py` PLUGINS), which this epic removes. The
     reconcile LLM (ADR-021) runs **only on conflict tracks** and authors *identity*, not genre, so it
     cannot supply genre on the corroborated majority (the T-219 fast-path skips it entirely). Therefore
     genre now auto-writes from **Shazam's genre** whenever the Shazam response carries it (free, every
     Shazam hit, happy path included); a track Shazam does not cover gets no auto genre. ADR-023 is **not
     repealed** — its LLM curated-enum genre is re-homed to the deferred owner polish pass (R2.5
     clean-work), where a subjective curated genre belongs and may override Shazam's coarse default.

  **What stays binding / untouched:** the three-sense 2-of-3 gate and "Shazam never lands alone"
  (ADR-021); Shazam-every-track + the subprocess quarantine (ADR-024); the T-219 corroboration fast-path
  (ADR-032); serial land, pool = 1 (ADR-022); MP3-320 output (the writer is mutagen's ID3 path — codec
  reconsideration is the separate T-225, not this ADR).

  **Safety:** corroboration — not raw sense confidence — authorises trusting Shazam's tags, the same
  argument ADR-032 made for the fingerprint. A Shazam record is written as tags only when Shazam is among
  the ≥2 agreeing senses; the Frank Ocean / Coldplay cover (Shazam says *Coldplay*, the title says *Frank
  Ocean* → disagreement → park) is safe exactly as today. Rationale + evidence: T-218 head-to-head report,
  [`T-220`](../backlog/T-220.md). **Acceptance:** the ADR-030/032 measured compare — engine-touching, so
  the corpus land/park + tag + timing side-by-side, owner-adjudicated; expected result is materially
  faster, artwork correct on landed tracks, identification outcomes unchanged modulo the accepted
  tag-source change. (Owner ratified 2026-08-26 on the T-220 spec gate.) [2026-08-26]

  - **Build note (T-222, 2026-08-26): a premise correction, owner-approved.** This ADR's preamble assumed
    Shazam "already runs on every track", but T-219 (ADR-032) had stopped gathering it on the corroborated
    majority (the fast-path returned before `_reconcile`). Since decisions 1 + 5 need the Shazam record in
    hand *there*, T-222 restores Shazam-every-track: `choose_item` gathers the record once, up front, reused
    by the fast-path, the degrade gate, and the reconcile evidence. The **land decision is still unchanged**
    (fp+yt, no Verdict) and the fast-path still skips the expensive ISRC + LLM steps — only the cheap
    recognition returns to the fast-path (ADR-032 amended to match). So "the T-219 fast-path is unchanged"
    above should read: *its land decision and its skip of the LLM are unchanged; its Shazam gather is
    restored*. [2026-08-26]
