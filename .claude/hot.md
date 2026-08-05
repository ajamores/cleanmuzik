---
type: meta
title: "Hot — cleanmuzik"
updated: 2026-08-04
tags:
  - meta
  - hot-cache
status: evergreen
---
# Hot — cleanmuzik (personal YouTube → Jellyfin music tool)

> This repo's own working-memory board — session continuity, loaded at session start via `/hot`.
> A cache, not a journal: rewritten each save, never appended. Durable knowledge lives in this repo's
> stores (`docs/r1/adr.md` · `docs/learnings.md` · `docs/r1.1/` · `docs/backlog/` · git);
> business/vault learnings go to the garden via `/graft`.

## What this repo is

CleanMuzik — personal YouTube → Jellyfin music tool. Purpose, stack, constraints and read-order are in
`CLAUDE.md`; scope in `cleanmuzik-prd.md`. Not restated here.

## Current State (2026-08-04)

- **On branch `t-105-signal-path`** (pushed to origin). Not merged to `main`.
- **T-105 console redesign committed** (`11b6302`). Grew past the original reskin: on seeing it live
  the owner set the approved design gate aside for a bolder **console-rail** direction (taste-skill,
  two Fable passes on `claude-fable`). Big centered crest, segmented-LED meter rail, and a **36-bar EQ
  beat animation** replacing the ambient wave. Visual only — no logic/props/SSE/API touched. Build,
  lint, 65/65 client tests green; verified in-browser dark + light.
- Queue (real backend `:8137`): 2 parked weak-match reviews (Outro/Nines, Dave East). Library in
  `~/cleanmuzik-data`.

## ⟹ NEXT (T-105 close-out — DoD not yet complete)

1. **`/code-review`** the accumulated redesign diff (large; two Fable passes).
2. **Amend ADR-018** — the console direction supersedes the "Signal Path" gate screens, and the EQ
   bars **reverse its "no spectrum bars" line** (owner's explicit call). Update the T-105 ticket +
   design-gate references too. (Decision is captured in `11b6302`'s body meanwhile.)
3. **Merge to `main`** once 1–2 are done (DoD step 5).
4. Then: **T-106** end-to-end `/verify` (unblocked now T-103 landed) + **§8 close-out** vs R1.1 spec.

## Also open (not the live thread)

- `docs/backlog/` — **T-039** (inbox loading indicator), **T-040** (keep_untagged resolve fails),
  **T-037** (tag-quality), **T-035** (Shazam tier).
- Real cover-art endpoint stayed deferred — T-105 shipped the Option-2 gradient swatch.

## Verifying

- **Run everything from `~/github/cleanmuzik` (ext4), never `/mnt/c`** — 9p times out test workers.
- Dev servers already run: `uvicorn :8137` (--reload) + Vite `:5173` (proxies `/api`). Editing server
  modules re-runs the lifespan against the **live** DB — client-only edits are safe.
- Playwright screenshots land in the gitignored `.playwright-mcp/`; toggle theme with
  `document.documentElement.setAttribute('data-theme','dark'|'light')`.

## Recent sessions (rolling — last 2–3)

- **2026-08-04 (pm)** — T-105 → full console redesign. Reskin ported the gate, owner found it
  templated ("AI slop"), so redesigned with taste-skill/Fable: console rail, big centered crest, EQ
  beat bars. Fixed a crest clip (nested `<symbol>` viewport → `<g>`). Committed `11b6302`, pushed.
- **2026-08-04 (am)** — Bug fix `8ba2c2f`: `FwKp-HkKUMA` showed Done but never landed (dup-stage
  false-match + equal-bitrate skip). → ADR-009 amendment, learnings entry.
- **2026-08-03** — T-105 design gate passed (crest Rev C + Signal Path), since superseded.

## Where the rest of the context lives

`docs/roadmap.md` · `docs/r1.1/` (active) · `docs/r1/adr.md` (**ADR-018 amendment owed**) ·
`docs/learnings.md` · `docs/backlog/` · git. Business/vault → `/garden`.
