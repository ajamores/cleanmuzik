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

- **T-016 landed on `main` (`a644c07`), pushed, suite green (269).** Scope was reduced at
  integration: the stream *reattach* layer was cut to **T-020** after two review passes found 8 then
  10 defects in it. Tree clean bar untracked `.claude/worktrees/`.
- **The app now has a UI and has never been run in a browser.** Owner is testing next session.
- Ledger `docs/r1/tickets.md`: open = **T-017, T-019, T-020**.

## NEXT — owner drives the app, together, next session

1. **Run the 6-row list under T-019** in `docs/r1/tickets.md` ("First owner-driven browser session").
   Two terminals: `server` → `./.venv/bin/uvicorn app.main:app --reload --port 8137`;
   `client` → `npm run dev`. Rows 3–4 (restart, offline) are the failure paths this sandbox can't
   produce — they feed T-020 directly. Row 5 dead-ends by design (review panel is T-017).
2. **Fix against real symptoms**, not hypotheses. That's the whole point of the session.
3. Then **T-017** (review panel UI) — its EventSource reuses T-016's pattern, so row-by-row results
   from #1 decide whether that pattern is safe to build on.

## Recent sessions (rolling — last 2–3)

### 2026-07-18 (later) — T-016 integration: scope cut, not patched
- Two pre-commit reviews on the merge: 8 defects, then 10 — the second set including 3 regressions
  from fixing the first. All in failure-path logic that can't be exercised here. Cut the give-up
  policy to T-020 rather than patch a 4th time; kept EventSource auto-retry + one snapshot per
  outage (required — a duplicate skip emits no §6 event). Lessons → `learnings.md`.
- Found + fixed a **dead Vite proxy port** (8000 vs README's 8137, broken since T-001, `fbf2da3`) —
  latent because client and server had never run together until there was a UI.

### 2026-07-18 (earlier) — T-014 re-review + integration
- T-014 fully done: optional re-review found 4 bugs (2 confirmed), fixed in `cd3d3a2`, pushed.

## Where the rest of the context lives

- **Durable stores:** `docs/r1/adr.md` · `docs/learnings.md` · `docs/r1/tickets.md` · `docs/r1/spec.md`
  · `docs/r1/architecture.md` · `cleanmuzik-prd.md` · git. Read order in `CLAUDE.md`.
- **Business/vault context** — the garden, via `/garden`.
