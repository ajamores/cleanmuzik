# Roadmap — CleanMuzik

Release status tracker. **No release starts until the one before it ships.** Agents are
blocked from touching a release that isn't `in-build`.

Source of truth for scope: `cleanmuzik-prd.md` (product) → `docs/rN/spec.md` (per release).

| Release | Status | One-line scope |
|---|---|---|
| **R1** | `in-build` | Single YouTube song → tagged MP3 320 in Jellyfin, end to end. Spec signed off; 19 tickets in `r1/tickets.md` (the status ledger — this table does not restate it). Phase A (engine spine) + Phase B (orchestration, SSE) done and verified live; Phase C (UI) in progress. |
| R2 | `backlog` | Untouched until R1 ships. Candidate: playlists, migrate + clean existing library. |
| R3+ | `backlog` | Untouched. Candidate: acoustic tier (BPM/key/energy), Tailscale/always-on host. |

Status vocabulary: `backlog` → `specing` → `in-build` → `shipped`. **Flip the status when the
state changes** — R1 sat at a `ticketed` value that isn't even in this vocabulary while 15 of its
tickets were built, which silently voided the "blocked unless `in-build`" rule above.

## Current release: R1

- [x] `spec.md` written and agreed
- [x] `tickets.md` generated from spec
- [ ] **Build — in progress.** Per-ticket status lives in `r1/tickets.md`; don't mirror it here.
      Open: T-014, T-016, T-017, T-019.
- [ ] Shipped — R1 acceptance checklist met (spec §7, swept by T-019)
