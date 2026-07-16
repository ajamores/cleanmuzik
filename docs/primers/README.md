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

## App-stack track

Not networking — the engine itself. Same format (versioned HTML source + published Artifact).

| # | Primer | Ties to | Read it | Status |
|---|--------|---------|---------|--------|
| A1 | **The fingerprint-trust gate** | T-007 — the match confidence gate (ADR-006); the pre-build walkthrough | [open](https://claude.ai/code/artifact/c8ecf382-a996-48bf-a9a7-d6a79051663d) · [source](A1-fingerprint-trust-gate.html) | ✅ built |
| A2 | **It filed its first song** | T-007 done — plain-terms status + the Door A/B decision | [open](https://claude.ai/code/artifact/99232026-d1ba-42a9-97b9-4252f834822a) · [source](A2-first-song-filed.html) | ✅ built |
| A3 | **Score vs Gap — the auto-accept experiment** | T-008 — tuning the thresholds on 25 real songs (ADR-006 addendum) | [open](https://claude.ai/code/artifact/b2d9e8f0-7902-4f09-979e-bd4e0f908df1) · [source](A3-score-vs-gap-experiment.html) | ✅ built |
| A4 | **The whole line runs** | T-012 — the six stages wired into one conveyor belt (worker thread + sequential queue + job routes); technical + plain-words | [open](https://claude.ai/code/artifact/3990d7ec-6a54-40a3-89d1-216f9ade4d8e) · [source](A4-the-conveyor-belt.html) | ✅ built |
