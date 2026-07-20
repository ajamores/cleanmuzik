---
type: meta
title: "Hot — cleanmuzik"
updated: 2026-07-20
tags:
  - meta
  - hot-cache
status: evergreen
---
# Hot — cleanmuzik (personal YouTube → Jellyfin music tool)

> This repo's own working-memory board — session continuity, loaded at session start via `/hot`.
> A cache, not a journal: rewritten each save, never appended to. Durable knowledge lives in this
> repo's stores (`docs/r1/adr.md` · `docs/learnings.md` · `docs/r1/tickets.md` · git); business/vault
> learnings go to the garden via `/graft`.

## What this repo is

CleanMuzik — personal YouTube → Jellyfin music tool. Purpose, stack, constraints and read-order
are in `CLAUDE.md`; scope in `cleanmuzik-prd.md`. Not restated here.

## Current State (2026-07-20)

- **On `main`, pushed.** Working tree clean but for two untracked throwaways. Server suite **324 green**.
- **R1: 22 of 31 done.** Engine + orchestration + SSE + UI + review all shipped and verified live.
- **T-021 + T-025 — DONE** (`80c74b4`), status flipped this session. One junk-survival bug: yt-dlp's
  `--embed-metadata` surviving on singletons. Fixed via **ADR-013** (`from_scratch`) + **ADR-014**
  (one MB call stamps an original-*ish* year, honest proxy). Verified: `Coming of Age` landed
  **`date=1996-06-25`** (was 2026), **no genre tag** (was `"Music"`).
- **T-019 (§7 pass) — closeable.** Its only open gate was #4's genre+year; now fixed and proven on
  disk. Formal close may want a glance at Jellyfin's genre list (T-021 Done-when).
- **Scope-triage is a governed system** (`tickets.md` "How a ticket enters a release" + `roadmap.md`).
  **Backlog** holds T-030 + **T-023** (duplicates — reconcile at triage; T-023's mtime evidence
  wins) + T-031 (album recovery).
- **Graft dropped, not yet ingested** — `2026-07-20-release-scope-is-exit-criteria.md` in the
  garden's `.inbox/pending/`. Inert until a `/garden` run.

## NEXT (owner picks)

0. **In the garden terminal: run `/garden`** to ingest the pending scope-triage graft.
1. **Stamp T-019 done** — every §7 item now observed; genre+year proven.
2. **T-029** — failed resume leaves job=`error` / row `pending`. Clean back-end fix, HTTP-verifiable.
3. **T-026** — needs an owner decision (a/b/c in `tickets.md`) before code.
4. **T-022** — JS-runtime download-quality *measurement* (latent, unrelated to tagging).
5. **T-020** — track-card stream reattach + payload gap (needs a browser that can go offline).

Realistic R1 close: **T-019** (exit gate) + **T-029** (real bug), then the **T-026** decision.

## Verifying

Dev server up on **:8137** (real library — **do NOT POST jobs to it**) + **:5173**; the **:8100/:5175**
stack is last-session stale code — ignore/kill. Tagging-verify recipe (temp library, land via
`resolve_import` to dodge the flaky AcoustID gate) is in `docs/learnings.md` 2026-07-20. Untracked
throwaways to clean: `.playwright-mcp/`, `client/vite.verify.config.ts`, `scratchpad/verify_t021_t025.py`.

## Recent sessions (rolling — last 2–3)

### 2026-07-20 — T-021 + T-025 done; scope-triage systematized
- One junk-survival bug → ADR-013 (`from_scratch`) + ADR-014 (year proxy); verified `date=1996-06-25`,
  genre blank. Filed T-031 + a Backlog section; made triage a governed system; grafted the general
  lesson (pending ingest). Flipped T-021/T-025 → done; moved T-023 to backlog next to its dup T-030.

### 2026-07-19 — T-019 §7 verify pass (near-closed)
- Drove every §7 item not needing a browser over HTTP; owner confirmed #5 in Jellyfin. The only gate
  left was #4's tag defects — now closed by T-021/T-025.

## Where the rest of the context lives

- **Durable stores:** `docs/r1/adr.md` · `docs/learnings.md` · `docs/r1/tickets.md` · `docs/r1/spec.md`
  · `docs/r1/architecture.md` · `cleanmuzik-prd.md` · git. Read order in `CLAUDE.md`.
- **Business/vault context** — the garden, via `/garden`.
