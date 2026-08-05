# R1.1 Tickets — Review Inbox

> **Status: GENERATED — 2026-07-23, from `r1.1/spec.md` (design gates signed off).** Decompose the
> R1.1 remediation slice into build-order tickets. Each ties back to a §8 acceptance item. Same ticket
> format and Definition of Done as `docs/r1/tickets.md` — don't restate them; read that header.
> Numbering is the **T-1xx** series to avoid collision with R1's T-0xx.

**Scope guard (roadmap rule).** R1.1's scope is its §8 exit criteria. Findings surfaced while building
are captured as tickets and triaged at birth — required for §8 → here; else → `docs/backlog/`. Don't
let the migrate/playlist story (R2) or candidate-art (deferred, ADR-010) creep in.

**Build order.** Backend correctness (T-104) is disjoint from the client and can land first or in
parallel. The client keystone is **T-101** (surface the queue); **T-102** (lift the lifecycle) depends
on it; **T-103** (no-candidate exits) depends on both; **T-105** (reskin) skins the finished structure,
so it goes last. T-101 ∥ T-104 is a clean fan-out (disjoint file sets: `client/` vs `server/`).
**T-106** (durable staging) is server-internal and independent of the client chain — the owner sequenced
it **next** (2026-07-25), and T-103's re-search exit is built on top of it, so it lands before T-103.

---

### T-101 — Review inbox: client consumes `GET /api/reviews` on cold load
- **Status:** **DONE + VERIFIED LIVE** (merged `700df62`; browser `/verify` 2026-07-24). The cold-load
  hydration was proven end-to-end: 7 reviews durably parked on the real backend (`:8137`), served through
  the Vite proxy, all 7 rendered by the **Needs-review** inbox on a fresh load with no live card, Review
  buttons correctly disabled (resolving-from-cold is T-102). Headless half confirmed earlier same session
  (`GET /api/reviews` returns the durable queue after a restart). *Trap paid for:* a stale Vite dev server
  served a pre-merge `App.tsx` and nearly booked a false FAIL → `docs/learnings.md` (2026-07-24).
- **Depends on:** none (backend `GET /api/reviews` exists — T-014). 
- **Agent:** front-end
- **What:** Add a top-level **Needs-review inbox** to `App.tsx`, loaded from `GET /api/reviews` on
  mount and rendered independent of any live `TrackCard`. One row per parked review (title/query, a
  weak-match vs keep-which tag, a Review action). Empty → the resting state. Append a row live off the
  `track.review_required` SSE event; remove on resolve. This is the keystone — it makes parked reviews
  reachable on a fresh load, closing the §7 gap that R1 shipped.
- **Done when:** a review parked in a previous session (or surviving a backend restart) appears in the
  inbox on cold load, with no live card present. Ties to §8 items 1 + the reachability of 2/3/4.

### T-102 — Lift the review lifecycle out of `TrackCard`; hand off to the inbox
- **Status:** todo
- **Depends on:** T-101
- **Agent:** front-end
- **What:** A card entering `review_required` stops hosting `ReviewPanel`; it renders the one-line
  *"→ moved to review"* hand-off and the **inbox** takes ownership. Re-home `ReviewPanel` (and its
  `GET /api/reviews/{id}` re-hydration, the duplicate keep-which fetch, the T-029 re-park path) into the
  inbox row. Collapse the `TrackCard` state machine accordingly — this is the tech-debt paydown the
  board flagged ("one component runs the whole job state machine"). Keep the pipeline rail + landing
  detail; remove only the review-hosting branches.
- **Done when:** a card that parks hands off and the review is fully resolvable **from the inbox after
  the card unmounts** (reload mid-review, resolve from the inbox). Ties to §8 item 5.

### T-103 — No-candidate park exits (fix the 8b dead-end)
- **Status:** **DONE — both exits on `main`.** Slice A (re-search) merged `ff7338a` 2026-07-30,
  browser-verified via Playwright. Slice B (keep-untagged) merged `3198cfe` 2026-07-31. Suites:
  432 server, 55 client. Verified end-to-end over HTTP: Frank Ocean fixture landed via keep-untagged
  as `Frank Ocean/Strawberry Swing.1.mp3` (artist+title only, no MBID, no art — the honest trade-off).
  Frank Ocean fixture **consumed** (was deliberately parked since 2026-07-27; now landed twice — once
  via re-search with full MB tags, once via keep-untagged with owner tags only).
  - **What landed in slice A.** `_validate_weak_match` relaxed per ADR-020 consequence 1 — membership in
    `candidate_ids` is no longer required, replaced by an MBID *shape* check, with listed candidates
    still accepted whatever their shape. New `app/mb_search.py` + `POST /api/reviews/{id}/search`
    (stateless read: stores nothing, leaves the row `pending`, repeatable). New `guess` field on
    **both** transports — the hydrated row and the `track.review_required` SSE frame — feeding the
    form's pre-fill. Client: the re-search form, swap, new-results list, and the empty state.
  - **`/verify` — done for the engine and the route, NOT for the browser.** Both fixtures re-searched
    over HTTP against the running `:8137`: Frank Ocean's known-correct `908e389b…` comes back **first at
    0.889** (it was absent from the parked list entirely), and Nines' `f5d1bcfb…` is present at 0.757.
    Then the full **park → re-search → resolve → land** was driven on a **copy** of the fixture audio
    into an **isolated** temp DB + temp beets library: landed `Frank Ocean/Strawberry Swing.mp3`, MP3
    **320 kbps**, `mb_trackid` = the re-searched recording, cover art embedded (426 KB), genre Soul,
    year 2011. The fixtures were deliberately **not** consumed — both are still parked.
  - **Review pass done 2026-07-30** (four parallel reviewers: reuse / simplification / efficiency /
    altitude). Two findings were defects, not polish, and both are fixed:
    - **27 s per search → 0.3–1.0 s.** Rows are now built from the single MusicBrainz search response;
      the per-id `tracks_for_ids` hydration is gone. It was 26 serialised requests through beets'
      1.0 req/s limiter — the *same* limiter the acquire pipeline uses, so a re-search also starved a
      running import for the duration. Ranking is unchanged (Frank Ocean 0.889 first, Coldplay 0.610).
    - **The owner's corrected terms were being discarded.** They lived in the re-search form; a
      successful search collapsed it, and re-opening remounted it and re-seeded from `guess`. Terms now
      live in `WeakMatchPanel`, with a regression test. This is the mainline path per the amendment
      below, not an edge case.
    - Also applied: shared `_pending_review` 404/409 preamble, `postJson` in `api.ts`, one shared
      `.review__field`/`.review__input` CSS pair, flattened `_validate_weak_match`, `guess_terms` guard,
      derived `searchOpen`. Four learnings filed. Suites: **421 server, 53 client**, green.
  - **Still open before this is done:** (1) the browser half — the form, swap, empty state and
    `EventSource` behaviour through the Vite proxy need the owner at `:5173`; (2) merge to `main`;
    (3) slice B, keep-untagged, whose entry point must change per the **ADR-020 amendment** (an empty
    result is not how "not in MusicBrainz" presents — see below).
  - **Design was signed off 2026-07-29** on the six flat screens in
    `docs/r1.1/design/review-rescue-flow.html`; ADR-016 gate passed; ratified as ADR-020. *Sign-off
    hazard worth knowing:* the owner's first read was **truncated** by OneDrive and showed neither
    screen 05 nor 06 — serve design artifacts over HTTP for review (`docs/learnings.md`, 2026-07-29).
  - **Screen 04's premise was measured wrong and the ADR is amended.** "MusicBrainz doesn't have this
    one" is drawn for an empty result; MusicBrainz text search almost never returns zero (a nonsense
    query returned 25 rows). The real dead-end shape is *many results, all wrong*. Keep-untagged
    therefore cannot be gated on an empty list — ADR-020 amendment + `docs/learnings.md`.
- **Was:** todo — **design explored 2026-07-25 (draft, not gated yet).** This ticket widened from
  "empty candidates" to the general *"candidates can't resolve this → give me another exit"* vertebra,
  because a wrong-but-present candidate set (the Nipsey reversed-title case) is the same dead-end. Two
  first-class exits emerged, drawn as flat screens in **`docs/r1.1/design/review-rescue-flow.html`**
  (6 states) for the ADR-016 gate: **(1) Re-search** — owner types the corrected artist/title, the app
  re-queries MusicBrainz in-app and repopulates candidates (the everyday gesture); **(2) Keep-untagged**
  — land the file with owner-supplied tags, *no* MB match, honest trade-off shown (no cover art /
  auto-genre, since those need a match). Reject stays required. Paste-an-MBID demoted to a quiet
  "advanced" affordance. **Engine finding:** `resolve_import` / `_forced_match` (`import_seam.py`)
  already lands an arbitrary recording; the main block is relaxing `_validate_weak_match`
  (`reviews.py`). Keep-untagged is the bigger lift (land-without-match machinery). **Cross-ref:** the
  Shazam spike (**backlog T-035**) may auto-rescue many of these upstream — it changes *how often* the
  manual exit is hit, not *whether* it's needed. Sign-off + the ADR were left pending the owner's call.
- **Live proof case, with a known-correct answer (2026-07-27).** The one review left in the owner's
  queue — **Frank Ocean — Strawberry Swing** (`297ec8fe…`, audio healthy under the new durable root) —
  is this ticket's dead-end in its purest form: **5 candidates, none of them right**, top match
  *Strawberry Swing — Coldplay* at 0.52 (his version is a cover of Coldplay's 2008 original, so the
  title collides while the recording differs). It cannot be resolved correctly today, and rejecting it
  throws away good audio.
  **The correct answer exists in MusicBrainz and is not in the candidate list:**
  `Strawberry Swing — Frank Ocean`, *nostalgia,ULTRA.* (2011-02-16), recording MBID
  **`908e389b-256c-4f6a-9d75-0e0a81815444`**, returned at **score 100** for
  `recording:"Strawberry Swing" AND artist:"Frank Ocean"`.
  That makes this row a **regression fixture rather than a nuisance**: it is a real parked review with
  an independently-known expected outcome, so re-search can be judged against a fact rather than a
  vibe. **Done-when for the re-search exit should be demonstrated on this row** — type the corrected
  artist/title, and the candidate list must come back containing that MBID. Deliberately left parked
  for that purpose (2026-07-27); do **not** clear it, and do **not** resolve it to the Coldplay
  candidate, which would file the owner's audio under the wrong artist and burn the fixture.
- **Depends on:** T-101, T-102
- **Agent:** front-end + build (backend resolve path)
- **What:** A review with **empty candidates** must render working exits, never a dead panel. **Reject**
  (discard + delete staging) is **required**. **Keep-untagged** (land the file as-is under a fallback
  path, no MB tags) **only if cheap** — first decide whether the existing `resolve` body shapes cover a
  no-candidate reject or a third shape/route is needed (spec §6); if keep-untagged needs real
  land-without-tag machinery, ship reject-only and defer keep-untagged to a backlog ticket. **Don't
  pre-commit the mechanism — design it in this ticket.**
- **Done when:** the 2026-07-23 dead-end is gone — a no-candidate park offers at least a working reject,
  driven through the real stack and watched (`/verify`, browser). Ties to §8 item 4.

### T-104 — Boot reconciliation: job/review agreement (from backlog T-033)
- **Status:** **DONE + VERIFIED LIVE** (merged `90d5854`; `/verify` 2026-07-24). One transactional
  `reconcile_orphans_on_boot()` (reviews first, then jobs owning a pending review → `review`, then
  remaining orphans → `error`) replaces the two disagreeing sweeps. Driven through the real ASGI socket on
  an isolated temp DB seeded with all five orphan shapes: mid-resolve crash (job=running + review=resolving)
  and submit-resolve-then-restart (job=running + review=pending) both settle to `review` **agreeing** with
  their `pending` review (`last_error` cleared, T-029 finding #3); bare running/queued orphans → `error`;
  a durable `review`+`pending` pair untouched; a second boot reconciles `(0,0,0)` (idempotent).
- **Depends on:** none (server-internal; disjoint from the client tickets — fan out with T-101).
- **Agent:** build
- **What:** The two boot sweeps in `JobWorker.start` (`server/app/jobs.py`) don't coordinate:
  `fail_unfinished_jobs()` errors every `running` job while `reset_resolving_reviews()` re-`pending`s
  its review, so a restart mid-resolve yields `job=error` **and** `review=pending` — the exact
  job/review disagreement **T-029** fixed on the live door, recreated through the boot door. Mirror
  `_repark_after_release`: reconcile reviews first, then fail only jobs with **no** pending review (a
  job whose reset review points back at it settles to `review`, not `error`). Add a boot-path test
  driving both sweeps against a `running`-job + `resolving`-review pair (none exists —
  `test_worker_start_fails_orphaned_jobs` uses a bare running job). The inbox (T-101) already makes the
  orphan *reachable*; this makes the state *correct* so a reconnecting card doesn't show a dead error
  over a live review.
- **Done when:** a restart with an in-flight resolve leaves `job` and `review` in agreement (job settles
  to `review`, the card recovers the panel), covered by the two-sweep test. Ties to §8 item 6.
  *(Full finding + evidence: this ticket supersedes `docs/backlog/T-033.md`, git-removed on filing.)*

### T-105 — Console reskin (crest logo, EQ beat bars, art where real)
- **Status:** **BUILT, close-out in progress (2026-08-05).** The reskin grew past the approved gate:
  on seeing the ported Signal Path live the owner judged it templated and, with taste-skill + two
  `claude-fable` passes, redesigned it into a **broadcast-console** skin — big centred crest, segmented-
  LED meter rail, **36-bar EQ beat animation** replacing the ambient line. Committed `11b6302`; the
  high-effort `/code-review` follow-up (`819f22c`) fixed three UI-truth regressions (fabricated dup
  swatch, channel-name-as-artist, dropped expanded-row highlight) and deferred a perf nit to `T-041`.
  The direction supersedes the gate and is ratified in the **ADR-018 amendment (2026-08-04)**; the EQ
  bars deliberately reverse the old "no spectrum bars" clause. **Remaining:** merge to `main` (§DoD 5);
  the one un-browser-verified fix (#1, the dup panel) awaits a duplicate paste. Earlier: design gate
  passed 2026-08-03 (crest Rev C + Signal Path palette), since superseded.
- **Depends on:** T-101, T-102 (skin the finished structure, not a moving target)
- **Agent:** front-end
- **What:** Replace the current tokens with the **Signal Path** palette (dark-native, cyan `#3fb6d8`
  accent, Plex Sans + Plex Mono — inline the faces as data URIs, no CDN). **OutKast-style crest logo**
  (wide badge with 3D crown, CLEAN/MUZIK in block letter paths — `docs/r1/design/crest-logo.html`).
  The segmented-meter rail. **One** ambient signal line in the background at ~7% opacity, frozen under
  `prefers-reduced-motion` — **no spectrum bars**. Cover art on landed tracks + the owned side of a
  duplicate; the picker stays text+score (ADR-010). Cursor-tracked hover glow on cards/buttons
  (disabled under reduced-motion). Design gate screens in `docs/r1/design/t105-design-gate.html`.
  This is **ADR-018**.
- **Done when:** the app renders in the **Console** skin (ADR-018 as amended) — centred crest, EQ beat
  bars, art where it genuinely exists, hover glow — light/dark both legible, reduced-motion honoured.
  Ties to §8 item 7.

### T-106 — Parked audio lives in `/tmp` and gets reaped (from backlog T-036)
- **Status:** **DONE + VERIFIED (2026-08-05).** Integrated on `main` 2026-07-27 (`eb5865e`); the
  last gate — the end-to-end `/verify` — passed 2026-08-05 once T-103 unblocked route-resolve.
  394 tests green on `main`. **All four items landed and were observed:**
  - **The reboot half is now PROVEN on the owner's real machine (2026-07-28).** WSL booted 08:52;
    the Frank Ocean staging file (`WgPXj2fEiW8.mp3`, 9.4 MB) was written 2026-07-27 08:56 and was
    still on disk after the boot. A WSL restart is exactly what reaped the original nine `/tmp` dirs,
    so this is the bug's own failure mode, survived — observed rather than argued, and it required no
    setup. This is the substance of the ticket.
  - **The resolve half cannot be demonstrated until T-103 lands.** Four downloads on 2026-07-28
    failed to produce a *resolvable* park: two auto-tagged past the queue (AcoustID had them), one
    parked with five wrong candidates (Nines *Outro (Official Audio)* — the correct
    `f5d1bcfb-f66e-400a-948a-e7f9127160de` is at MB score 100 and was not among them), and the
    duplicate branch turned out to be unreachable (see `learnings.md` 2026-07-28: it parks only on a
    strictly-higher bitrate, and everything this app lands is already MP3 320). `_validate_weak_match`
    (`reviews.py:168`) refuses any recording that isn't already a candidate, so the gate structurally
    requires T-103's re-search. **Owner decision 2026-07-28: fold this gate into T-103's `/verify`** —
    one run proves both, and T-106 stays *built* until then rather than being called done on evidence
    that doesn't exist. The 2026-07-25 note already said this ("the through-the-UI half of this ticket
    cannot be shown until T-103 lands"); it was filed as a caveat and should have been on the status
    line.
  - **Two incidental confirmations from the same session.** Reject cleans up its own staging dir (the
    `7fbde7f` fix, observed). The beets library DB survived the data-dir move intact — 8 items, all
    with `mb_trackid` — so the move cost no library memory.
  - **Item 1+2.** Staging is durable and lives at `/home/armand/cleanmuzik-data/staging` — the
    **Linux filesystem, not `server/data/`**. That path is inside the OneDrive-synced repo tree, so the
    original wording would have swapped the OS reaper for a sync engine (uploads of every download;
    Files On-Demand able to dehydrate a parked MP3 into a placeholder WSL can't open *while `isfile`
    still answers True*; sync handles making `rmtree` fail silently). Owner decision 2026-07-27.
    `DB_PATH` places the whole data dir — the beets library DB derives from the same parent — so the
    "derived, not configured" correction below still holds; there is still no separate staging setting.
    Documented in `.env.example`; rationale in `docs/learnings.md`.
  - **Item 4.** The Frank Ocean review was migrated to the new root with its row repointed, then the
    9 dead rows were deleted **selectively by file-existence**. Inbox is now 1 review,
    `staging_missing: false`, 5 candidates. DB backed up before the surgery.
  - **The sweep, observed.** A genuine restart with a planted decoy logged `swept 1 orphaned staging
    dir(s) on startup`, removed it, and left both the claimed dir and a foreign non-prefixed dir alone.
  **A high-effort `/code-review` found 10 issues; the 8 code ones are fixed in `7fbde7f`** — reject and
  transcode now clean up after themselves, the sweep logs its failures and is opt-in to the process
  that owns the data dir, it runs off the event loop, the unreachable stat warning is reachable, and
  two sweep tests that passed under mutation were replaced with mutation-proved ones.
  **The last gate — PASSED (2026-08-05).** The full chain was driven end-to-end through the HTTP
  routes against **two isolated `uvicorn` processes** (temp `DB_PATH` + `LIBRARY_DIRECTORY` patched
  in **both** `beets_engine` and `import_seam` — the constant is copied by value, so a single patch
  would still land in the real library; real library confirmed untouched, `-mmin -15` empty):
  Nines "Franklin" (`D5QjfJao9FQ`) real download → parked (`rec:none`, 5 wrong candidates, correct
  `f5d1bcfb…` off-list) → **killed the process and relaunched** → boot logged `swept 1 orphaned
  staging dir(s) on startup` (a planted decoy reaped; the parked file **and** a foreign non-prefixed
  dir survived) → `POST /reviews/{id}/search {Nines/Outro}` surfaced `f5d1bcfb…` → `POST
  /reviews/{id}/resolve` onto it → landed `Nines/Outro.mp3`, **MP3 320 kbps**, `mb_trackid=f5d1bcfb…`,
  genre Hip Hop, year 2017, **165 KB embedded art**, staging removed on resolve (retention ends,
  spec §5). A **third** restart confirmed the resolve is durable (queue empty, job still `done`,
  404/409 on the resolved id). The isolated-verify recipe was persisted to
  `.claude/skills/verify/SKILL.md`.
  **Two corrections to this ticket, made while building it:**
  - **Item 3 was already done.** The claim "the resolve path has no existence check" was wrong —
    `jobs.py:503` has guarded it with a *terminal* `_StageFailure` naming the missing file since
    T-029. The grep behind the claim looked for `isfile` and missed `is_file()`. What was genuinely
    missing is one step earlier: neither read endpoint stat'd the file, so a dead row rendered
    identically to a live one until the owner clicked. That half is what got built —
    `staging_missing` on the hydrated row (`reviews.py`), for the inbox to render in T-102.
  - **Staging root is derived, not configured.** Item 1 said "default `staging_root` to a real
    location, keep the setting overridable". It is now `Store.staging_root` = `db_path.parent /
    "staging"` with **no separate setting**, because a setting invites the row and the audio to be
    pointed at different places, and because a bare `JobWorker(store)` in a test would otherwise read
    *production* settings and sweep the real library's parked audio. Deriving it makes a test Store
    under `tmp_path` own a staging root under that same `tmp_path` — the sweep is safe by
    construction rather than by everyone remembering to pass settings. Promote to an ADR if this
    should bind.
- **Was:** todo — **BUG, HIGH. Owner sequenced this next** (2026-07-25), ahead of the Shazam tier
  build (ADR-019). **Pulled into R1.1** on filing: born in the backlog on the reading that §8 item 1 is
  satisfiable by restarting `uvicorn` alone (which `/tmp` survives) — but item 1 promises a review
  survives a *restart*, and a machine reboot reaps `/tmp`. Leaving it in the backlog would tick the box
  by choosing the gentler restart. `docs/backlog/T-036.md` git-removed on filing; full evidence below.
- **Depends on:** none (server-internal; disjoint from the client tickets — fans out with T-102/T-103).
- **Agent:** build (server)
- **The bug in one line:** a parked review's row is durable; the audio it points at is not. The row
  outlives the song.
- **Evidence (2026-07-25, the owner's live DB).** **9 of 10 live reviews point at a `/tmp/cleanmuzik-*`
  directory that no longer exists.** The 10th is the proof of mechanism: *Frank Ocean — Strawberry
  Swing*, parked 16:39 that day, **has its audio**. The only variable is **age** — nothing in the app
  deleted them; the OS reaped the older dirs while they waited. **The UI cannot see this:**
  `GET /api/reviews` and `GET /api/reviews/{id}` never stat the file, so the inbox renders ten
  healthy-looking rows, nine of which cannot be resolved. Verified against the running server on `:8137`.
- **Why it's a gap, not a decision.** Both halves were decided correctly and never introduced to each
  other. *Retention* was specified emphatically (`docs/r1/spec.md:148` — *"a parked song KEEPS its
  staging file… deleting it makes the resolve unimplementable"*) and the code honours it
  (`run_pipeline`'s `finally` skips the `rmtree` when `retain_staging`). *Location* was never chosen:
  `jobs.py:275` calls `mkdtemp(prefix="cleanmuzik-", dir=staging_root)` and `staging_root` **defaults to
  the system temp** — the comment at `jobs.py:272` shows the setting was added so *pytest* could stage
  under a `tmp_path`. The production default was inherited from `tempfile`, not decided. So the app
  faithfully retains the file in a directory the OS is entitled to delete.
- **What:** the one-line version (repoint `staging_root`) is a trap — **`/tmp` was doing free garbage
  collection.** Parked staging dirs are only cleaned at resolve time and a review can sit indefinitely,
  so a durable root without a sweep trades a broken queue for a filling disk. Four parts:
  1. **Durable staging root.** Default `staging_root` to a real location (e.g. under `server/data/`),
     not the system temp. Keep it overridable so tests still stage under `tmp_path`.
  2. **Own the cleanup `/tmp` was doing.** Sweep orphaned `cleanmuzik-*` dirs with no matching pending
     review at boot — `Store.reconcile_orphans_on_boot` (T-104) is the obvious home. Without this,
     item 1 is a disk leak.
  3. **Fail loudly, not weirdly, on a missing file.** The resolve path has no existence check
     (`_incoming_detail` guards with `os.path.isfile`; nothing else does). A missing staging file should
     surface a clear reason, not an opaque beets failure. Ties to T-103's exits.
  4. **Clear the 9 dead rows — selectively.** *(Owner decision 2026-07-25: delete, don't re-download —
     they were never tagged, so nothing is lost.)* **Selective is load-bearing:** delete rows whose file
     is missing, never "clear the queue", which would take the healthy Frank Ocean review with it.
- **Blast radius:** **T-103**'s re-search exit assumes the audio is still on disk to re-import — built on
  this hole, it inherits it. Spec §7 promises parked reviews *"can still be resolved"*; today 9 of 10
  cannot.
- **Done when:** a review parked before a **machine reboot** is still resolvable after it, demonstrated
  end-to-end (`/verify`): park a track, restart, resolve, confirm the tagged MP3 lands in Jellyfin. Plus
  a boot with orphaned staging dirs sweeps them, and the dead rows are gone while the healthy one
  survives. Ties to §8 items 1 + 8 (the reboot item, added with this ticket).
- **Observable artifact (2026-07-25, two separate processes — the restart is real, not simulated).**
  Isolated `DB_PATH` + a monkeypatched `LIBRARY_DIRECTORY`, so nothing touched the real library. The
  subject is the Nines `"Franklin"` rip (`D5QjfJao9FQ`) — the one that parked **five times** in the
  owner's real queue and that even Shazam missed (T-035), so the park is genuine, not contrived.
  **Process A:** real yt-dlp download → transcode → beets gate → parked, `staging_path` under
  `…/data/staging/cleanmuzik-391h0ykk/`, file on disk. **Process B (the reboot):** a `cleanmuzik-`
  debris dir planted first, then `JobWorker.start()` → *the parked staging file survived* and *the
  orphan dir was swept*. Then resolved (MB re-search, `Outro` score 100 →
  `f5d1bcfb-f66e-400a-948a-e7f9127160de`, the T-103 gesture) → **`Nines/Outro.mp3`, 8.2 MB, 327 kbps,
  title/artist/genre `Hip Hop` tagged, cover art embedded (mjpeg)**, review `resolved`, staging removed
  — retention ending exactly where spec §5 says it should. *Caveat, stated plainly:* every review in
  the owner's real queue has **no candidates**, so the landing half was driven through `run_resolve`
  directly with a re-searched MBID; route validation would refuse that body today. That is the T-103
  dead-end, not a T-106 gap, but it means the **through-the-UI** half of this ticket cannot be shown
  until T-103 lands.

---

## Not pulled into R1.1 (stay in the backlog)

- **T-032** (browser reload loses job cards) — **deferred by design.** ADR-017 makes job cards
  ephemeral theatre; the durable surface is the inbox, which R1.1 delivers. Restoring transient cards is
  separate and lower-value. Note updated in `docs/backlog/T-032.md`.
- **T-030 / T-023** (Jellyfin lyrics second-scan) and **T-031** (album recovery) — R2/migrate concerns.
- **Candidate-art thumbnails in the picker** — deferred per ADR-010 (needs a per-candidate art lookup).
