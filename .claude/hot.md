---
type: meta
title: "Hot — cleanmuzik"
updated: 2026-08-19
tags:
  - meta
  - hot-cache
status: evergreen
---
# Hot — cleanmuzik (personal YouTube → Jellyfin music tool)

> This repo's own working-memory board — session continuity, loaded at session start via `/hot`.
> A cache, not a journal: rewritten each save, never appended. Durable knowledge lives in this repo's
> stores (`docs/roadmap.md` · `docs/r1/adr.md` · `docs/r2/` · `docs/backlog/` · `docs/learnings.md` · git);
> business learnings go to the garden via `/graft`.

## What this repo is

CleanMuzik — personal YouTube → Jellyfin music tool. Purpose, stack, constraints, read-order in
`CLAUDE.md`; scope in `cleanmuzik-prd.md`. Not restated here.

## Current State (2026-08-19)

- **On `main`.** Uncommitted: `docs/learnings.md` (this save's yt-dlp entry) + this board; `.vscode/` untracked.
  **683 server + 91 client tests green.** R2 (Playlists) `in-build` — batch spine now essentially done
  (T-300–307/T-310/T-312/T-313/T-314 all merged).
- **Three commits landed today** (detail in git): **T-307 closed** (idempotent re-paste — no prod delta, it
  emerged from shipped seams; the deliverable was the composition proof), **yt-dlp 2026.7.4→2026.8.19** (fixed
  a total 403 download blackout on the first live batch — stale pin, see learnings), **T-216** (bounded the
  Cover Art fetch: timeout 10→5, cap kept at 3 for recall — live-verified ~39s→~26s/track).
- **Live run left running:** `May2024pt2` sits ~22 done / 23 parked in the review inbox / 31 error — but **most
  errors are dev-server restarts** (my kills + `--reload` edits re-erroring in-flight jobs), not pipeline
  failures. A re-paste (T-307) retries the errored, skips the landed.
- Servers may still be up: uvicorn `:8137` + vite `:5173`, both running the new code.

## ⟹ NEXT

1. **Owner wants to try a different experiment** (his words, 2026-08-19 — details pending; ask before assuming).
2. **T-308 / T-309** — the T-037 tag fixes (`git mv docs/backlog/T-037.md` context): artist-credit
   normalisation in the write path (ADR-028 filed), and the genre-report read-off-disk bug.
3. **T-315** — recover a stale/deleted Jellyfin playlist id (create-if-missing only guards NULL).
4. **T-311** — the FULL end-to-end `/verify` (whole acceptance checklist); carries T-307's live re-paste.
5. Backlog speed follow-ons if wanted: **T-217** (Jellyfin scan debounce, filed), **T-215** (Shazam overlap),
   **T-208** (MB de-hydration — R2.5-deferred, engine change).

## Recent sessions (rolling — last 2–3)

- **2026-08-19 (this session)** — Closed **T-307**. Then, driving a real batch: diagnosed + fixed the **yt-dlp
  403 blackout**; dispatched an agent to profile the pipeline (~35–40s/track), built **T-216** (Cover Art tail
  bound — `/code-review` caught an art-recall regression in the first draft, reverted to a recall-preserving
  shape), filed **T-216/T-217** to backlog. Solo (Opus).
- **2026-08-19 (earlier)** — Built + merged **T-310** (batch aggregate card + acquire dial).
- **2026-08-18** — Built + merged **T-312** (durable batch snapshot) and **T-305** (batch-scoped SSE).

## Where the rest of the context lives

`docs/roadmap.md` (R2 `in-build`) · `docs/r2/tickets.md` (**T-308/T-309/T-315/T-311 open**; rest done) ·
`docs/r1/adr.md` (ADR-027 batch model · ADR-028 artist-credit · ADR-029 acquire dial) ·
`docs/learnings.md` (**2026-08-19: yt-dlp 403 = stale pin**; T-310 reload-orphan + stream-race traps) ·
`docs/backlog/` (**T-216 built · T-217** · the T-208/214/215 speed family · T-037). Business → `/graft`.
