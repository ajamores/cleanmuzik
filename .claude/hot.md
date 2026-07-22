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

- **On `main`, clean tree.** Suites green: **server 379, client 33**, lint + tsc clean.
- **T-020 (the last R1 ticket) is BUILT + MERGED, but NOT done** — `/code-review` (DoD step 1) has
  not run. It's **owner-run** (disabled for model invocation), deferred to next session by owner's
  call. Landed `0007c3c` so the code is in the tree, but the review gate is open.
- **⟹ NEXT ACTION (next session): run `/code-review` on the T-020 diff** (`git show 0007c3c`, or
  the working diff before this session's commits). Only after it passes is T-020 done and every R1
  ticket closed.
- **Then — owner decision:** flip `docs/roadmap.md` R1 `in-build` → `shipped` and move R2
  (`backlog`: playlists, migrate + clean) to `specing`. R1 **cannot ship until the review passes.**

What T-020 changed (durable receipt + 4 T-016 nits + reconnect latch fix): commit `0007c3c` body +
the `tickets.md` T-020 block; corrections in `learnings.md`. Not restated here.

## Candidate backlog item (not filed yet)

- **Reload loses all cards.** `App.tsx` holds the job list in component state; a browser reload
  drops it. Latent until a job-restore-on-reload story exists — likely an R2/UI backlog ticket.

## Verifying

- Owner's real servers: `:8137` (uvicorn `--reload`, real library — **do NOT POST jobs to it**) +
  `:5173`. Editing a startup-state module (`db.py`) re-runs the lifespan on the live DB; the T-020
  column migration already ran there (idempotent, nullable — harmless).
- Browser `/verify` needs an **isolated** stack (temp DB + monkeypatched `LIBRARY_DIRECTORY` — a
  hardcoded constant, not env-configurable — on spare ports); start Vite with `--force` (WSL stale
  bundle). The Vite proxy masks a hard backend kill from `EventSource` (learnings 2026-07-21).

## Recent sessions (rolling — last 2–3)

### 2026-07-21 — T-020 built + merged (last R1 ticket); review gate still open
- Durable receipt + 4 nits + latch fix landed `0007c3c`. `/code-review` NOT run (owner-run, disabled
  for model) — deferred to next session; T-020 not "done" until it passes. Browser verify surfaced
  the Vite-proxy `onerror` masking + the `unicode-bidi` bug (both → learnings).

### 2026-07-21 — T-027 done (channel-URL guard + front-door reject)
- Reproduce-first found the real hole (channel/@handle downloads whole channel). C+A fix, landed `704da64`.

## Where the rest of the context lives

- **Durable stores:** `docs/r1/adr.md` · `docs/learnings.md` · `docs/r1/tickets.md` ·
  `docs/backlog/` · `docs/r1/spec.md` · `docs/r1/architecture.md` · `cleanmuzik-prd.md` · git.
  Read order in `CLAUDE.md`.
- **Business/vault context** — the garden, via `/garden`.
