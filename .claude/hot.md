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

- **On `main`, nothing in flight, tree clean.** R2 (Playlists) `in-build`, **635 tests green on main**.
- **T-313 done + merged** — the reconcile reframe that fixes T-304's 3 bugs. Retired the give-up tally
  (dead column), 3-state `resolve_item_id` (RESOLVED/NOT_INDEXED/UNREACHABLE, `RESOLVED(None)`
  unconstructible), idempotent append via per-pass pre-check (`get_playlist_item_ids`), no-penalty on the
  append organ, and `playlist_members.stuck_since` (wall-clock, visible+retried). Carries the ADR-027
  seam-1 amendment; supersedes backlog T-047. `/code-review high` clean after 5 findings resolved.
- **⚠ Live discovery (now the first work of T-311):** T-313's `/verify` was the first real look at the
  Jellyfin append path and **two pre-existing T-304/T-302 seams are non-functional** — (1)
  `resolve_item_id`'s `Path=` filter is **ignored** by the live server (returns the whole library →
  `items[0]` is the library-root Folder id, not the track); (2) `create_playlist` **400s** and zero
  playlists exist. Filed with evidence + fix candidates on **T-311**; a learning is in `learnings.md`.
  **Not a T-313 regression** — its reconcile logic is correct regardless of which id resolve returns, and
  its own new-code mappings (UNREACHABLE/None/NOT_INDEXED) ARE live-verified.

## ⟹ NEXT

1. **T-306** — resolve-path membership write (the live review-approve silent gap); rides T-313's
   idempotent append. Buildable now.
2. **T-311's two live-seam fixes** — the `Path=` exact-lookup + `create_playlist` 400 (userId?). These
   now gate the end-to-end happy-path observable; owner may want them pulled early since the append path
   is currently non-functional live. Evidence is already on the ticket.
3. **T-305 — batch-scoped SSE** (truthful counts now the seam is fixed) → **T-312** durable batch state →
   **T-310** batch card (renders `stuck_since`) → **T-308** (`git mv docs/backlog/T-037.md docs/r2/`).

## Recent sessions (rolling — last 2–3)

- **2026-08-17 (this session)** — Built + merged **T-313** (Fable planned, Opus executed). 5 review
  findings resolved; live `/verify` surfaced the two T-304/T-302 seam bugs → filed on T-311.
- **2026-08-17 (earlier)** — Shipped **T-303** (exact-video dedup). Two councils settled T-304's fix as
  T-313; rejected push + batch-at-end; found the review-approve membership gap (→ T-306).
- **2026-08-17 (earlier)** — Shipped **T-304** defer-first Jellyfin playlist seam (the one T-313 hardened).

## Where the rest of the context lives

`docs/roadmap.md` (R2 `in-build`) · `docs/r2/spec.md` + **`tickets.md`** (T-300–304 + **T-313** done;
**T-311** carries the two live-seam findings; T-306 buildable now) · `docs/r1/adr.md` (**ADR-027 seam-1
amendment last filed**, T-313) · `docs/learnings.md` (T-313 live-API lesson) · `docs/workflow.md` ·
`docs/backlog/` (T-047 superseded). Business → `/graft`.
