# CleanMuzik Primers

Plain-English explainers to help the **owner** understand the concepts behind this project —
starting with networking. Written to teach, with analogies for the hard parts, tables for every
comparison, and the trade-offs made explicit.

> **Not to be confused with `../learnings.md`.** That file is the *build's* mistake-ledger — things
> an agent got wrong, so they aren't re-taught. **These primers are for the human** — understanding,
> not corrections. Different audience, different purpose, deliberately a separate directory.

## How this is organized

- **One concept = one primer.** Each has a versioned HTML source here *and* a published Artifact —
  a full-bleed, open-in-your-browser page. The Artifact link is the nice way to read it; the file is
  the versioned source.
- **Numbered by reading order.** Start at 01 and walk up; each builds on the last.
- **Every primer ties to a real piece of CleanMuzik** — not networking in the abstract, but the
  networking *this project* actually uses, and why.

## Networking track

| # | Primer | Ties to | Read it | Status |
|---|--------|---------|---------|--------|
| 01 | **VPN vs VPS — where your music actually lives** | Phase 0 → Phase 1 hosting | [open](https://claude.ai/code/artifact/ba2f49ef-1ddc-49c5-bf1d-672d0d1ff0cf) | ✅ built |
| 02 | localhost, IPs & ports | How the app + Jellyfin find each other | — | planned |
| 03 | **The network map — how it all connects** | Your devices → server → the internet; the download journey | [open](https://claude.ai/code/artifact/e5bd6be6-6597-4073-85c2-2d500d02c1af) | ✅ built |
| 04 | NAT & port-forwarding | Why we *don't* expose the server to the internet | — | planned |
| 05 | Tailscale deep-dive (WireGuard) | Phase 1 remote access | — | planned |

*Beyond networking, this directory can grow primers on the app's own stack (beets & fingerprinting,
SSE progress, the review queue) if useful — same format.*
