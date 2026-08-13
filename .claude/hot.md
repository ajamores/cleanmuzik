---
type: meta
title: "Hot — cleanmuzik"
updated: 2026-08-12
tags:
  - meta
  - hot-cache
status: evergreen
---
# Hot — cleanmuzik (personal YouTube → Jellyfin music tool)

> This repo's own working-memory board — session continuity, loaded at session start via `/hot`.
> A cache, not a journal: rewritten each save, never appended. Durable knowledge lives in this repo's
> stores (`docs/r1/adr.md` · `docs/learnings.md` · `docs/research/` · `docs/r1.5/` · git); business
> learnings go to the garden via `/graft`.

## What this repo is

CleanMuzik — personal YouTube → Jellyfin music tool. Purpose, stack, constraints, read-order in
`CLAUDE.md`; scope in `cleanmuzik-prd.md`. Not restated here.

## Current State (2026-08-12)

- **On `main`, clean tree** (`4c98623`). Client **71** / server **529** — unchanged; T-209 was docs-only.
- **R1 + R1.1 shipped.** **R1.5** (architecture B — multi-sense reconciliation): T-200–T-207 all landed;
  **T-209 verify DONE.**
- **T-209 closed — §7 verified end-to-end, 11 of 12 pass.** Isolated `/verify` on the spike corpus with
  live reconcile (real Shazam/MusicBrainz/Haiku); **real library confirmed untouched.** Pa Salieu override
  landed the correct identity via `source=isrc senses=[yt,sz]` (mbid 6d6dd1f3), zero clicks. Happy-path,
  vote-holds, no-invented-facts, fail-soft (error+hang, hang capped 8.06s), reconcile-fail-parks, degrade,
  persistence (byte-identical across restart), feature-parity (3 songs identical B vs R1), serial pool=1,
  genre-unchanged — all ✅.
- **The 1 fail was speed** — identity median **~21s** vs the <6s §7 target. The target came from spike
  exp 9's 4.2s, which measured the senses against a **pre-captured** fixture; the built pipeline is
  **additive** (live fingerprint chain ~12s THEN senses serially). Per owner: **§7 speed amended** to
  no-regression-vs-R1-total, **T-208 opened**, learning + spike postscript filed.

## ⟹ NEXT — T-208, or ship R1.5?

- **T-208** (opened by T-209, was the reserved slot): gather senses **concurrently within a track**
  (ADR-001 bars cross-track parallelism, **not** intra-track) → pull identity from ~21s toward the ~12s
  fingerprint floor, with **zero** change to T-209's land/park outcomes. Spec in `docs/r1.5/tickets.md`.
- **Owner call:** T-208 is an *optimization, not a correctness blocker* — §7 now passes against the amended
  bar. Decide whether R1.5 **ships now** (T-208 as a post-ship follow-on) or T-208 lands first.

## Recent sessions (rolling — last 2–3)

- **2026-08-12 (this session)** — Ran **T-209**: isolated `/verify`, 11/12 §7 pass, real library untouched.
  Speed failed → §7 amended + **T-208** opened; learning transcribed. Commit `4c98623`. (Verify harness +
  RESULTS in the session scratchpad.)
- **2026-08-12–13 (prev)** — T-207 review-card park story + T-200 reconcile-key fix (reconcile went live) +
  T-213 (auto-retry transient 403s). thru `a455386`.

## Where the rest of the context lives

`docs/r1.5/spec.md` (§7 amended) · `docs/r1.5/tickets.md` (T-208 open, T-209 done) ·
`docs/research/engine-rethink-spike.md` · `docs/roadmap.md` · `docs/r1/adr.md` · `docs/learnings.md` ·
`docs/backlog/` (T-210/211/212). Business/vault → `/graft`.
