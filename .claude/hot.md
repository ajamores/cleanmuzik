---
type: meta
title: "Hot — cleanmuzik"
updated: 2026-08-17
tags:
  - meta
  - hot-cache
status: evergreen
---
# Hot — cleanmuzik (personal YouTube → Jellyfin music tool)

> This repo's own working-memory board — session continuity, loaded at session start via `/hot`.
> A cache, not a journal: rewritten each save, never appended. Durable knowledge lives in this repo's
> stores (`docs/roadmap.md` · `docs/r1/adr.md` · `docs/r2/` · `docs/backlog/` · git); business
> learnings go to the garden via `/graft`.

## What this repo is

CleanMuzik — personal YouTube → Jellyfin music tool. Purpose, stack, constraints, read-order in
`CLAUDE.md`; scope in `cleanmuzik-prd.md`. Not restated here.

## Current State (2026-08-17)

- **On `main`, nothing in flight, tree clean.** R2 (Playlists) `in-build`, **646 tests green on main**.
- **The playlist append path now WORKS LIVE** — for the first time a real track landed in a real Jellyfin
  playlist through the app code (`/verify`). This closed a feature that had never once functioned against a
  real server (built on API-docs guesses + fake-http tests).
- **T-313 done + merged** — reconcile reframe fixing T-304's 3 bugs (retired the give-up tally, 3-state
  resolve, idempotent append via pre-check, `stuck_since` wall-clock flag).
- **T-314 done + merged** — the two live-seam fixes T-313's `/verify` surfaced: (1) **all playlist ops are
  user-scoped** — `resolve_user_id` auto-discovers the Jellyfin user (`GET /Users`, cached; owner chose
  auto-discover over a `JELLYFIN_USER_ID` setting) and create/append/pre-check now send it; (2)
  **`Items?Path=` is ignored by the live server** — resolve now lists audio items and matches the path
  client-side. `/code-review high` clean after fixing the load-bearing finding (pre-check-`None` no longer
  flags stuck — it's indistinguishable from an outage). ADR-027 seam-1 amended; two concrete Jellyfin API
  facts filed in `learnings.md`.

## ⟹ NEXT

1. **T-306** — resolve-path membership write (the live review-approve silent gap); rides T-313's idempotent
   append. Buildable now, and the seam under it now actually works.
2. **T-305 — batch-scoped SSE** → **T-312** durable batch state → **T-310** batch card (renders
   `stuck_since`) → **T-308** (`git mv docs/backlog/T-037.md docs/r2/`).
3. **T-311** — the FULL end-to-end `/verify` (whole acceptance checklist); needs the batch spine above. Its
   two live findings are now RESOLVED by T-314.
- **Two tracked follow-ups on T-314** (deferred from review, not lost): a per-pass resolve cache (resolve
  lists the audio library per member), and Phase-1 path-remap robustness (exact `Path==` match only holds
  while app + Jellyfin share the same absolute path — Phase 0 localhost).

## Recent sessions (rolling — last 2–3)

- **2026-08-17 (this session)** — Built + merged **T-313** then **T-314** (Fable planned T-313; live spike
  cracked the real Jellyfin API shapes). Playlist append works live for the first time. A history-audit
  agent confirmed the feature had never been live-tested.
- **2026-08-17 (earlier)** — Shipped **T-303** (exact-video dedup). Councils settled T-304's fix as T-313.
- **2026-08-17 (earlier)** — Shipped **T-304** defer-first Jellyfin playlist seam (hardened by T-313/T-314).

## Where the rest of the context lives

`docs/roadmap.md` (R2 `in-build`) · `docs/r2/spec.md` + **`tickets.md`** (T-300–304 + **T-313, T-314** done;
T-311 findings resolved; T-306 buildable) · `docs/r1/adr.md` (**ADR-027 seam-1: T-313 + T-314 amendments**) ·
`docs/learnings.md` (T-313 live-API lesson + T-314 Jellyfin API facts) · `docs/workflow.md` ·
`docs/backlog/` (T-047 superseded). Business → `/graft`.
