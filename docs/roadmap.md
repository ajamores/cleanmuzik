# Roadmap — CleanMuzik

Release status tracker. **No release starts until the one before it ships.** Agents are
blocked from touching a release that isn't `in-build`.

Source of truth for scope: `cleanmuzik-prd.md` (product) → `docs/rN/spec.md` (per release).

| Release | Status | One-line scope |
|---|---|---|
| **R1** | `ticketed` | Spec signed off + `r1/tickets.md` written (2026-07-12, 19 tickets). Ready to build. Single YouTube song → tagged MP3 320 in Jellyfin, end to end. |
| R2 | `backlog` | Untouched until R1 ships. Candidate: playlists, migrate + clean existing library. |
| R3+ | `backlog` | Untouched. Candidate: acoustic tier (BPM/key/energy), Tailscale/always-on host. |

Status vocabulary: `backlog` → `specing` → `in-build` → `shipped`.

## Current release: R1

- [x] `spec.md` written and agreed
- [x] `tickets.md` generated from spec
- [ ] Build
- [ ] Shipped — R1 acceptance checklist met (see spec)
