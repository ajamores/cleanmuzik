---
type: meta
title: "Hot — cleanmuzik"
updated: 2026-08-18
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

## Current State (2026-08-18)

- **On `main`, tree clean, pushed. 650 tests green.** R2 (Playlists) `in-build`.
- **T-306 done + pushed** — the last silent gap in the append seam is closed: a batch member that
  **parked at import and is resolved later** via `/api/reviews` now joins its playlist. `run_resolve`'s
  landed branch records a pending membership (path, NULL item id) exactly as `run_pipeline` does; the
  reconcile pass gained a **create-if-missing** branch (NULL container → create + persist, double-create
  guarded). **Live-verified 9/9 against real Jellyfin** — a parked member's durable row auto-created a
  real playlist and landed the track in it, idempotent across a simulated restart.
- Four out-of-scope `/code-review` findings from T-306 triaged. #1 **stale/deleted non-null playlist-id
  never recovered** promoted to its own R2 ticket **T-315** (`tickets.md`, Phase C, todo) — it's a
  robustness gap in a shipped R2 feature, so it rides R2 per the active-release-bugs rule. #2–#4 stay as
  T-306 deferred follow-ups (cosmetic / latent / single-user-negligible): stuck-ceiling measured from
  `created_at`; stuck-row drain starvation (T-313 lineage); `resolve_user_id` cache no invalidation (T-314).

## ⟹ NEXT

1. **The batch spine (Phase C→E), in order:** **T-305** batch-scoped SSE → **T-312** durable batch
   state + reconnect → **T-310** batch card (renders `stuck_since`) → **T-308** (`git mv
   docs/backlog/T-037.md docs/r2/`).
2. **T-307** — idempotent re-paste (rides T-303 + T-304's idempotent append; buildable).
3. **T-311** — the FULL end-to-end `/verify` (whole acceptance checklist). Needs the batch spine above;
   item 4 (parked→resolved→appends) is now separately live-proven by T-306.

## Recent sessions (rolling — last 2–3)

- **2026-08-18 (this session)** — Built + pushed **T-306** directly on `main`. Live `/verify` proved
  create-if-missing against real Jellyfin. Review findings triaged (1 fixed in code, 4 filed).
- **2026-08-17** — Built + merged **T-313** then **T-314**; playlist append works live for the first time
  (real track in a real Jellyfin playlist). Shipped **T-303** (exact-video dedup) earlier.

## Where the rest of the context lives

`docs/roadmap.md` (R2 `in-build`) · `docs/r2/spec.md` + **`tickets.md`** (T-300–304, T-313, T-314, **T-306**
done; T-305/T-312/T-310/T-308/T-307/T-311/**T-315** open) · `docs/r1/adr.md` (**ADR-027 seam-1**; create-if-missing
is the settled null-case guard) · `docs/learnings.md` · `docs/workflow.md` · `docs/backlog/` (T-037). Business → `/graft`.
