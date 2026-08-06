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
| R2 | `specing` | Playlists, migrate + clean existing library. Pull backlog items into `r2/spec.md` as it specs (`git mv` from `docs/backlog/`). **Unblocked** — R1.1 shipped, so the durable review queue migrate pours into now exists. Ready to move to `specing` build when the owner starts it. |
| R3+ | `backlog` | Untouched. Candidate: acoustic tier (BPM/key/energy), Tailscale/always-on host. |

Status vocabulary: `backlog` → `specing` → `in-build` → `shipped`. **Flip the status when the
state changes** — R1 sat at a `ticketed` value that isn't even in this vocabulary while 15 of its
tickets were built, which silently voided the "blocked unless `in-build`" rule above.

## Current release: R2 (specing) — on deck

**R1.1 shipped 2026-08-05.** It closed R1's §7 spec-vs-build gap (the review lifecycle had been built
inside the ephemeral `TrackCard`, so parked reviews were invisible on a fresh load and a no-candidate
park was a dead end). The remediation landed a durable review inbox, the lifecycle lifted out of the
card (ADR-017), the no-candidate exits, the boot-recon fix (T-104), durable parked-audio staging
(T-106), and the Console reskin (ADR-018, amended) — §8 acceptance met with receipts.

**R2** is now unblocked: playlists + migrate/clean the existing library. Migrate is a firehose into
exactly the review queue R1.1 made durable. Next step is `docs/r2/spec.md`, pulling relevant
`docs/backlog/` items in as it specs (`git mv` from `docs/backlog/`). Owner starts it when ready.

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
