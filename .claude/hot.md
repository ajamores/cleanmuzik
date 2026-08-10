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

- **On branch `spike/engine-rethink`** (NOT main), tree clean, pushed to origin. Holds the full spike
  harness + results; nothing merged to main yet.
- **R1 + R1.1 shipped.** R2 (playlists + T-037) scope-locked, `docs/r2/spec.md` `ready-for-agent`,
  parked behind the engine decision. Migrate/clean → R2.5.

## ⟹ Spike DONE — gate MET (results: `docs/research/engine-rethink-spike.md`)

26-song real-rip corpus, isolated capture → offline fixture, blinded **Haiku** adjudicator (via the
Claude Code harness — no key needed for accuracy). Artifacts in `server/spike/`.

- ✅ **Lock 1b (never override a correct fingerprint): PASS** — 0/17; caught the **Pa Salieu "Frontline"
  → Vanessa Bling** mistag on real audio; 0 false-accepts on blanks.
- ✅ **Lock 7 (speed): PASS** — Shazam 1.58s + real Haiku 1.37s ≈ **~3s vs today's 11s/37s beets chain,
  ~12×.** (Anthropic key now in `.env` as `ANTHROPIC_APIKEY` — SDK default name differs; R1.5 code must
  read it explicitly.)
- 🟡 **Lock 3 (review labor): effectively met** — referee parked only 2 extra songs and improved every
  card; Shazam rescued 3/6 freestyles (one had 0 MB candidates). Seconds-per-card is confirmatory, not a
  blocker. Shazam installed in isolated 3.12 venv `server/.venv-shazam` (keyless).

**Verdict: commit to R1.5** — LLM-adjudicator + Shazam-input, per council containment (veto/confirm only,
`chosen_mbid` enum-constrained, `_matching_candidate` hard veto, Shazam never auto-lands).

## ⟹ NEXT

1. Owner **ratifies the 3 proposed ADRs** (spike passed) → move from council doc §2 into `adr.md`:
   narrow ADR-001 (land pool=1), narrow ADR-005 (LLM=adjudicator, beets=writer/facts), genre-enum-swap.
2. **Build R1.5** (flagged, between R1.1 and R2): surface `SourceSignals` (`download.py:~299`), inject
   `llm_adjudicate` at `choose_item`, `app/shazam.py`, `app/enrich.py`. Graduating spike artifacts: the
   Verdict schema/prompt/accept-rule, the Shazam fail-soft taxonomy. **Prereq:** ADR-020 manual exits.
3. R1.5+ follow-ons (the platform upside): genre/mood enrichment (exp 4), re-search rescue agent
   (T-034/035), alias disambiguation. Scoped in the spike doc "Beyond the gate".

## Live library mess (real cleanup, unticketed)

`Vanessa Bling…/Frontline.mp3` is really Pa Salieu (the spike's marquee fixture — re-tag). `JAŸ-Z/Roc
Boys` — T-037 recurrence.

## Recent sessions (rolling — last 2–3)

- **2026-08-09 (pm)** — Ran the whole spike: test env (26-song corpus + isolated capture fixture),
  passed lock 1b (0 overrides, caught Frontline), lock 3 (review-labor mechanism proven), and lock 7
  (Shazam+Haiku ~12× faster, real key). Gate met → R1.5 recommended. Filed `engine-rethink-spike.md`;
  branch `spike/engine-rethink` pushed. Lessons: capture `item_tags` are pre-tag YouTube input not landed
  truth (scorer bug, fixed); Python 3.14 venv has no `shazamio-core` wheel → isolated 3.12 venv.
- **2026-08-09 (am)** — R2 specced; engine-rethink council → LLM-as-adjudicator verdict; measured
  identify (not download) as the 11s/36s bottleneck.

## Where the rest of the context lives

`docs/research/engine-rethink-spike.md` (results) · `engine-rethink-council.md` (§5 plan, §2 ADRs) ·
`docs/roadmap.md` · `docs/r2/spec.md` · `docs/workflow.md` · `docs/r1/adr.md` · `docs/learnings.md` · git.
Business/vault → `/garden`.
