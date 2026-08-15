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
| **R1.5** | `shipped` | **Engine rethink — multi-sense reconciliation (architecture B) — shipped 2026-08-13.** Identity from yt-dlp + AcoustID fingerprint + Shazam, reconciled by one LLM call (2-of-3 senses vote), facts from a real lookup, feature-parity outputs. **T-209 verified §7 end-to-end: 11/12 pass** — the marquee **Pa Salieu override** lands the correct identity via a real ISRC MBID where R1 could only mistag/park. Faster end-to-end than R1 (22–26s vs ~36s auto-land), though **not** the spike's oversold ~8.6× — that measured senses against a fixture, not the live chain (T-209 finding; §7 speed criterion amended). Per-song speed optimization (T-208) **deferred** — graduates at R2.5 where bulk-migrate multiplies per-song seconds. Spec `docs/r1.5/spec.md`; evidence `docs/research/engine-rethink-spike.md` (exp 8/9); binding ADR-021 (amended 2026-08-10), ADR-022. |
| **R2** | `in-build` | **Playlists — paste a YouTube _playlist_ URL and walk away.** Expands the playlist, runs each track through the existing R1.5 pipeline, and mirrors it into Jellyfin as a playlist named after the YouTube one (the owner's monthly "music journals"); safe to re-run, backfills late-resolved tracks, one canonical file on disk. Scope signed off at the 2026-08-08 grilling; spec `docs/r2/spec.md` is `ready-for-agent`. Carries the T-037 tag-mangle fix. **Playlists only — migrate/clean is R2.5.** |
| **R2.5** | `backlog` | **Migrate + clean the existing library.** Split out of R2 at the 2026-08-08 grilling (`docs/r2/spec.md:13`) — the same engine pointed at the owner's existing files instead of a YouTube URL. **The one the owner actually wants**: it's what fills the library worth streaming in the car. Durable review queue (R1.1) is the firehose target; R1.5's engine + R2's batch model are what its bulk run multiplies over. Speed follow-on **T-208 graduates here** (per-song seconds × a whole library). |
| **R3+** | `backlog` | **Tailscale + always-on host — the library reachable from the car (the north-star).** Host is the owner's 2010 MacBook already on Linux Mint — native Linux, no WSL bridging, a spare so 24/7 is free; **nothing to buy.** Check disk (external drive if tight) and the battery (2010 cells often dead/swollen) at move time. Migrate the finished stack there once R2.5's library is clean. Also the acoustic tier (BPM/key/energy) via **local** Essentia/Librosa — never the dead AcousticBrainz service (learnings 2026-08-10). |
| **R1.6** | `backlog` · **deferred** | **LLM-authored genre/mood (ADR-023) — deferred behind R2 / R2.5 / R3.** Polish, not on the car path, so it waits (owner call 2026-08-14). Opens with **exp 4** (the never-run confident-wrong-rate test + the curated enum with an `uncertain` member); wires `app/enrich.py` and drops `lastgenre` only if it passes. Also the Shazam-vs-LRCLIB synced-lyrics decision. Was deferred out of R1.5 deliberately (spec §3). |

Status vocabulary: `backlog` → `specing` → `in-build` → `shipped`. **Flip the status when the
state changes** — R1 sat at a `ticketed` value that isn't even in this vocabulary while 15 of its
tickets were built, which silently voided the "blocked unless `in-build`" rule above.

## Current release: R2 (Playlists) — `in-build` (flipped 2026-08-14)

**R1.5 shipped 2026-08-13.** Multi-sense reconciliation (architecture B): three senses (yt-dlp title,
AcoustID fingerprint, Shazam) reconciled by one LLM call under a **2-of-3 vote**; facts from a real
lookup; **feature parity** with R1. T-209 verified §7 end-to-end (11/12; speed criterion amended after
the spike's isolated benchmark proved unreachable in the integrated pipeline). Binding: **ADR-021
(amended 2026-08-10)**, ADR-022. **R2 is now `in-build`** (flipped 2026-08-14) — see below.

**Build order (owner-set 2026-08-14) — _not_ numeric order:** **R2 Playlists → R2.5 Migrate/clean →
R3 Tailscale/host → R1.6 genre.** The through-line is the north-star, the owner's music playable in
the car: R2 makes the paste-a-playlist flow work, **R2.5 fills the library worth streaming**, R3
(Tailscale on the always-on 2010 MacBook) makes it reachable on the road. R1.6 (LLM genre) is polish
off that path, so it waits. R2's spec (`docs/r2/spec.md`) is signed off and **`in-build` as of
2026-08-14** — build T-300 + T-301 first (they write ADR-027 + ADR-028, which gate the design gate T-310).

**The speed follow-ons live in `docs/backlog/`, split by risk:** T-215 (Shazam hoist) and T-214
(narrate the identify freeze) are safe, non-engine, buildable anytime; **T-208** (candidate
de-hydration) is the only piece that touches the tagging engine, so it's deferred + conditional, clears
its own §7 gate, and **graduates at R2.5** where bulk-migrate multiplies per-song seconds.

### R1.5 (shipped) — closeout
- [x] All tickets T-200–T-207 built + integrated on `main` (prior sessions); T-209 verify **done** (`4c98623`)
- [x] **§7 acceptance: 11/12 proven end-to-end** by isolated `/verify` (`docs/r1.5/spec.md` §7); Pa Salieu
      override + fail-soft + persistence + feature-parity all on real audio, real library untouched
- [x] Speed re-scoped (spike's ~8.6× was fixture-measured, not integrated) → §7 amended, **T-208 deferred to R2.5**
- [x] Shipped 2026-08-13

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
