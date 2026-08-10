# Roadmap — CleanMuzik

Release status tracker. **No release starts until the one before it ships.** Agents are
blocked from touching a release that isn't `in-build`.

Source of truth for scope: `cleanmuzik-prd.md` (product) → `docs/rN/spec.md` (per release).

**Scope triage (the gate that keeps a release from creeping).** A release's scope is its **exit
criteria**, not everything found while building it. Work discovered mid-build (from reviews,
verifies, browser sessions) is captured as a ticket, then triaged **at birth**: required to meet
this release's exit criteria → current release; else → the **`docs/backlog/`** parking lot (one
file per ticket; see its `README.md`). Backlog items enter a future release only when that release
moves to `specing` and pulls them into its spec — a `git mv` of the ticket file into that release's
`tickets.md`. Capturing a finding is automatic; committing it to *this* release is a
decision. (R1 was specced at 19 tickets and drifted to 31 because this gate didn't exist — the
mechanism now lives in `docs/r1/tickets.md` "How a ticket enters a release".)

| Release | Status | One-line scope |
|---|---|---|
| **R1** | `shipped` | Single YouTube song → tagged MP3 320 in Jellyfin, end to end. Spec signed off; specced at 19 tickets, plus mid-build discoveries triaged into R1 or Backlog in `r1/tickets.md` (the status ledger — this table does not restate it). All build tickets on `main`; T-020 (last) merged with a clean high-effort review. **Shipped with a spec-vs-build gap** (§7 "parked reviews can still be resolved" was false through the UI) — closed by **R1.1**. |
| **R1.1** | `shipped` | **Review-inbox remediation — shipped 2026-08-05.** Durable parked-review queue (`GET /api/reviews`), review lifecycle lifted out of `TrackCard` (ADR-017), no-candidate dead-end fixed, boot-recon agreement (T-104), durable parked-audio staging (T-106), Console reskin (ADR-018, amended). All six tickets on `main`; **§8 acceptance checklist met with receipts** (`docs/r1.1/spec.md` §8). Closes R1's §7 spec-vs-build gap. |
| **R1.5** | `specing` | **Engine rethink — multi-sense reconciliation (architecture B).** Identity from yt-dlp + AcoustID fingerprint + Shazam, reconciled by one LLM call (2-of-3 senses vote), facts from a real lookup, feature-parity outputs, ~8.6× faster. Spec v2 in `docs/r1.5/spec.md` (pending owner sign-off). Decision + evidence: `docs/research/engine-rethink-spike.md` (exp 8/9); binding: ADR-021 (amended 2026-08-10), ADR-022. **Slots between R1.1 and R2.** |
| **R1.6** | `backlog` | **LLM-authored genre/mood (ADR-023).** Opens with **exp 4** (the never-run confident-wrong-rate test + the curated enum with an `uncertain` member); wires `app/enrich.py` and drops `lastgenre` only if it passes. Also the Shazam-vs-LRCLIB synced-lyrics decision. Deferred out of R1.5 deliberately (spec §3). |
| R2 | `backlog` | Playlists, migrate + clean existing library. Pull backlog items into `r2/spec.md` as it specs (`git mv` from `docs/backlog/`). Durable review queue (R1.1) is the firehose target. **Now sequenced behind R1.5/R1.6** (the engine landing there is what R2's batch multiplies over). |
| R3+ | `backlog` | Untouched. Candidate: acoustic tier (BPM/key/energy), Tailscale/always-on host — **the host is the owner's 2010 MacBook already running Linux Mint, not a future purchase.** Native Linux, so no WSL bridging (the only real friction on the dev laptop); it's a spare, so 24/7 is free. Check disk space (add an external drive if tight) and the battery (2010 cells are often dead/swollen) at move time. Migrate the finished stack there after R2 ships; nothing to buy. |

Status vocabulary: `backlog` → `specing` → `in-build` → `shipped`. **Flip the status when the
state changes** — R1 sat at a `ticketed` value that isn't even in this vocabulary while 15 of its
tickets were built, which silently voided the "blocked unless `in-build`" rule above.

## Current release: R1.5 (specing) — engine rethink

**R1.5** is the active release: multi-sense reconciliation (architecture B), chosen over the veto-only
adjudicator after the spike's A-vs-B head-to-head (`docs/research/engine-rethink-spike.md`, exp 8/9).
Identity comes from three senses (yt-dlp title, AcoustID fingerprint, Shazam) reconciled by one LLM call
under a **2-of-3 vote**; facts stay from a real lookup; outputs keep **feature parity** with R1; ~8.6×
faster. Spec v2 is `docs/r1.5/spec.md`, **pending owner sign-off**; next is ticket decomposition. Binding:
**ADR-021 (amended 2026-08-10)**, ADR-022. R1.6 (LLM genre, gated on exp 4) and R2 sequence behind it.

**R2** (playlists + migrate/clean) is unblocked but now **behind R1.5/R1.6** — the engine that lands in
R1.5 is what R2's batch multiplies over, so it lands first. `docs/r2/spec.md` already `ready-for-agent`.

### R1.1 (shipped) — closeout
- [x] `spec.md` written and owner-signed-off; design gates signed off (`docs/r1/design/`)
- [x] `tickets.md` — T-101/102/103/104/105/106 all done, verified, on `main`
- [x] **§8 acceptance checklist met with receipts** (`docs/r1.1/spec.md` §8), suites green (432/65)
- [x] Shipped 2026-08-05 — closes R1's §7 gap

### R1 (shipped) — closeout
- [x] `spec.md` written and agreed
- [x] `tickets.md` generated from spec
- [x] **Build complete** — per-ticket status and the R1-vs-Backlog split in `r1/tickets.md`.
- [x] Shipped — R1 acceptance checklist met (spec §7, swept by T-019)
