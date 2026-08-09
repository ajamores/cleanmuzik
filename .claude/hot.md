---
type: meta
title: "Hot — cleanmuzik"
updated: 2026-08-09
tags:
  - meta
  - hot-cache
status: evergreen
---
# Hot — cleanmuzik (personal YouTube → Jellyfin music tool)

> This repo's own working-memory board — session continuity, loaded at session start via `/hot`.
> A cache, not a journal: rewritten each save, never appended. Durable knowledge lives in this repo's
> stores (`docs/r1/adr.md` · `docs/learnings.md` · `docs/r2/spec.md` · `docs/research/` · git);
> business/vault learnings go to the garden via `/graft`.

## What this repo is

CleanMuzik — personal YouTube → Jellyfin music tool. Purpose, stack, constraints, read-order in
`CLAUDE.md`; scope in `cleanmuzik-prd.md`. Not restated here.

## Current State (2026-08-09)

- **On `main`, tree clean.** Suites green (server 432, client 65). No pipeline code this session —
  specced, ran a council, measured.
- **R1 + R1.1 SHIPPED.** R2 = playlists + T-037, scope locked; `docs/r2/spec.md` `ready-for-agent`.
  Migrate/clean → R2.5.
- **Engine-rethink: council done → filed `docs/research/engine-rethink-council.md`.** Verdict is
  **NOT a rewrite.** The LLM becomes the **adjudicator** (veto/confirm on auto-land, choose-among on
  review) + **genre/mood author**, over an **unchanged beets(writer)/MusicBrainz(facts) spine**;
  Shazam = fail-soft input. A matcher swap, not an engine swap.
- **MEASURED (2 real songs):** *identify ("inspect") is the bottleneck* — **10.96s parked / 36.2s
  auto-land** (~62–85% of wall clock); download is only 2–3s. Corrects the council's "download is
  slow" framing, and is the **latency case** for the LLM path (Shazam+LLM collapses the serial
  AcoustID→MB→Last.fm lookup chain).

## ⟹ NEXT — run the spike (go/no-go before ANY build)

Plan = §5 of the council doc; ~30–50 real rips, offline `TestClient`. Two tracks:
- **Accuracy** — exp 1b: LLM must *never* override a correct fingerprint (=0); exp 3: review
  seconds-per-card drops.
- **Speed** — exp 7: head-to-head inspect timing (beets chain, per-sub-call, vs Shazam+LLM);
  exp 8: Shazam batch-throttle probe (the one risk that can't be reasoned, only measured).
- **Three-lock gate:** 1b=0 **AND** card-seconds drop **AND** Shazam+LLM faster than beets. Baseline
  to beat: **11s/36s.**
- **Needs building:** an inject-`llm_adjudicate` harness (mirror `dominance_fn` injection), a ShazamIO
  seam, an Anthropic client. Timing driver already in scratchpad (`time_pipeline.py`, `run_isolated.py`).

## Proposed decisions (pending spike — NOT ratified, not in `adr.md` yet)

Narrow ADR-001 (per-stage: parallelize download/transcode, **land pool=1**); narrow ADR-005
(LLM=identifier+genre, beets=writer/facts); ship as flagged **R1.5** between R1.1 and R2; R2's two
data-model ADRs can proceed now (engine-agnostic). Detail: council doc §2.

## Live library messes (uncleaned)

- `Vanessa Bling…/Frontline.mp3` — really Pa Salieu. Re-tag/re-acquire.
- `JAŸ-Z/Roc Boys` — T-037 recurrence. Re-consolidate.

## Also open / verifying

Backlog (parked, NOT R2): T-035 (Shazam — now central), T-034, T-042, T-023/030/031/039/041; only
T-037 pulled into R2. Verify playbook: `/verify` skill + `docs/workflow.md` (isolate `DB_PATH`, never
`/mnt/c`; dev servers uvicorn `:8137` + Vite `:5173`).

## Recent sessions (rolling — last 2–3)

- **2026-08-09** — R2 specced (`spec.md` ready). A live confidently-wrong auto-tag opened the
  engine-rethink thread → research → 11-agent council (filed `engine-rethink-council.md`): verdict
  LLM-as-adjudicator over an unchanged beets spine, not a rewrite. Then **measured** that identify is
  the real bottleneck (11s/36s), correcting the download framing; folded a speed arm into the spike.
- **2026-08-06** — Retro R1→R1.1: DoD step 6; slimmed CLAUDE.md ~46%.
- **2026-08-05 (pm)** — Shipped R1.1; diagnosed T-037's encoding mangle.

## Where the rest of the context lives

`docs/roadmap.md` · `docs/r2/spec.md` · `docs/research/` · `docs/workflow.md` · `docs/r1/adr.md` ·
`docs/learnings.md` · `docs/backlog/` · git. Business/vault → `/garden`.
