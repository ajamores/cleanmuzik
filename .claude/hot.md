---
type: meta
title: "Hot — cleanmuzik"
updated: 2026-07-16
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

CleanMuzik — personal YouTube → Jellyfin music tool. Purpose, stack, constraints and the read-order
are in `CLAUDE.md`; scope in `cleanmuzik-prd.md`. Not restated here.

## Current State (2026-07-16)

- **Phase: R1 build.** Phase A (engine spine) + Phase B (T-012 orchestration, T-013 SSE) **done and
  verified live**. Phase C started — T-015 shell done. `docs/r1/tickets.md` is the status ledger and
  is now **accurate**: the only open tickets are **T-014, T-016, T-017, T-019**.
- **Branch `main`, tree clean, pushed.** Session 14 was docs-only (`d7b620f` doc-bug fixes,
  `c99e76d` board prune) — no code changed since T-015.
- **NEXT — the T-016 ∥ T-014 fan-out.** Disjoint (client vs server), both unblocked; run them as
  parallel worktree agents per the fan-out mechanics in `CLAUDE.md`. T-017 needs both.
  - **T-016** — add `EventSource` + `setStage` to `client/src/components/TrackCard.tsx`. That's the
    whole ticket: T-015 left the seam, so the `Stage` union (matching the §6 event names) and the
    `useState` are already there. Also the first real browser round-trip — T-015 was never driven live.
  - **T-014** — review API. `GET /api/reviews` re-hydrates candidates from stored MBIDs (reuse
    `events.candidate_row()`); `POST /api/reviews/{id}/resolve` resumes the import + emits the tail
    events. **Read `spec.md` §5 staging-retention first** — a parked song keeps its staging file; it
    *is* the copy being resolved. Cleanup is T-014's job, at resolve time, on both branches.

## Recent sessions (rolling — last 2–3)

### 2026-07-16 (session 14) — board sweep; docs corrected; `/hot` skill rewritten

- Board had grown to 883 lines and was **contradicting itself** (two rival `## Current State`
  sections; T-015 listed as both committed and still in a worktree). Root cause: `/hot` said
  "prepend, never rewrite older entries" — append with no eviction path. **Skill rewritten**: cache
  not journal, rewrite-don't-append, a routing table, and ~500 words as a *tripwire* (over budget ⇒
  unfiled content, on load and save). Same bug found upstream in claude-obsidian — evidence, not
  anecdote. → `learnings.md`
- **Two live doc bugs found and fixed** (`d7b620f`): `spec.md` never carved parks out of
  staging-cleanup (**T-014 would have deleted the file it resolves** — read §5 before building it);
  `architecture.md` + `backlog/` still described the **data-loss** duplicate design ADR-009 withdrew,
  in the doc agents read *before* the ADR. Also filed 4 orphans to `learnings.md`, fan-out mechanics
  + the routing table to `CLAUDE.md`, primer 00 to its index, and corrected **9 ticket statuses** —
  the ledger is accurate for the first time, which is what made the board disposable.

### 2026-07-16 (session 13) — T-013 ∥ T-015 fan-out

- Both built as parallel worktree agents, integrated one at a time. T-013 (`6a7675e`) reviewed +
  `/verify`'d live. T-015 (`439fdf3`) reviewed. Per-ticket detail: `tickets.md`.

## Where the rest of the context lives

- **This repo's durable stores:** `docs/r1/adr.md` (binding decisions) · `docs/learnings.md`
  (mistakes already paid for) · `docs/r1/tickets.md` (work + status) · `docs/r1/spec.md` ·
  `docs/r1/architecture.md` (stack + seams) · `cleanmuzik-prd.md` (scope) · `docs/primers/` (owner
  explainers) · git history. Read order is in `CLAUDE.md`.
- **Business/vault context** (pricing, prospects, positioning) lives in the **garden** — `/garden`.
