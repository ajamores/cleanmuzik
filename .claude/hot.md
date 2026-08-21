---
type: meta
title: "Hot — cleanmuzik"
updated: 2026-08-20
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

## Current State (2026-08-20)

- **On `main`, clean tree** (only `.vscode/` untracked). **723 server tests green on main.** Ahead of
  `origin/main` by **8 commits — not pushed** (push is the owner's call).
- **T-315 SHIPPED** — merged to `main` (`f9afe83` + merge `5241f67`). A **deleted** Jellyfin playlist id
  is now recovered: the pre-check returns a 3-state `PlaylistProbe` (READABLE / ABSENT / UNREADABLE);
  a positive **404 = ABSENT** → re-create the container + rebuild it from `playlist_members` (re-queue
  already-appended members too, not just pending); UNREADABLE (outage) defers, never re-creates.
  `/code-review high`: F1/F3/F4 fixed, F2/F5 declined — all adjudicated in the ticket.

## ⟹ NEXT

1. **T-311** — the FULL end-to-end `/verify` (whole R2 acceptance checklist). It now also owns two
   deferred live proofs: T-315's **404-vs-200-empty** assumption (does a deleted playlist's `/Items`
   GET actually 404?) and the playlist recovery across a restart. This is the last open R2 ticket.
2. Backlog speed follow-ons if wanted: **T-217** (Jellyfin scan debounce), **T-215** (Shazam overlap),
   **T-208** (MB de-hydration — R2.5-deferred, engine change).

## Recent sessions (rolling — last 2–3)

- **2026-08-20 (this session)** — Shipped **T-315** (recover a deleted playlist id). 3-state pre-check +
  re-create/rebuild path; applied review F1 (rebuild from source-of-truth), F3 (dropped frozen), F4
  (log re-precheck); declined F2/F5. Merged to main (723 green). Solo (Opus).
- **2026-08-20 (earlier)** — Closed **T-309** (genre off disk); filed **T-050**. 714 green.
- **2026-08-19** — Shipped **T-308** (ADR-028 credit fold); filed **T-049**. Built T-309; closed T-307;
  fixed the yt-dlp 403; built **T-216**.

## Where the rest of the context lives

`docs/roadmap.md` (R2 `in-build`) · `docs/r2/tickets.md` (**T-311 open**; T-308/309/310/315 done) ·
`docs/r1/adr.md` (ADR-027 batch model · ADR-028 artist-credit · ADR-029 acquire dial) ·
`docs/learnings.md` (yt-dlp 403 = stale pin; T-310 reload-orphan + stream-race traps) ·
`docs/backlog/` (**T-050** lyrics-lag · **T-049** ADR-028 field-coverage · T-216/217 · T-208/214/215).
Business → `/graft`.
