---
type: meta
title: "Hot — cleanmuzik"
updated: 2026-08-14
tags:
  - meta
  - hot-cache
status: evergreen
---
# Hot — cleanmuzik (personal YouTube → Jellyfin music tool)

> This repo's own working-memory board — session continuity, loaded at session start via `/hot`.
> A cache, not a journal: rewritten each save, never appended. Durable knowledge lives in this repo's
> stores (`docs/roadmap.md` · `docs/r1/adr.md` · `docs/learnings.md` · `docs/r1.5/` · git); business
> learnings go to the garden via `/graft`.

## What this repo is

CleanMuzik — personal YouTube → Jellyfin music tool. Purpose, stack, constraints, read-order in
`CLAUDE.md`; scope in `cleanmuzik-prd.md`. Not restated here.

## Current State (2026-08-14)

- **On `main`.** Client 71 / server 529 green. **Uncommitted:** doc-only edits from today's R1.5 retro +
  roadmap resequence (`learnings.md`, `adr.md`, `workflow.md`, `roadmap.md`) — not yet committed.
- **R1 + R1.1 + R1.5 all SHIPPED.** No release is `in-build`. **R2 (Playlists) is next.**
- **R1.5 retro done (this session).** Root cause of the speed miss: the spike benchmarked the new senses
  *in isolation* against a fixture, ignoring work the real pipeline already does — an apples-to-oranges
  number that became a §7 criterion and broke at verify. Filed: learning (`learnings.md` 2026-08-14) +
  **ADR-026** (a spike's numbers pass a council review before entering a spec) + `workflow.md` rationale.

## Build order — RESEQUENCED (owner call 2026-08-14)

North-star = the owner's music playable **in the car**. Sequence is **not** numeric:

**R2 Playlists → R2.5 Migrate/clean → R3 Tailscale/host → R1.6 genre.**

- **R2 = Playlists ONLY** (paste a YouTube playlist, walk away). Spec `docs/r2/spec.md` signed off,
  `ready-for-agent`. Migrate/clean **split out to R2.5** — the roadmap table used to conflate them (fixed).
- **R2.5 = Migrate + clean** — the one the owner actually wants; fills the library worth streaming.
- **R3 = Tailscale + always-on host** (2010 MacBook on Mint) — the reachability that unlocks the car.
- **R1.6 = LLM genre — DEFERRED** behind all three (polish, off the car path).

Speed follow-ons unchanged in `docs/backlog/`: T-215 (Shazam hoist) + T-214 (narrate freeze) safe;
T-208 (de-hydration) the conditional engine change — **now graduates at R2.5**, not R2.

## ⟹ NEXT

- Nothing mid-flight. **Commit today's doc edits**, then **start R2** by flipping its roadmap status to
  `in-build`. R2's spec is signed off; the batch model + `playlists` entity are specced in `docs/r2/spec.md`.

## Recent sessions (rolling — last 2–3)

- **2026-08-14 (this session)** — Ran the **R1.5 retro**: filed the spike-benchmark lesson + **ADR-026**
  (spike-number council gate) + `workflow.md` rationale. **Resequenced the roadmap** for the car north-star
  (R2 → R2.5 → R3 → R1.6); fixed the stale "R2 = playlists + migrate" line (migrate is R2.5). Doc edits
  uncommitted.
- **2026-08-13 (prev)** — Closed **T-209** (§7 11/12); **shipped R1.5**. Design council corrected the
  fan-out blind spot; filed speed follow-ons to backlog split by risk (T-215/T-214 safe, T-208 conditional).

## Where the rest of the context lives

`docs/roadmap.md` (resequenced) · `docs/r2/spec.md` (Playlists, `ready-for-agent`) · `docs/r1/adr.md`
(ADR-026 new) · `docs/learnings.md` · `docs/workflow.md` (spike-number gate) · `docs/backlog/`
(T-208/214/215). Business/vault → `/graft`.
