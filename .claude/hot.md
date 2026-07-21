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

- **On `main`, clean tree** after committing + pushing the T-029 close-out (learnings + tickets + this
  board). Verify throwaways deleted, isolated verify servers stopped.
- **T-029 is fully DONE** — both browser checks now PASS against the fixed bundle (details below).
- **R1 at its shipping line.** Remaining R1 items are post-exit findings: **T-026** (owner decision
  a/b/c) and the browser/latent trio **T-020 / T-022 / T-027**.

## Just landed — T-029 browser checks #4 + #7 (PASS)

Drove the real UI (Playwright) over the isolated `:8100` backend; both checks pass against the fixed
bundle. Full receipts + method are in the T-029 ticket; the stale-bundle trap that cost the first run
is in `docs/learnings.md` 2026-07-21. Nothing left open on T-029.

## Next session, in order

1. **Cosmetic — trim the re-park message.** It still tails the internal staging path
   (`…cannot apply it to /tmp/…/song.mp3`); drop the path from the owner-facing note, keep it in logs.
2. **T-026** needs your call (a/b/c in its ticket; (c) — "part of a playlist, took the named song" —
   looks strongest). Then the browser/latent trio T-020/T-022/T-027.

## Verifying

- Owner's real servers: `:8137` (uvicorn, real library — **do NOT POST jobs to it**) + `:5173`. Left alone.
- **Browser `/verify` is doable here** (Playwright MCP over an isolated backend) — proven on T-029.
  Two standing hazards: (1) a long-lived Vite dev server serves a **stale bundle** on WSL `/mnt/c`
  (inotify miss) — restart with `--force` and confirm the served source before trusting it
  (`docs/learnings.md` 2026-07-21); (2) a park is **non-deterministic** (AcoustID/MB), so force it if
  you need a reproducible one. The T-029 browser harness (isolated launcher with three test-only
  monkeypatches + a verify Vite config) was a throwaway — rebuild from the ticket if needed.

## Recent sessions (rolling — last 2–3)

### 2026-07-21 (pm) — T-029 browser checks #4/#7 PASS → T-029 fully done
- Built a browser harness on the isolated `:8100`; proved #7 (no blank-row flash) and #4 (fallback
  remount re-enables buttons). Caught + filed the stale-Vite-bundle trap. Updated tickets + learnings.

### 2026-07-21 (am) — T-029 second review pass, landed + pushed
- `/code-review` (high) second pass: 7 findings fixed, 8 regression tests. Committed T-029 to `main`,
  pushed. Browser #4/#7 were deferred here — now closed above.

## Where the rest of the context lives

- **Durable stores:** `docs/r1/adr.md` · `docs/learnings.md` · `docs/r1/tickets.md` ·
  `docs/backlog/` · `docs/r1/spec.md` · `docs/r1/architecture.md` · `cleanmuzik-prd.md` · git.
  Read order in `CLAUDE.md`.
- **Business/vault context** — the garden, via `/garden`.
