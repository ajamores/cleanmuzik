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

- **On `main`, pushed.** Commit `80c74b4` landed **T-021 + T-025**; a follow-up docs commit carries
  the learnings note + this board. Server suite **324 green**.
- **T-021 + T-025 — DONE.** Both were one bug: yt-dlp's `--embed-metadata` junk surviving on
  singletons (MB doesn't overwrite what it doesn't supply). Fixed via **ADR-013** (`from_scratch:
  yes` — MB is the sole tag source) + **ADR-014** (one MB call stamps an original-*ish* year, honest
  proxy). Verified on a real download: `Coming of Age` landed **`date=1996-06-25`** (was 2026) and
  **no genre tag** (was `"Music"`). High-effort review: 5 fixed, 1 accepted, 1 → T-031.
- **T-019 (§7 pass) — closeable.** Its only open gate was #4's genre+year defects; those are now
  fixed and proven on disk. Formal close may want a glance at Jellyfin's genre list (T-021 Done-when).
- **`tickets.md` now has a `## Backlog (post-R1)` section.** T-030 (lyrics 2nd-scan) + T-031 (album
  recovery — new, the F1 escalation) live there; triage into R2 via `roadmap.md`.

## NEXT (owner picks)

1. **Stamp T-019 done** — every §7 item now observed; genre+year proven.
2. **T-022** — JS-runtime download-quality *measurement* (unrelated to tagging; latent). Owner asked.
3. **T-023** — it's a **duplicate of backlog T-030 and contradicts it** (T-023: "not a race, scan
   depth"; T-030: "a race"). Reconcile into one, then a won't-fix call. Owner asked.
4. **T-029** — failed resume leaves job=`error` / row `pending`. Clean back-end fix, HTTP-verifiable.
5. **T-026** — needs an owner decision (a/b/c in `tickets.md`) before code.

## Verifying (learned this session)

Dev server up on **:8137** (real library — **do NOT POST jobs to it**) + **:5173**. The **:8100/:5175**
verify stack from last session runs **stale code** — ignore or kill it. For tagging verifies use the
one-shot temp-library recipe (`docs/learnings.md` 2026-07-20): drive `run_pipeline` against a temp
`LIBRARY_DIRECTORY` + `db_path`, land via `resolve_import` to dodge the flaky AcoustID gate.
Untracked throwaways to clean: `.playwright-mcp/`, `client/vite.verify.config.ts`,
`scratchpad/verify_t021_t025.py`.

## Recent sessions (rolling — last 2–3)

### 2026-07-20 — T-021 + T-025 done
- Traced both to one junk-survival bug; ADR-013 (`from_scratch`) + ADR-014 (year proxy). Real-download
  verify: `date=1996-06-25`, genre blank. Filed T-031 (album recovery) + a Backlog section.

### 2026-07-19 — T-019 §7 verify pass (near-closed)
- Drove every §7 item not needing a browser over HTTP vs :8100; owner confirmed #5 in Jellyfin.
- Only gate left was #4's tag-quality defects — now closed by T-021/T-025.

### 2026-07-20 (earlier) — T-024 row 7 verified → DONE
- Real collab download: `ftintitle` folded "Memphis Bleek" into the title, artist stayed single.

## Where the rest of the context lives

- **Durable stores:** `docs/r1/adr.md` · `docs/learnings.md` · `docs/r1/tickets.md` · `docs/r1/spec.md`
  · `docs/r1/architecture.md` · `cleanmuzik-prd.md` · git. Read order in `CLAUDE.md`.
- **Business/vault context** — the garden, via `/garden`.
