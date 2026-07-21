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

- **On `main`, clean tree** after the T-029 landing (pushed to `origin/main`).
- **R1 at its shipping line.** Remaining R1 tickets are post-exit findings: **T-026** (owner
  decision a/b/c), and the browser/latent trio T-020/T-022/T-027.

## Just landed — T-029 (on `main`, one loose end deferred)

The failed-resume orphan fix, through **two** high `/code-review` passes. Second pass fixed 7
findings + added 8 regression tests (all red-before/green-after). Suites **331 server / 26 client**
green, build clean, `/verify` **7/7** over the real ASGI stack (`scratchpad/verify_t029.py`).

- **DEFERRED to next session — two browser-only checks** (logic is unit-covered; the environment
  here can't produce them): **#4** the real `EventSource` reconnect *timing* — fail a pick, drop the
  stream, confirm the panel buttons come back alive; **#7** the visual re-park frame — confirm no
  candidate-row flicker on a live re-park. Only these close T-029 fully.

## Next session, in order

1. **The two T-029 browser checks above** (`/verify` in a real browser).
2. **Cosmetic — trim the re-park message.** It still tails the internal staging path
   (`…cannot apply it to /tmp/…/song.mp3`); drop the path from the owner-facing note, keep it in logs.
   Visible in `/verify` check 5. Separate from the 7 findings.
3. **T-026** needs your call (a/b/c in its ticket; (c) — "part of a playlist, took the named song" —
   looks strongest). Then the deferred browser trio.

## Verifying

Dev server was up on **:8137** (real library — **do NOT POST jobs to it**) + **:5173**; the server
edits hot-reloaded it, harmless. Untracked throwaways left uncommitted (clean when convenient):
`.playwright-mcp/`, `client/vite.verify.config.ts`, `scratchpad/` (holds re-runnable `verify_t029.py`).

## Recent sessions (rolling — last 2–3)

### 2026-07-21 — T-029 second review pass, landed + pushed
- `/code-review` (high) second pass: 7 findings fixed, 8 regression tests. Committed the whole T-029
  work to `main` and pushed. Browser #4/#7 deferred. Consulted a QA + SWE agent on fix strategy first.

### 2026-07-20 (pm) — T-019 done; backlog → docs/backlog/; T-029 built
- Committed `8650204`. Built T-029, first `/code-review` (4 findings fixed), `/verify` 7/7; re-review
  deferred to the session above.

## Where the rest of the context lives

- **Durable stores:** `docs/r1/adr.md` · `docs/learnings.md` · `docs/r1/tickets.md` ·
  `docs/backlog/` · `docs/r1/spec.md` · `docs/r1/architecture.md` · `cleanmuzik-prd.md` · git.
  Read order in `CLAUDE.md`.
- **Business/vault context** — the garden, via `/garden`.
