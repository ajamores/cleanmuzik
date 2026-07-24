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

---

### T-101 — Review inbox: client consumes `GET /api/reviews` on cold load
- **Status:** todo
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
- **Status:** todo
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
- **Status:** todo — **HIGH** (real bug, pre-existing on `main`).
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

### T-105 — Signal Path reskin (wordmark A, ambient line, art where real)
- **Status:** todo
- **Depends on:** T-101, T-102 (skin the finished structure, not a moving target)
- **Agent:** front-end
- **What:** Replace the current tokens with the **Signal Path** palette (dark-native, cyan `#3fb6d8`
  accent, Plex Sans + Plex Mono — inline the faces as data URIs, no CDN). Wordmark **A** (soundwave seal
  + script "Muzik", the seal hand-drawn SVG). The segmented-meter rail. **One** ambient signal line in
  the background at ~7% opacity, frozen under `prefers-reduced-motion` — **no spectrum bars**. Cover art
  on landed tracks + the owned side of a duplicate; the picker stays text+score (ADR-010). Design tokens
  + markup are in `docs/r1/design/signal-path-tweaked.html`. This is **ADR-018**.
- **Done when:** the app renders in Signal Path per the artifact — wordmark A, the single ambient line,
  art where it exists, no spectrum — light/dark both legible, reduced-motion honoured. Ties to §8 item 7.

---

## Not pulled into R1.1 (stay in the backlog)

- **T-032** (browser reload loses job cards) — **deferred by design.** ADR-017 makes job cards
  ephemeral theatre; the durable surface is the inbox, which R1.1 delivers. Restoring transient cards is
  separate and lower-value. Note updated in `docs/backlog/T-032.md`.
- **T-030 / T-023** (Jellyfin lyrics second-scan) and **T-031** (album recovery) — R2/migrate concerns.
- **Candidate-art thumbnails in the picker** — deferred per ADR-010 (needs a per-candidate art lookup).
