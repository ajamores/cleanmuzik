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

- **On `main`, clean tree.** T-026 built, browser-verified, landed + pushed.
- **R1 at its shipping line.** Remaining: **T-020 / T-022 / T-027** (browser/latent trio).

## Just landed — T-026 (album/playlist note)

A URL naming one song but carrying a curated `list=` shows a card note: only the named song was
taken (whole-list download is R2). `curated_list_kind(url)` → "album" (`OLAK5uy_…`) / "playlist"
(`PL…`) / None — an **allowlist**, so it never nags on `RD…`/`LL`/`WL`/`UU`. Two `/code-review`
passes folded in: an allowlist (was RD-denylist) and `list_kind` on the resolve-reopen too.
Browser-verified on isolated `:8100`. Owner's acquire workflow → PRD §3.

## Next session, in order

1. **`/code-review` the T-026 post-review delta** (owner deferred it here): the album/playlist
   split + allowlist + reopen fix landed after the last review, covered by tests + browser but not
   yet its own review pass. `git show` the T-026 commit, or diff against `986ff43`'s parent.
2. Then the browser/latent trio **T-020 / T-022 / T-027**.

## Notes for later (not blocking)

- **Reload loses all cards.** `App.tsx` holds the job list in component state and doesn't restore
  it across a browser reload — so T-026's finding-#0 (note lost on reload) is latent until a
  *job-restore-on-reload* capability exists. The server fix + its unit test cover the mechanism now.

## Verifying

- Owner's real servers: `:8137` (uvicorn, real library — **do NOT POST jobs to it**) + `:5173`.
- **Browser `/verify` works here** (Playwright MCP over an isolated `:8100` backend). The T-026
  harness (`scratchpad/verify_server.py` — patches `run_pipeline`/`run_resolve` `__kwdefaults__`
  with offline fake stages + temp `DB_PATH`; a `vite.verify.config.ts` proxying `/api`→`:8100` on
  `:5273`) was a throwaway — rebuild from this note if needed. Hazard: WSL `/mnt/c` Vite serves a
  **stale bundle** — start with `--force` (`learnings.md` 2026-07-21).

## Recent sessions (rolling — last 2–3)

### 2026-07-21 (pm) — T-026 built + verified + landed
- Decision (c); album/playlist allowlist; two review passes (findings #0 reopen, #1 allowlist);
  browser-verified 3 note cases + resolve-survival on isolated `:8100`. Cosmetic ResolveError trim
  also landed earlier this session.

### 2026-07-21 (pm) — T-029 browser checks #4/#7 PASS → T-029 fully done
- Browser harness on isolated `:8100` proved #7 (no blank-row flash) and #4 (fallback remount
  re-enables buttons). Filed the stale-Vite-bundle trap.

## Where the rest of the context lives

- **Durable stores:** `docs/r1/adr.md` · `docs/learnings.md` · `docs/r1/tickets.md` ·
  `docs/backlog/` · `docs/r1/spec.md` · `docs/r1/architecture.md` · `cleanmuzik-prd.md` · git.
  Read order in `CLAUDE.md`.
- **Business/vault context** — the garden, via `/garden`.
