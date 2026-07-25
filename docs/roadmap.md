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
| **R1.1** | `in-build` | **Review-inbox remediation.** Surface the durable parked-review queue (`GET /api/reviews`), lift the review lifecycle out of `TrackCard` (ADR-017), fix the no-candidate dead-end, boot-recon agreement (T-033), durable parked-audio staging (T-106), Signal Path reskin (ADR-018). Design gates signed off. `docs/r1.1/`. |
| R2 | `specing` | Playlists, migrate + clean existing library. Pull backlog items into `r2/spec.md` as it specs (`git mv` from `docs/backlog/`). **Blocked on R1.1** — migrate is a firehose into the review queue R1.1 makes real; don't build R2 on the amnesiac inbox. |
| R3+ | `backlog` | Untouched. Candidate: acoustic tier (BPM/key/energy), Tailscale/always-on host. |

Status vocabulary: `backlog` → `specing` → `in-build` → `shipped`. **Flip the status when the
state changes** — R1 sat at a `ticketed` value that isn't even in this vocabulary while 15 of its
tickets were built, which silently voided the "blocked unless `in-build`" rule above.

## Current release: R1.1 (in-build)

R1 shipped 2026-07-23, but a step-back on 2026-07-23 found it shipped a **spec-vs-build gap**: §7
promised parked reviews *"can still be resolved"*, and the backend keeps them — but the review
lifecycle was built inside the ephemeral `TrackCard`, so on a fresh load they were invisible and
unreachable, and a no-candidate park was a dead end. **R1.1** is the remediation slice that closes it:
a durable review inbox, the lifecycle lifted out of the card (ADR-017), the no-candidate exits, the
boot-recon fix (T-033), and the Signal Path reskin (ADR-018). Behaviour and skin are **owner-signed-off
as design-gate screens** (`docs/r1/design/`), spec + tickets in `docs/r1.1/`. R2 stays `specing` and is
**blocked from build** until R1.1 lands — migrate pours ambiguous tracks into exactly this queue.

Next step: build R1.1 tickets in order (T-104 backend ∥ T-101 client keystone → T-102 → T-103 → T-105
reskin).

### R2 (specing) — on deck
Playlists + migrate/clean the existing library. Next step is `docs/r2/spec.md`, pulling relevant
`docs/backlog/` items in as it specs — **after R1.1 ships.**

### R1 (shipped) — closeout
- [x] `spec.md` written and agreed
- [x] `tickets.md` generated from spec
- [x] **Build complete** — per-ticket status and the R1-vs-Backlog split in `r1/tickets.md`.
- [x] Shipped — R1 acceptance checklist met (spec §7, swept by T-019)
