---
type: meta
title: "Hot — cleanmuzik"
updated: 2026-07-18
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

## Current State (2026-07-18)

- **Phase: R1 build. T-014 (review API) is DONE — merged `6da574b`, pushed, `main` level with
  origin, suite green (266).** `main` tree clean bar the untracked `.claude/worktrees/`.
- **T-016 (client track-card SSE) — BUILT, not integrated.** Next to land. On worktree branch
  `worktree-agent-aaffef646dc8b8e5c` @ `3885939`. Reviewed (4 fixes), lint+build green, never driven
  live (rides with T-019's browser round-trip).
- Ledger `docs/r1/tickets.md`: open = **T-016, T-017, T-019**.

## NEXT

1. **Owner wants the OPTIONAL scoped code-review of T-014's fix diff** (`run_resolve` restructure) —
   belt-and-suspenders, "to be sure." Not blocking (already `/verify`'d 26/26 + 3 regression tests),
   but he asked to note it. Scope: just the fix hunks in `server/app/{jobs,reviews,routes/reviews,
   import_seam}.py`, not the whole T-014 diff.
2. **Integrate T-016 onto `main`** (client-only, disjoint from server — clean fan-out merge).
3. **Then T-017** (review panel UI) unblocks — its EventSource MUST reuse T-016's reconcile-on-close
   fallback (guard-rail note already in the T-017 ticket, from finding #4). **T-019** owns the live
   browser round-trip.
4. **Persist the /verify harness** — cold-started this session (isolate `DB_PATH` + patch
   `beets_engine.LIBRARY_DIRECTORY`; stub `resolve_import`/`scan_fn` via `run_resolve.__kwdefaults__`
   since MB is unreachable in-sandbox; drive real app under `TestClient`). Worth a
   `server/.claude/skills/verify/SKILL.md` so the next ticket skips the setup. Driver lives in the
   session scratchpad.

## Recent sessions (rolling — last 2–3)

### 2026-07-18 — T-014 integrated + DONE; 6-finding review; real-app /verify
- Merged T-014 worktree onto `main` (2 test conflicts hand-resolved; `events.py` auto-merge kept both
  `candidate_row` + `EventBus.reopen`). High-effort review → 6 findings, all resolved before landing
  (#1 replace-before-scan rollback + #2 torn-row hang fixed w/ regression tests; #3 claim release;
  #4 no-code adjudication; #5/#6 cleanups). Lesson (resolve-twin commit/close discipline) →
  `learnings.md`. `/verify` PASS 26/26 on the real app.

### 2026-07-17 — T-014 built + verified in isolation; ADR-010; replace-refuse ruling
- T-014 built; its isolation `/verify` caught two data-loss bugs. ADR-010 (candidate = 4 keys) +
  acceptance-check DoD added. Detail: `learnings.md`, `adr.md`.

## Where the rest of the context lives

- **Durable stores:** `docs/r1/adr.md` · `docs/learnings.md` · `docs/r1/tickets.md` · `docs/r1/spec.md`
  · `docs/r1/architecture.md` · `cleanmuzik-prd.md` · git. Read order in `CLAUDE.md`.
- **Business/vault context** — the garden, via `/garden`.
