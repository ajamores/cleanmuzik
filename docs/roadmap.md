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
| **R1** | `shipped` | Single YouTube song → tagged MP3 320 in Jellyfin, end to end. Spec signed off; specced at 19 tickets, plus mid-build discoveries triaged into R1 or Backlog in `r1/tickets.md` (the status ledger — this table does not restate it). All build tickets on `main`; T-020 (last) merged with a clean high-effort review. |
| R2 | `specing` | Playlists, migrate + clean existing library. Pull backlog items into `r2/spec.md` as it specs (`git mv` from `docs/backlog/`). |
| R3+ | `backlog` | Untouched. Candidate: acoustic tier (BPM/key/energy), Tailscale/always-on host. |

Status vocabulary: `backlog` → `specing` → `in-build` → `shipped`. **Flip the status when the
state changes** — R1 sat at a `ticketed` value that isn't even in this vocabulary while 15 of its
tickets were built, which silently voided the "blocked unless `in-build`" rule above.

## Current release: R2 (specing)

R1 shipped 2026-07-23 — all build tickets on `main`, T-020 (last) merged with a clean high-effort
review. R2 is now `specing`: playlists + migrate/clean the existing library. Next step is
`docs/r2/spec.md`, pulling relevant `docs/backlog/` items in as it specs.

### R1 (shipped) — closeout
- [x] `spec.md` written and agreed
- [x] `tickets.md` generated from spec
- [x] **Build complete** — per-ticket status and the R1-vs-Backlog split in `r1/tickets.md`.
- [x] Shipped — R1 acceptance checklist met (spec §7, swept by T-019)
