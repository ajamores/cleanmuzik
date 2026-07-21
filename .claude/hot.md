---
type: meta
title: "Hot — cleanmuzik"
updated: 2026-07-21
tags:
  - meta
  - hot-cache
status: evergreen
---
# Hot — cleanmuzik (personal YouTube → Jellyfin music tool)

> This repo's own working-memory board — session continuity, loaded at session start via `/hot`.
> A cache, not a journal: rewritten each save, never appended to. Durable knowledge lives in this
> repo's stores (`docs/r1/adr.md` · `docs/learnings.md` · `docs/r1/tickets.md` · `docs/backlog/` ·
> git); business/vault learnings go to the garden via `/graft`.

## What this repo is

CleanMuzik — personal YouTube → Jellyfin music tool. Purpose, stack, constraints and read-order
are in `CLAUDE.md`; scope in `cleanmuzik-prd.md`. Not restated here.

## Current State (2026-07-21)

- **On `main`, clean tree.** T-029 fully done; cosmetic trim landed + pushed (see below).
- **R1 at its shipping line.** Remaining items are post-exit findings: **T-026** (owner decision,
  in progress) and the browser/latent trio **T-020 / T-022 / T-027**.

## Just landed — cosmetic trim (committed + pushed)

Dropped the internal `/tmp` staging path from the owner-facing `ResolveError` note
(`import_seam.py`) — now just the recording id. High-effort `/code-review` flagged an added
`logger.warning` as a duplicate of the downstream log at `jobs.py:592`; removed it (owner chose
"remove"). Failure still logged there with `review_id`; `staging_path` recoverable from the row.

## Next session, in order

1. **T-026 (active)** — needs an owner decision recorded in the ticket. Options a/b/c; **(c)** —
   "accept, but have the UI say 'this URL was part of a playlist — only the named song was taken'"
   — is strongest (additive, refuses nothing, no id-prefix taxonomy). Done when the decision is
   recorded with its reason and, for (b)/(c), the behaviour is observed in a browser vs a real
   album URL (`music.youtube.com/watch?v=TRACK&list=OLAK5uy_…`).
2. Then the browser/latent trio **T-020 / T-022 / T-027**.

## Verifying

- Owner's real servers: `:8137` (uvicorn, real library — **do NOT POST jobs to it**) + `:5173`.
- **Browser `/verify` is doable here** (Playwright MCP over an isolated `:8100` backend) — proven
  on T-029. Hazards: (1) a long-lived Vite dev server serves a **stale bundle** on WSL `/mnt/c`
  (inotify miss) — restart with `--force`, confirm served source (`learnings.md` 2026-07-21);
  (2) a park is **non-deterministic** (AcoustID/MB) — force it for a reproducible one.

## Recent sessions (rolling — last 2–3)

### 2026-07-21 (pm) — cosmetic trim landed
- Trimmed the staging path from the owner-facing ResolveError note; high-effort review, one
  low-sev cleanup finding resolved. Committed + pushed. T-026 is next.

### 2026-07-21 (pm) — T-029 browser checks #4/#7 PASS → T-029 fully done
- Browser harness on isolated `:8100` proved #7 (no blank-row flash) and #4 (fallback remount
  re-enables buttons). Filed the stale-Vite-bundle trap. Tickets + learnings updated.

## Where the rest of the context lives

- **Durable stores:** `docs/r1/adr.md` · `docs/learnings.md` · `docs/r1/tickets.md` ·
  `docs/backlog/` · `docs/r1/spec.md` · `docs/r1/architecture.md` · `cleanmuzik-prd.md` · git.
  Read order in `CLAUDE.md`.
- **Business/vault context** — the garden, via `/garden`.
