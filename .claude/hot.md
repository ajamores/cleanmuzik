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
- **R1's BUILD IS COMPLETE — every R1 ticket is done.** T-020, the last one, landed (`0007c3c`).
- **Owner decision pending:** `docs/roadmap.md` still says R1 `in-build`. Flipping R1 →
  `shipped` and moving R2 (`backlog`: playlists, migrate + clean) to `specing` is a release
  milestone — the owner's call, not auto. R2 pulls backlog tickets in only when it's specced.

T-020 receipt (durable landing receipt + 4 T-016 nits + a reconnect latch fix) is in the commit
body of `0007c3c` and the `tickets.md` T-020 block; two corrections are in `learnings.md`
(the Vite-proxy `onerror` masking; `unicode-bidi:plaintext` hiding the filename). Not restated here.
`/code-review` on the diff is still owed — it's **owner-run** (disabled for model invocation).

## Candidate backlog item (not filed yet)

- **Reload loses all cards.** `App.tsx` holds the job list in component state; a browser reload
  drops it. Latent until a job-restore-on-reload story exists — likely an R2/UI backlog ticket.

## Verifying

- Owner's real servers: `:8137` (uvicorn `--reload`, real library — **do NOT POST jobs to it**) +
  `:5173`. Editing a startup-state module (`db.py`) re-runs the lifespan on the live DB; the T-020
  column migration already ran there (idempotent, nullable — harmless).
- Browser `/verify` needs an **isolated** stack (temp DB + monkeypatched `LIBRARY_DIRECTORY`, spare
  ports) — `LIBRARY_DIRECTORY` is a hardcoded constant, not env-configurable. Rebuild the harness
  from this session's notes if needed; start Vite with `--force` (WSL stale-bundle hazard). Know the
  Vite proxy masks a hard backend kill from `EventSource` (learnings 2026-07-21).

## Recent sessions (rolling — last 2–3)

### 2026-07-21 — T-020 done (last R1 ticket); R1 build complete
- Durable receipt + 4 nits + latch fix, `/code-review` is owner-run (disabled for model). Browser
  verify surfaced the Vite-proxy `onerror` masking + the `unicode-bidi` bug (both → learnings).

### 2026-07-21 — T-027 done (channel-URL guard + front-door reject)
- Reproduce-first found the real hole (channel/@handle downloads whole channel). C+A fix, landed `704da64`.

## Where the rest of the context lives

- **Durable stores:** `docs/r1/adr.md` · `docs/learnings.md` · `docs/r1/tickets.md` ·
  `docs/backlog/` · `docs/r1/spec.md` · `docs/r1/architecture.md` · `cleanmuzik-prd.md` · git.
  Read order in `CLAUDE.md`.
- **Business/vault context** — the garden, via `/garden`.
