# R2 Tickets — Playlists (+ T-037 tag-mangle fix)

> **Status: GENERATED — 2026-08-14, from `docs/r2/spec.md` (`ready-for-agent`, scope signed off at the
> 2026-08-08 grilling); four cold-review lenses folded (spec-fidelity, drop-in buildability, ADR/constraint
> compliance, data-model correctness — 2026-08-14).** Decompose the R2 spec into build-order tickets. Each
> "Done when" ties back to a numbered **acceptance-checklist** item (the "R2 is done when…" list,
> §Further Notes — **1–12**); user-story references (US-N, N up to 27) are called out separately as
> `Stories:` and are **not** the acceptance citation. **Same ticket format and Definition of Done as
> `docs/r1/tickets.md` — don't restate them; read that header.** Numbering is the **T-3xx** series to avoid
> collision with R1 (T-0xx / backlog), R1.1 (T-1xx), R1.5 (T-2xx). **T-037** keeps its original number
> (pulled up from `docs/backlog/`, split into its two defects — T-308 / T-309).

**Scope guard (roadmap rule).** R2's scope is its acceptance checklist. Findings surfaced while building
are captured as tickets and triaged **at birth** — required for an acceptance item → here; else →
`docs/backlog/`. **The fence (spec §Out of Scope):** no migrate/clean (that is **R2.5**), no loose
multi-URL paste, no "Recently Added" rolling playlist, no user-named playlists, no exact-position backfill.
Do not let any of them creep in. The parked backlog tickets (T-034/035/042/023/030/031/032/039/041) each
ride their own release — do not pull them.

**This extends R1/R1.1/R1.5 — it turns the *existing* pipeline on a batch and adds a Jellyfin-playlist
output.** Download → transcode → identify → tag → land is untouched (ADR-001, sequential). The switch that
keeps R1 byte-for-byte unchanged is a single nullable column: `jobs.playlist_id IS NULL` = the R1 path.
A regression in single-song acquire is a build failure (acceptance item 11), not a trade-off.

**Two ADRs are prerequisites, both settled BEFORE the design gate (T-310):** ADR-027 (batch/backfill data
model — T-300) and ADR-028 (T-037 artist-credit normalisation — T-301). The spec is explicit: the mockups
encode these, and retrofitting the association into live job data later is unrecoverable. **ADR-027 must
settle six seams the cold-review surfaced (enumerated in T-300)** — the schema alone is not enough; the
timing/durability/idempotency decisions are what the mockups and every downstream ticket depend on.

## Build order

**Phase A — decisions + data model (gate everything).** The two ADRs and the schema they bind land first;
nothing downstream can be mocked or built until the association *and its six seams* are settled.

- **T-300** batch/backfill data model + ADR-027 · **T-301** T-037 normalisation decision + ADR-028.

**Phase B — accept, dedup, the two output seams (backend).** Once the schema exists: T-302 expands, then
the Jellyfin seam (T-304) lands **before** dedup (T-303), because T-303's skip path *adds the existing file
to the playlist* through T-304's append (they are **not** parallel — cold-review correction).

- **T-302** accept + expand → **T-304** Jellyfin playlist seam → **T-303** exact-video dedup → **T-305**
  batch-scoped SSE + new events → **T-312** durable batch state + reconnect.

**Phase C — compose the batch behaviours.** Backfill and idempotent re-paste sit on top of the seams.

- **T-306** backfill (review→playlist) · **T-307** idempotent re-paste.

**Phase D — T-037.** Independent of the batch spine; can run alongside Phase B once ADR-028 (T-301) lands.

- **T-308** defect 1 (artist-credit normalisation) · **T-309** defect 2 (genre-report read-off-disk).

**Phase E — UI.** The one aggregate card. **ADR-016 design gate first** — flat HTML scenario screens
including the ugly states, signed off before component code.

- **T-310** batch view (aggregate card).

**Phase F — verify.** Drive the real flow end-to-end against the acceptance checklist.

- **T-311** end-to-end `/verify` + R1 non-regression.

Definition of Done per ticket is the repo rule (`docs/workflow.md`): `/code-review` on the diff, the
acceptance re-read against the spec section it cites, `/verify` the real side effect for pipeline tickets,
integrate onto `main` with the status line flipped in the closing commit, transcribe corrections to
`docs/learnings.md`.

---

## Phase A — decisions + data model

### T-300 — Batch/backfill data model: `playlists` entity, `jobs` columns, membership store (+ ADR-027)
- **Status:** done
- **Depends on:** none
- **Agent:** back-end
- **What:** Record **ADR-027** and implement the schema it binds — the association every later ticket reads.
  **Schema, and the two migration mechanisms are DIFFERENT (cold-review BLOCKER — do not conflate):**
  - **New tables → `CREATE TABLE IF NOT EXISTS` in `db.py:_SCHEMA`** (runs before `_migrate` in
    `init_schema`, `db.py:~231`). This is the **correct, safe** path for tables that do not yet exist on the
    owner's live DB — the `IF NOT EXISTS` guard creates them and no-ops thereafter. It is **also required**
    because `_ADDED_COLUMNS`/`_migrate` runs `ALTER TABLE … ADD COLUMN` only and **SQLite cannot add a
    `UNIQUE` column via ALTER** — so `youtube_playlist_id UNIQUE` and the membership `UNIQUE(playlist_id, …)`
    have no other home. The **`playlists`** table: `id`, `youtube_playlist_id` (**UNIQUE**), `title`,
    `jellyfin_playlist_id` (**nullable** until created), `created_at`. The **membership** table:
    `(playlist_id FK, member key, position)` with **`UNIQUE(playlist_id, member)`** so a double-add is
    structurally impossible.
  - **New `jobs` columns → `db.py:_ADDED_COLUMNS`** (ALTER ADD COLUMN): **`playlist_id`** (nullable FK →
    `playlists.id`; **null = single-song paste = R1 path unchanged**), **`position`**, **`youtube_video_id`**.
    The nullable FK is legal via ALTER *because it defaults NULL*, and `_SCHEMA` has already created
    `playlists` by the time `_migrate` runs. (The R1.5 T-206 lesson is only that a **new column** can't be
    smuggled into an existing table's `CREATE` — it does **not** forbid `CREATE TABLE IF NOT EXISTS` for a
    genuinely new table.)
- **ADR-027 must settle these six seams — the schema alone is not enough (all surfaced by cold-review):**
  1. **Jellyfin item-ID post-scan resolve (T-304):** the concrete wait — poll Items-by-path, bounded
     interval, **hard timeout** — and the fallback on expiry: **write app-side membership now, defer/retry
     the Jellyfin append** (a "pending append" the next scan reconciles). The resolve **must not block the
     sequential worker** (else a 50-track batch serializes into minutes of dead `/Library/Refresh` waits).
  2. **Landed-video dedup store + predicate (T-303):** **one** store — the `jobs` row's `youtube_video_id`
     (written at **enqueue**, T-302) — and the exact test **`EXISTS(job WHERE youtube_video_id = ? AND
     status = 'done')`**. The `status='done'` filter is load-bearing: without it a **parked or failed**
     never-landed entry reads as "already owned" and a re-paste skips it forever.
  3. **Jellyfin playlist create timing:** create at **`batch.queued`** (expansion), **not** on first land —
     else an all-parked batch never gets a `jellyfin_playlist_id` and its later backfill (T-306) has nowhere
     to append. (Or: backfill creates-if-missing. Pick one; recommend create-at-queued.)
  4. **Membership uniqueness + per-entry order:** `UNIQUE(playlist_id, member)`; append is a **no-op when
     membership exists**; per entry the order is **membership-check → library video-dedup → process** (so a
     re-paste of an already-in-playlist owned video cannot double-add).
  5. **Durable batch state (T-312):** the batch tally + terminal state must be **derivable from
     `jobs.playlist_id` + membership** (grouped by status), not only accumulated in the in-memory event bus
     — so "walk away and come back" survives a **restart**, not just an in-process reload.
  6. **`playlists` create-or-reuse is an atomic upsert:** `INSERT … ON CONFLICT(youtube_playlist_id) DO
     NOTHING` then SELECT — not SELECT-then-INSERT (avoids an `IntegrityError` on a double-paste).

  ADR-027 also records the entity shape, the nullable-FK-as-R1-switch, the membership store as the source of
  truth read three ways (re-paste, counters, backfill), and the backfill chain
  `review → job → playlist → jellyfin_playlist_id`. Define the association shape once so
  T-302/T-304/T-305/T-306/T-307/T-312 all import it.
- **Done when:** the `playlists`, membership, and three `jobs` columns exist and apply cleanly to a
  **pre-existing** DB (tables via `_SCHEMA`, columns via `_ADDED_COLUMNS`); a round-trip test writes a
  playlist + a member track-job and reads them back after a process restart; the `UNIQUE` constraints hold;
  ADR-027 is filed in `docs/r1/adr.md` with all six seams settled. (Spec §Implementation "Batch model" +
  "This data model is a new ADR"; gates the design gate. Acceptance item 11 — the null-`playlist_id` R1
  switch.)

### T-301 — T-037 canonical artist-credit normalisation: the decision (ADR-028)
- **Status:** done — **ADR-028 filed 2026-08-15** (council-reviewed: 4 lenses + chair; owner picked the
  layered+observable reach). Decisions: surgical layered fold (NFC floor + enumerated `Ÿ`→`Y` map +
  hyphen-class U+2010/U+2011→U+002D), placement via one shared `canonicalize_credit` helper in
  `import_seam.py` wired at BOTH `_accept` (:634) and `ResolveSession.choose_item` (:1520), NFKC/TR39/
  ASCII-strip rejected on record. **Diagnosis corrected:** the `Ÿ` is NOT an in-app decode fault (byte-
  mechanically impossible; MB serves it, beets writes it faithfully) — reframed as identity
  normalisation. See ADR-028's binding note for T-308 (both sites must route through the helper) and the
  near-duplicate-folder tripwire filed as a follow-on.
- **Depends on:** none
- **Agent:** back-end
- **What:** Record **ADR-028** — the decision that binds **every path the app writes**, so T-308 has a
  ratified rule to implement. The diagnosed cause (spec §Implementation "T-037"; `docs/backlog/T-037.md`):
  MusicBrainz's canonical credit uses a Unicode hyphen **U+2010**, and the `Y` is mangled to **`Ÿ` (U+0178)**
  in the write path — riding the **matched-metadata** path (both mangled items carried `mb_trackid`s), not a
  no-match fallback. ADR-028 decides: (a) the **`Ÿ→Y` fold**, (b) the **hyphen policy** (normalise
  U+2010→U+002D, or accept MB's), (c) placement in the **write / path-format path**. **Stand on this
  ticket's own diagnosis — do NOT cite ADR-019 as precedent** (cold-review: ADR-019's fold is a *search-query*
  ASCII-fold that affects MusicBrainz *ranking, not identity*; the T-037 fold is a *write-path* normalisation
  that deliberately **does** change the artist's canonical folder = its Jellyfin identity — the opposite
  direction). The one-time library sweep for existing mangled folders is **already done for Jay-Z** (recipe
  in `docs/backlog/T-037.md`) — do not re-litigate; ADR-028 is about **every future write**.
- **Done when:** ADR-028 is filed in `docs/r1/adr.md` with the fold, the hyphen policy, and the path-format
  placement recorded; T-308 can implement it without a further decision. (Spec §Implementation "T-037 defect
  1"; §Further Notes "two ADRs before the design gate". Acceptance item 9 — the fix ADR-028 authorizes.)

---

## Phase B — accept, dedup, the two output seams

### T-302 — Accept + expand a playlist URL → N track-jobs (relax the 422)
- **Status:** done — shipped 2026-08-16 (council-settled create split → ADR-027 seam-3 addendum;
  `create_playlist` degrades on absent/failed Jellyfin; verified against a real 183-track playlist).
- **Depends on:** T-300, **ADR-029** (explicit-intent accept contract)
- **Agent:** back-end
- **What:** **`app/routes/jobs.py`** (the route — **not** `app/jobs.py`, the worker) currently refuses a
  playlist URL by shape (`422`, `app/routes/jobs.py:~63`, `download.is_playlist_url`/`names_one_song`). R2
  **accepts** it: **create-or-reuse the `playlists` row** via an **atomic upsert** (`INSERT … ON
  CONFLICT(youtube_playlist_id) DO NOTHING` then SELECT — T-300 seam 6), **create the Jellyfin playlist now**
  (at expansion — T-300 seam 3, so an all-parked batch still has a `jellyfin_playlist_id`), expand via
  **yt-dlp** into entries, and enqueue **one track-job per entry** carrying the shared `playlist_id`, its
  `position`, and its **`youtube_video_id`** (available per-entry at expansion — `SourceSignals.video_id`
  confirms the field). Playlist **title is derived** from the YouTube title (§Out of Scope: no user naming).
  A **single-song** URL still enqueues **one `playlist_id = null` job** — the R1 path, byte-for-byte
  unchanged. Reuse the per-song job + the R1/R1.1 pipeline **and the review lifecycle unchanged**: **parked
  batch tracks route to the existing `/api/reviews` inbox** (US6 — batching invents no second place to look).
- **Explicit intent (ADR-029).** `POST /api/jobs` gains an **optional `intent` enum (`single | playlist`;
  `multi` reserved, not wired).** When **present**, it decides the ambiguous `watch?v=X&list=PL…` case — the
  dial's answer, **not** `names_one_song` — so a song-in-a-playlist paste can expand instead of silently
  stripping. When **absent**, fall back to today's shape inference **verbatim** so R1 is byte-for-byte
  unchanged. Intent stays at the accept/expand door — **it must NOT leak into the pipeline** (that column
  switch is what guarantees R1 non-regression). Kill the shape re-guess **only** for the explicit case.
- **Jellyfin create lives HERE (council-settled 2026-08-16, ADR-027 seam-3 addendum).** T-302 adds a
  minimal **`create_playlist()`** to `jellyfin.py` (one `POST /Playlists` by the derived name, mirroring
  `trigger_scan`'s DI + config-strip shape) and calls it at expansion, gated `if playlist.jellyfin_playlist_id
  is None:` (so a re-paste does not double-create), storing the returned id via `set_jellyfin_playlist_id`.
  **Failure contract (owner-settled): degrade to `None` + warn on BOTH config-absent AND a present-but-failed
  POST** — a create gates all N enqueues, so a transient Jellyfin blip must not abort the batch; the null
  falls to T-306's create-if-missing guard. T-304 owns the hard remainder (resolve / append / reconcile).
- **Done when:** a playlist URL that R1 answered `422` now upserts the `playlists` row, creates the Jellyfin
  playlist **via the minimal `create_playlist()` (stubbed in tests), persisting a non-null
  `jellyfin_playlist_id` — and, config-absent OR POST-failed, degrades to a NULL id without aborting the
  batch (the all-parked / Jellyfin-less case)**, and expands into N enqueued track-jobs each with the shared
  `playlist_id` + distinct `position` + its `youtube_video_id`; **an `intent`-carrying `watch?v=X&list=PL…`
  expands (or stays single) per the field, and an `intent`-less request classifies exactly as R1 did**; a
  single-song URL still enqueues one `playlist_id = null` job on the R1 path. (Acceptance item 1; item 11 —
  R1 unchanged. Stories: US1, US2, US6, US14. Intent contract: ADR-029. Create split: ADR-027 seam-3 addendum.)

### T-304 — Jellyfin playlist output seam: resolve / append / defer-first reconcile (+ membership write)
- **Status:** done
- **Depends on:** T-300
- **Agent:** back-end
- **What:** `jellyfin.py` today does exactly one thing — fire-and-forget `POST /Library/Refresh`
  (`jellyfin.py:~87`); it has **no item-resolution** capability. Extend the **single existing Jellyfin seam**
  (no second integration point) with `resolve_item_id` (a landed file → its Jellyfin item id, `Items?Path=`)
  and `append_to_playlist`. **`create_playlist` is NOT here — it was defined *and* called in T-302**
  (council-settled 2026-08-16, ADR-027 seam-3 addendum). T-304 consumes the `jellyfin_playlist_id` T-302
  already stored.
  **Resolve/append timing — DEFER-FIRST, superseding the inline poll (4-lens council + owner, 2026-08-16;
  ADR-027 seam-1 amendment):** Jellyfin's scan is async, so a landed file's item id exists only after it
  indexes. The worker **never polls a just-landed track's own (least-settled) index** — that added ~10s×N of
  dead time to the sequential worker. Instead: at land, write the pending membership row immediately
  (`jellyfin_item_id NULL` + `landed_path`) and move on; a reconcile pass (`reconcile_pending_appends`)
  resolves+appends the *older*, already-indexed pending members, triggered three ways — opportunistically on
  each subsequent land (fills the playlist live-ish), a **background tick** (~25s) + a **boot sweep** (own the
  tail). A resolve is a single attempt retried across passes; `append_attempts` (cap 20) bounds it into a
  visible give-up, never a silent drop. Append is a **no-op when membership already exists** (T-300 seam 4).
  The file lands **canonically under `Artist/Album`** (one copy on disk); the playlist holds **pointers**.
  M3U-on-disk was weighed and rejected (doesn't skip the index wait; read-only + wipe bugs since 10.9) — see
  the ADR-027 seam-1 amendment.
- **Done when:** ✅ against a **stubbed** `jellyfin.py` edge, the app appends with the right (playlist, item)
  using the `jellyfin_playlist_id` T-302 stored; the resolve **defers rather than blocking or racing the
  worker** (single attempt, retried across passes — the superseding shape of "doesn't block the worker"); a
  resolve miss leaves membership + a pending append (no silent drop) — in fact membership+path is written at
  land, *before* any resolve, so it is always durable; a re-append of an existing member is a no-op
  (idempotent across passes); the canonical file is unmoved (the membership holds the path, nothing touches
  the file). Covered by `tests/test_playlist_append.py` (24 tests). The **real** Jellyfin playlist appearing
  is proven in T-311. (Acceptance items 2, 3; ADR-027 seam-1 amendment. Stories: US4, US5.)
- **Known limitation (cold-review, deferred):** appends land in **drain (≈land) order**, not the source
  playlist's `position` order. In the common all-land case tracks land in position order so the two agree;
  they diverge only when a track lands late (parked → resolved). Jellyfin's append API adds to the end, so
  strict source-order needs a follow-up reorder pass (`POST /Playlists/{id}/Items/{itemId}/Move/{index}`)
  keyed on the stored `position`. Not in T-304's "Done when"; flagged for owner call (own ticket vs T-311).

### T-303 — Exact-video de-duplication (record video-ID at enqueue; skip only landed videos)
- **Status:** done
- **Depends on:** T-300, **T-304** (the skip path adds the existing file to the playlist via T-304's append)
- **Agent:** back-end
- **What:** `youtube_video_id` is written on the `jobs` row **at enqueue** (T-302). On expansion, test each
  entry against the durable landed set **exactly — never fuzzy** — with the **status-filtered** predicate
  (T-300 seam 2): **`EXISTS(job WHERE youtube_video_id = ? AND status = 'done')`**. The `status='done'` filter
  is mandatory — a parked/failed never-landed entry must **not** read as owned, or a re-paste skips it
  forever.
  - **Hit** → skip download/transcode/identify/tag entirely; **add the existing canonical file to the
    playlist** (via T-304's append, membership-guarded) and emit **`track.skipped`**. **Silent — must NOT
    route through the ADR-009 duplicate-park keep/replace path** (that path is for a different-bitrate library
    duplicate offered as a choice; an exact re-paste of a video already in *this* library is just "already
    have it"). ADR-009's recording-ID dedup at `choose_item` land-time is left fully intact for the miss path.
  - **Miss** → the normal pipeline. A genuinely **different upload** of an owned song is treated as **new**
    (accepted duplicate-file risk — US13 — so no wanted song is silently swapped out).
  Per-entry order is **membership-check → this video-dedup → process** (T-300 seam 4).
- **Done when:** an entry with a `status='done'` video-ID match **skips + adds-to-playlist + emits
  `track.skipped`** and does **not** hit the ADR-009 park path; a **parked/failed** prior entry with the same
  video-ID is **re-processed, not skipped** (the status filter); a different video (different ID) processes
  as new with **no fuzzy match attempted**. (Acceptance item 6; item 3 — add-to-playlist. Stories: US10,
  US11, US12, US13.)

### T-305 — Batch-scoped SSE: one stream per batch + new events; terminal "waiting on you"
- **Status:** todo
- **Depends on:** T-302
- **Agent:** back-end
- **What:** A 50-track batch must **not** open 50 `EventSource`s (browsers cap ~6/origin → 44 dead streams).
  Open **one** playlist-scoped stream. `events.py` keys channels by an arbitrary string — today the
  **`job_id`** (`publish(job_id, …)`, `dict[str, _JobChannel]`). Batch-scoping is **not free "reuse":** every
  existing emit site in the worker (`registry.set_stage`, the `track.*` publishes in `app/jobs.py`) must
  **also publish under the playlist key**, and the channel cap (`_CHANNEL_CAP`, mirrors
  `JobRegistry._REGISTRY_CAP`) **must not evict the long-lived batch channel** while 50 short per-job channels
  churn — pin/exempt it. Each event is **stamped with the track's `position`/job id**. Add the stable event
  names: **`batch.queued`** (title + total count), **`track.skipped`** (the entry added without re-processing
  — **required for the idempotent re-paste view**), **`batch.progress`** (tally: landed / in-review / failed
  / skipped / queued). Existing `track.*` events ride the batch stream **unchanged plus** the stamp. **Derive
  the batch terminal state:** a finished grind with **parked > 0 reports "waiting on you," not "done"**; a
  failed track does **not** stop the batch (ADR-002). `batch.progress` is **computed from the durable
  jobs/membership state (T-312)**, not accumulated only in memory, so a mid-batch restart doesn't lose it.
- **Done when:** a batch drives **one** stream (not one-per-track) carrying `batch.queued` / `batch.progress`
  / `track.skipped` and the stamped `track.*`; the batch channel is **not** evicted while member channels
  churn; the tally matches the real land/park/skip/fail counts; a forced track failure leaves the rest of the
  batch running; terminal state is "waiting on you" while parked > 0. (Acceptance items 1, 7. Stories: US15,
  US16, US17, US18, US19.)

### T-312 — Durable batch state + reconnect (walk-away survives a restart)
- **Status:** todo
- **Depends on:** T-300, T-305
- **Agent:** back-end
- **What:** The single-song card reconnects by overlaying the durable `jobs` row on the live registry
  (`app/routes/jobs.py:~107`) + the SSE replay buffer. A **batch** has **no equivalent** — the tally and
  terminal state live only on the in-memory `EventBus` (cleared on restart). In-process reload is already
  covered by the channel's replay buffer, but **"walk away and come back" across a restart is not** (stories
  20, 22). Add a durable batch-state read — a **`GET /api/playlists/{id}`** (mirroring the single-song
  reconnect pattern) that **derives** the aggregate tally and per-track outcomes from `jobs WHERE
  playlist_id = ?` grouped by status **+** the membership store (skipped/added) — so `batch.progress` (T-305)
  and the T-310 card can rebuild from durable state after a restart, not just replay memory. No new landing
  path; a read-only projection.
- **Done when:** after a **backend restart** mid-batch, `GET /api/playlists/{id}` returns the correct tally
  (landed / in-review / failed / skipped / queued) and terminal state ("waiting on you" while parked > 0)
  derived from SQLite — the card rebuilds without any in-memory event history. (Acceptance item 7 — terminal
  state durable; supports item 1's "walk away". Stories: US20, US22.)

---

## Phase C — compose the batch behaviours

### T-306 — Backfill: a resolved parked track appends to its playlist
- **Status:** todo
- **Depends on:** T-304, T-302
- **Agent:** back-end
- **What:** Walk the locked chain **`review → job → playlist → jellyfin_playlist_id`**. When a parked track
  is resolved through the **existing** `/api/reviews` resolve path (`reviews.py` → `resolve_import`) and
  lands, the resolve's landed branch looks up the job's `playlist_id`; **if present, append** the
  newly-landed track to that Jellyfin playlist (T-304's append + membership write). **If
  `jellyfin_playlist_id` is somehow null** (all-parked batch that skipped create — should not happen given
  T-302 creates at queued, but guard it), **create-if-missing** rather than dropping the append. **Append to
  end — position is NOT preserved** (owner decision US8; original `position` is still recorded so the list
  isn't *actively* scrambled and the card can show journal order from the store if it ever wants to, but no
  effort is spent re-inserting). No new landing path — reuse the resolve machinery.
- **Done when:** a track parked in a batch, resolved via `/api/reviews` **across a restart** (days later),
  **appends to its original Jellyfin playlist automatically**, proven by playlist membership — not by reading
  the `playlists` table. (Acceptance item 4. Stories: US7, US8.)

### T-307 — Idempotent re-paste: same playlist updated, only new entries added
- **Status:** todo
- **Depends on:** T-304, T-303
- **Agent:** back-end
- **What:** Re-pasting a playlist as it grows must update the **same** Jellyfin playlist, never create a
  duplicate. On re-expansion: reuse the existing `playlists` row (unique YouTube playlist ID → existing
  `jellyfin_playlist_id`); per entry, in this **fixed order** (T-300 seam 4): **(1) membership-check** — skip
  entries already in *this* playlist (the app-side membership record — **not** a query back to Jellyfin);
  **(2) library video-dedup** (T-303, silent `track.skipped`) — skip videos already landed but **add them to
  this playlist** (a July song reappearing in August shows in both); **(3) process** only genuinely new
  entries. The membership `UNIQUE(playlist_id, member)` makes a double-add structurally impossible. The
  common case — a mostly-landed re-paste — reads as a quiet "N already here, M added, nothing wrong"
  (rendered T-310).
- **Done when:** run a playlist, then re-run it with one added entry: the first run's tracks emit
  `track.skipped` (not re-downloaded), the one new entry processes, an already-owned entry new to the
  playlist is **added exactly once**, and the Jellyfin playlist is the **same** one (not duplicated); a
  video already in both library and playlist does **not** double-add. (Acceptance items 5, 9-adjacent (re-add
  path); item 11 (already-have still added). Stories: US9, US10, US11.)

---

## Phase D — T-037 (git mv from `docs/backlog/`)

> `docs/backlog/T-037.md` carries the full diagnosis + the one-time-sweep recipe (already run for Jay-Z). On
> starting T-308, **`git mv docs/backlog/T-037.md docs/r2/`** so the evidence travels with the release (spec
> §Further Notes "T-037 filing"); these two tickets are its build halves.

### T-308 — T-037 defect 1: canonical artist-credit normalisation in the write path
- **Status:** todo
- **Depends on:** T-301
- **Agent:** back-end
- **What:** Implement ADR-028 (T-301): a **canonical artist-credit normalisation step in the write /
  path-format path** so **no fresh download re-introduces a mangled folder** (`JAŸ-Z` / `JAŸ‐Z` and
  variants). The fix rides the **matched-metadata** path (both mangled items carried `mb_trackid`s — it is
  not a no-match fallback). Fold per ADR-028 (`Ÿ→Y`, hyphen policy). Not Jay-Z-specific — any artist whose
  credit trips the `Y→Ÿ` decode splits, so the guard is general.
- **Done when:** a **fresh download** of a T-037-class artist (feed a matched credit reproducing the `Y→Ÿ` /
  U+2010 case) lands under the **single canonical folder** — a regression guard that a fresh write never
  re-splits the artist. (Acceptance item 9. Stories: US24, US25.)

### T-309 — T-037 defect 2: the genre-report bug (read the written genre off disk)
- **Status:** todo
- **Depends on:** none
- **Agent:** back-end
- **What:** The **only** genuine defect-2 bug (the plugin/key theories were refuted by the T-103 verify —
  `lastgenre` + `LASTFM_APIKEY` proven working; a bare genre is real per-recording Last.fm coverage, and
  `album` absence is correct per ADR-010): the SSE `track.done` payload's genre is `None` while the file on
  disk carries a genre (T-103: `Outcome.tags` genre `None`, disk `'Soul'`). **Do not assume a specific
  cause** — the backlog's "snapshot taken before `lastgenre` writes" is a *"presumably,"* and it **conflicts
  with the code**: `finalize_outcomes` (`import_seam.py:~833`) documents itself as running **post-`run()`**
  and `_landed_tags` (`:~1315`) already reads `getattr(item, "genre")` claiming it's "whatever lastgenre
  wrote." So the fix the Done-when demands is behavioural: **make `track.done` carry the genre actually on
  disk** — read the tag back off the landed file for the payload (do not rely on an in-memory snapshot whose
  timing is unproven). `lastgenre` remains live (ADR-023 genre-authoring is deferred to R1.6 — this does not
  touch it).
- **Done when:** a landing whose file carries a genre on disk emits `track.done` with **that** genre (not
  `None`) — asserted by reading the tag back off disk and comparing to the event. (Acceptance item 10.
  Stories: US26.)

---

## Phase E — UI

### T-310 — Batch view: one aggregate playlist card
- **Status:** todo
- **Depends on:** T-305, T-312, T-303, T-304, T-306 (behaviours + durable state to render); **ADR-027 +
  ADR-028 settled** (T-300, T-301)
- **Agent:** front-end
- **Design gate (ADR-016) — BEFORE component code.** This changes a user-visible **flow/state**, so it passes
  the design gate first: **flat HTML scenario screens, one per scenario including the ugly states** — a
  just-started batch; the live currently-processing track; a failed song ("gone / unavailable", **not**
  error-red); "N in review" ("still filling in"); the terminal **"waiting on you"** (parked > 0); and a
  **mostly-already-done re-paste** ("45 already here, 3 added, nothing wrong") — published for owner sign-off.
  Runs *ahead of* the DoD, not inside it. The mockups **encode ADR-027/028** — writing them before those ADRs
  land means re-mocking (why the design gate depends on Phase A). **Gate artifact: `docs/r2/design/t310-batch-view.html`.**
  - **Added 2026-08-16 (ADR-029): the acquire dial screens (D1–D4).** The gate also covers the acquire-intent
    control that feeds the batch — the round detented **Single / Playlist / Multi·soon** selector: its three
    resting stops, the `watch?v=X&list=PL…`-on-Single **quiet note** (no prompt — the dial is the intent, ADR-029), and the **Multi "soon"** state. The
    dial is input-strip only; **the aggregate card itself is unchanged** by it. The Multi *build* is backlog
    (see T-046); this ticket ships the dial's **Single + Playlist** behaviour with Multi present-but-inert.
- **What:** **One aggregate playlist card** in the existing `.deck` layout (no router), reusing **the shipped
  console skin (ADR-018 — note: "Signal Path" is the *superseded* predecessor per ADR-018's 2026-08-04
  amendment; canonical is the shipped code `11b6302`+`819f22c`, not `signal-path-tweaked.html`)** and the
  existing review-inbox resolve seam. Contents: an aggregate **progress meter + outcome tally** (landed /
  in-review / failed / skipped / queued); the single **currently-processing** track shown **live**; the rest
  **bucketed by outcome with the "needs you" bucket hoisted to the top**; **album art on LANDED rows only**
  (ADR-010/018 discipline — parked/in-review rows carry **no** art placeholder, just "still filling in";
  `819f22c` removed a swatch precisely because it asserted art where none need exist); parked/failed rendered
  as **"still filling in" / "gone"**, not error-red. The card **survives a page reload and a restart** (reads
  T-312's durable state). Single-song R1 acquire keeps its existing card unchanged.
- **Done when:** the design screens are signed off; then a real 50-ish-track batch renders as **one** card
  showing progress, the live track, outcome buckets ("needs you" on top), **art on landed rows only**, and
  the terminal "waiting on you" while parked > 0; the view **survives a reload and a restart**; the
  single-song card is unchanged. (Acceptance items 7, 8. Stories: US15, US16, US20, US22, US23.)

---

## Phase F — verify

### T-311 — End-to-end `/verify` against the acceptance checklist + R1 non-regression
- **Status:** todo
- **Depends on:** T-302–T-310, T-312 (all)
- **Agent:** verify
- **What:** Drive the **real** flow — a `/verify` run pasting a **small real playlist** end-to-end,
  **offline-isolated** (temp `DB_PATH` + temp beets library; **`pgrep -af uvicorn` first**; see
  `docs/workflow.md` + the `/verify` skill so the run never pollutes the real Jellyfin library) — and observe
  the **real side effects** for every acceptance item: files landed **canonically under `Artist/Album`** (one
  copy on disk); the **Jellyfin playlist created and populated** as tracks land (the real Jellyfin, exercised
  only here); a **parked track backfilling** into its playlist on resolve; a **re-paste** updating the same
  playlist, skipping owned videos silently, adding only new; an **exact-video dedup** skip **and** a
  parked-not-skipped re-process (the status filter); a **failed track** not stopping the batch, terminal
  "waiting on you"; the batch state **surviving a mid-batch restart** (T-312); a **T-037-class artist**
  landing under the single canonical folder; **`track.done` reporting the genre on disk**; and **single-song
  R1 acquire unchanged**. Transcribe any correction to `docs/learnings.md`.
- **Done when:** **every** acceptance-checklist item is proven by `/verify` observing the real side effect (a
  correctly-tagged MP3 320 in the right place, the real Jellyfin playlist created + backfilled, the tally
  rebuilt after a restart) — not by "the code looks right"; suites green on `main`. (Spec §Further Notes
  acceptance checklist, whole list; DoD step 3.)

---

## Acceptance-checklist → ticket trace

| # | Acceptance item (spec §Further Notes) | Owning ticket(s) |
|---|---|---|
| 1 | Playlist expands, every track processed sequentially over one SSE stream | T-302, T-305 |
| 2 | Jellyfin playlist named after the YouTube title created + populated | T-304 |
| 3 | Each file canonical under `Artist/Album`; one copy, playlist holds pointers | T-303, T-304 |
| 4 | Parked track resolved later appends to its playlist automatically | T-306 |
| 5 | Re-paste updates the same playlist, skips already-have silently, adds new | T-307 |
| 6 | Exact-video duplicate skipped + added; no fuzzy matching | T-303 |
| 7 | Failed track doesn't stop the batch; "waiting on you" while parked > 0 (durable) | T-305, T-312, T-310 |
| 8 | Batch view is one aggregate card (design-gate screens signed off first) | T-310 |
| 9 | Fresh download of a T-037-class artist lands under the single canonical folder | T-308 |
| 10 | `track.done` reports the genre actually written to disk | T-309 |
| 11 | Single-song acquire (R1) unchanged | T-302, T-311 |
| 12 | Suites green on `main`; `/verify` shows the real playlist created + backfilled | T-311 |

## Backlog (not R2 — captured, triaged at birth per the scope guard)

Findings that surface while building go to `docs/backlog/` unless an acceptance item **requires** them. The
deliberate fence (spec §Out of Scope): migrate/clean → **R2.5**; loose multi-URL paste, "Recently Added"
rolling playlist, user-named playlists, exact-position backfill → later/rejected; the parked backlog
(T-034/035/042/023/030/031/032/039/041) each rides its own release. Do not pull them.
