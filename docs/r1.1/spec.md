# R1.1 Spec — Review Inbox (remediation slice)

> **Status: drafted 2026-07-23 from signed-off design gates.** The *behaviour* (flow) and the
> *skin* (Signal Path) are owner-signed-off as flat screens — see **Design artifacts** below.
> This doc records what those screens commit to. Skim and confirm; then the roadmap flips R1.1 to
> `in-build` and tickets start.

## Why R1.1 exists (it's remediation, not new scope)

R1 shipped with a **spec-vs-build gap**. Spec §7 promises: *"Restarting the backend preserves parked
reviews; they can still be resolved."* The backend half is true (SQLite persists every review). The
**UI half is false**: the review lifecycle was built *inside* `TrackCard` (T-016/T-020), and the
card list is ephemeral React state (`App.tsx`) that boots empty. So on a fresh load a parked review
is **invisible and unreachable** — the durable `GET /api/reviews` endpoint (T-014) exists but no
client code calls it. A no-candidate park renders a **dead-end panel with no buttons** (the owner hit
this live, 2026-07-23). This is an R1 exit-criteria miss, closed here rather than left for R2 to build
migrate on top of — see the roadmap note (migrate is a firehose into this same queue).

## 1. Goal of R1.1

Parked reviews **survive close/reopen and are always resolvable**, from a durable surface that isn't
tied to a live job card. Pay down the `TrackCard` state-machine debt as the direct means. Reskin to
the signed-off **Signal Path** identity.

## 2. In scope

- A durable, top-level **review inbox** — the client consumes `GET /api/reviews` on cold load and
  renders the parked queue independent of any live card.
- The review lifecycle **moves out of `TrackCard`** into the inbox (**ADR-017**). A live card that
  parks hands off to the inbox and stops owning the review.
- **No-candidate park exits** — the 8b dead-end gets working actions (reject required; keep-untagged
  if cheap — design in-ticket).
- **Boot reconciliation agreement** — job/review state agree after a restart mid-resolve
  (pulls in backlog **T-033**; the inbox makes its orphan *reachable*, this makes the state *correct*).
- **Console reskin** — token palette, a big centred crest (OutKast-style badge), the 36-bar EQ beat
  animation, cover art where it genuinely exists (landed tracks only; see the ADR-018 amendment and the
  2026-08-05 review-tightening that dropped the always-on duplicate swatch).

## 3. Explicitly out of scope

- **Candidate thumbnails in the picker.** The `track.review_required` event carries `{title, artist,
  score}` only — a recording lookup can't reach cover art (**ADR-010**). Thumbnails need a new
  per-candidate art lookup (cost, may not resolve). Deferred; its own future ticket if wanted.
- **Full job-card restore on reload (backlog T-032).** By ADR-017's model **job cards are ephemeral
  theatre**; the durable surface is the inbox, which this slice delivers. Restoring transient job
  cards is a separate, lower-value improvement — stays in the backlog, updated note.
- **Landed history / a "recently added" ledger.** Not asked for; Jellyfin owns the library view.
- **The migrate/playlist firehose itself** — that's R2. R1.1 just makes the queue it will fill *real*.

## 4. Flow (signed off — the design gate)

The eight scenario screens are the contract. Two surfaces on the home screen:

- **Job cards** — transient. Appear on paste, run the pipeline, disappear on reload.
- **Needs-review inbox** — durable. Loaded from `GET /api/reviews` on every cold open, always
  present (even empty).

Hand-off on a weak/ambiguous park: the card resolves to a one-line *"→ moved to review"* and the song
appears as an inbox row. Reviewing (weak-match pick / duplicate keep-which) happens **in the inbox
row**, expanded in place. Resolving removes the row and shows a brief landed confirmation. See the
design artifacts for every state including the three edge cases.

## 5. Behaviour details

- **Cold load:** client calls `GET /api/reviews`, renders one inbox row per parked review. Empty →
  the resting "nothing waiting" state. This is the whole fix for the §7 "can still be resolved" gap.
- **Live freshness:** while the app is open, a park appends to the inbox off the `track.review_required`
  SSE event; a resolve removes it. No manual refresh.
- **Hand-off:** a card entering `review_required` no longer *hosts* `ReviewPanel`; it emits the
  hand-off note and the inbox takes over. `ReviewPanel` re-homes into the inbox row.
- **No-candidate park (the 8b fix):** a park whose review has **empty candidates** must render working
  exits, never a dead panel. **Reject** (discard + delete staging) is required. **Keep-untagged** (land
  the file as-is under a fallback path, no MusicBrainz tags) is included **only if** it's cheap on the
  backend — design in T-103, don't pre-commit; if it needs real land-without-tag machinery, reject-only
  ships R1.1 and keep-untagged is deferred.
- **Boot reconciliation (T-033):** the two boot sweeps in `JobWorker.start` must agree. Mirror
  `_repark_after_release` (T-029): reconcile reviews first, then fail only jobs with **no** pending
  review — a job whose reset review points back at it settles to `review`, not `error`. Covered by a
  test driving both sweeps against a `running`-job + `resolving`-review pair.

## 6. Interfaces

No new backend routes for the core inbox — it consumes existing ones:

- `GET /api/reviews` — the parked queue (T-014). **Now consumed by the client** (was unwired).
- `GET /api/reviews/{id}`, `POST /api/reviews/{id}/resolve` — unchanged; the inbox row drives them.
- **Possible new work, scoped in-ticket:** a resolve path for a **no-candidate** review (reject; and
  keep-untagged if pursued) — T-103 decides whether the existing `resolve` shapes cover it or a third
  shape is needed. The boot-reconciliation fix (T-104) is server-internal, no route change.

## 7. Visual identity — Console (signed off)

Dark-native broadcast **console**, IBM Plex Sans + Plex Mono, cyan `#3fb6d8` accent (desaturated so the
amber/green/red semantics out-shout it), segmented-LED progress rail. A **big centred crest** (OutKast-
style badge, 3D crown, CLEAN/MUZIK block letters) replaces the old soundwave wordmark, and a **36-bar EQ
beat animation** across the console base replaces the single ambient line (frozen under
`prefers-reduced-motion`). This is the **ADR-018 amendment (2026-08-04)** — the console direction
supersedes the earlier "Signal Path" screens and deliberately reverses their "no spectrum bars" clause.
Canonical form is the shipped code (`11b6302` + `819f22c`), not a flat screen. Do not re-skin without a
decision.

## 8. Acceptance checklist (R1.1 is "done" when…)

**R1.1 met — closed out 2026-08-05.** Each box carries its receipt.

- [x] After a **backend restart** (or just a browser reload), a parked review **appears in the inbox**
      on cold load and can be **resolved to a landed track** — the R1 §7 item, now true through the UI.
      *(T-101 cold-load browser `/verify` 2026-07-24; T-106 end-to-end `/verify` 2026-08-05 — parked →
      process restart → route-resolve → landed MP3.)*
- [x] A **weak-match** park is reviewed and landed **from the inbox**, not from a live card.
      *(T-102 owner browser verify `027a5db`; T-106 verify drove re-search + resolve from the inbox row.)*
- [x] A **duplicate** park is resolved from the inbox (keep-mine / replace / keep-both).
      *(Owner browser verify 2026-08-05 — real Jay-Z "My 1st Song" parked as a duplicate, resolved via
      **Replace** from the inbox; explicit landed, clean removed.)*
- [x] A **no-candidate** park shows working exits (at least **reject**), never a dead panel — the
      2026-07-23 bug is gone. *(T-103 both exits `/verify`; T-040 re-test 2026-08-05 confirmed all three —
      reject / re-search / keep-untagged — land.)*
- [x] The review lifecycle no longer lives in `TrackCard` (ADR-017): a card that parks hands off and
      the review survives the card unmounting. *(T-102 `58c0fea`, owner-verified `027a5db`.)*
- [x] A restart with an **in-flight resolve** leaves `job` and `review` in **agreement** (T-033),
      covered by a two-sweep test. *(T-104 `/verify` 2026-07-24, two-sweep test in the suite.)*
- [x] The app renders in the **Console** skin (ADR-018 as amended): centred crest, EQ beat bars, art
      where it genuinely exists. *(T-105 merged `cb66c80`; dup-panel art fix confirmed in the 2026-08-05
      duplicate verify above.)*
- [x] A review parked before a **machine reboot** is still resolvable after it — its staging audio lives
      somewhere durable, not in the system temp, and orphaned staging dirs are swept at boot (T-106).
      *(T-106 `/verify` 2026-08-05 — kill+relaunch, orphan swept, parked file survived, resolved.)*
- [x] Green on `main`, both suites, per the DoD. *(2026-08-05: server 432, client 65.)*

## Design artifacts (the signed-off gates)

- **Flow gate** (8 scenario screens): `docs/r1/design/review-inbox-flow.html`
- **Visual directions** (the three-way pitch): `docs/r1/design/visual-directions.html`
- **Signal Path** (superseded predecessor — kept for lineage): `docs/r1/design/signal-path-tweaked.html`.
  The shipped **Console** direction (ADR-018 amendment) lives in code (`11b6302` + `819f22c`), not a screen.

---

*Per the DoD: each acceptance item is proven by `/verify` driving the real flow (the inbox is a
platform-behaviour surface — `EventSource` freshness, cold-load hydration — so it needs a real
browser, per ADR-016's note that the gate narrows but doesn't remove `/verify`). Corrections →
`docs/learnings.md`.*
