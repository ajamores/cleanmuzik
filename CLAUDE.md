# CLAUDE.md

Guidance for Claude Code (claude.ai/code) working in this repository.

## Start here (read in this order)

1. **`CLAUDE.md`** (this file) — how we work
2. **`cleanmuzik-prd.md`** — product source of truth (scope + design)
3. **`docs/roadmap.md`** — which release is active
4. **`docs/r1/spec.md`** — what R1 builds *(signed off)*
5. **`docs/r1/architecture.md`** — stack diagram + open technical seams (single home)
6. **`docs/r1/adr.md`** — binding decisions; do not silently reverse one
7. **`docs/learnings.md`** — mistakes already paid for; don't repeat them
8. **`docs/workflow.md`** — the build process (DoD rationale, fan-out, verify playbook)
9. **`.claude/hot.md`** — live session state + what's next

**Which release is active, and live session state, are not tracked here** — that's `docs/roadmap.md`
and `.claude/hot.md`. Work tickets in dependency order; each is done per the Definition of Done below.

## What this is

CleanMuzik is a **single-user personal tool** for a clean, richly-tagged Jellyfin music library. Two jobs:

1. **Acquire** — paste a YouTube song/playlist URL → download → identify → tag → land it, organized,
   in the Jellyfin library. The everyday flow.
2. **Migrate + clean** — re-tag and organize the owner's existing library with the same engine.

Jellyfin is the hub (library, storage, streaming, playback); the app is the front door into it.

**Scope truth is `cleanmuzik-prd.md`** — read it before building. The old
`archive/music-cleaner-prd.md` and `archive/cleanmuzik-secret-mode-prd.md` describe an **abandoned**
design (portfolio showcase, Express-middleman stack, hand-rolled ShazamIO + Mutagen, hidden "secret
mode") — do **not** implement from them.

## Current state

R1 and R1.1 have **shipped** (see `docs/roadmap.md`); the app is built, not scaffold. Read the real
implementation:

- `server/` — the **Python/FastAPI** backend: the download → transcode → identify → tag → land
  pipeline (`app/`, e.g. `jobs.py`, `beets_engine.py`, `reviews.py`, `events.py`, `jellyfin.py`).
- `client/` — the real **React 19** UI (job submission, live SSE progress, the review inbox).

The PRD is scope truth; `server/` and `client/` are the built implementation — read them, don't
treat them as stale scaffold to bypass.

## Architecture

Python engine → Python backend, **no Node/Express bridge**. The stack diagram + open seams live in
**`docs/r1/architecture.md`** (single home). Three things to carry in your head:

- **beets is the tagging engine** — never hand-roll one. Plugins do the work: `chroma` (AcoustID),
  `lastgenre` (Last.fm genres), `fetchart` + `embedart` (cover art).
- **The review queue is the product's spine.** beets emits a confidence per track; strong matches
  auto-tag, weak ones (common for YouTube rips) go to a review queue. A UX centrepiece.
- **Progress is SSE**, not polling.

### Hard constraints

The binding constraints — sequential processing (no parallelizing the pipeline), MP3 320 output,
one-failure-continues-the-batch, single-user/no-auth, beets-not-hand-rolled — are **ADR-001–005 in
`docs/r1/adr.md`** (single home). Review checks new code against them; do not silently reverse one.

## Commands

Client (`cd client`): `npm run dev` (Vite) · `npm run build` (`tsc -b && vite build`) · `npm run lint`
· `npm test` (vitest).

Server (`cd server`) — Python/FastAPI. Canonical setup + run in **`server/README.md`** (don't
duplicate here). In short: `uvicorn app.main:app --reload` serves `GET /api/health`; secrets load
from the git-ignored **repo-root** `.env` (spec §6, template `.env.example`). Tests: `pytest` (see
`server/pytest.ini`, `server/tests/`). Packages are managed independently — no root workspace tooling.

**Verifying:** `/verify` runs against `TestClient` *or* the running server over HTTP (`localhost` is
reachable). Two load-bearing hazards — **isolate `DB_PATH` + the beets library to a temp dir** or the
run pollutes the real library, and **`pgrep -af uvicorn` first** (the `--reload` server re-runs its
lifespan against the *live* DB the moment you edit a startup module). Full playbook: `docs/workflow.md`
+ the `/verify` skill.

## Design gate (UI tickets) — before code

A ticket that changes a user-visible **flow or state** passes a design gate *before* component code:
flat HTML scenario screens — one per scenario, **including failure/edge states** — published for owner
sign-off. Runs *ahead of* the Definition of Done, not inside it. Scope: flow/state changes only, **not**
CSS/visual tweaks. Detail + the T-020 evidence: **ADR-016** and `docs/workflow.md`.

## Definition of Done (per ticket)

A ticket is done when there's a receipt, not a claim. Each step earned its place from a mistake — the
**rationale + evidence for every step is in `docs/workflow.md`**; the imperatives are:

1. **Review pass** — `/code-review` on the diff (correctness + cleanup).
2. **Acceptance check** — re-read the ticket's own **"Done when"** + the spec section it cites, and
   check the diff against them. Different question from step 1: "is this the thing we asked for?", which
   a diff review structurally can't see. **If the spec's payload can't deliver the ask, stop and amend
   — don't build the nearest thing.**
3. **Observable artifact** — for pipeline tickets, `/verify`: drive the real flow, confirm the real
   side effect. "Looks right" is not done; "I watched it happen" is.
4. **Transcribe corrections to their owning store, as they come up** — not onto the board. Route:
   future-code decision → `adr.md`; mistake paid for → `learnings.md`; ticket scope/status →
   `tickets.md`; scope/intent → the PRD. **Only branch state / work-in-flight / next belongs on the board.**
5. **Integration** — merge onto `main`, suite green *there*. Passing 1–4 in a worktree is **built**,
   not **done**. **"Done" always implies integrated.**
6. **Ledger sync** — the closing commit **flips that ticket's own status line in the same commit**. A
   closed ticket the ledger still calls `todo`/`in-build` invites a rebuild of shipped code.

Fan-out mechanics (worktrees, one-at-a-time integration, owner adjudicates findings): `docs/workflow.md`.

## Hosting

Runs where Jellyfin runs — **home, not a VPS**. Phase 0: the owner's laptop at `localhost`. Phase 1:
an always-on box reached via **Tailscale**. Phased plan: `cleanmuzik-prd.md` §9; host hardware:
`docs/roadmap.md` (R3+).

## Session board

Working state lives in `.claude/hot.md` (the repo's hot board), per `/hot` and `/maintenance`. Tasks
and open items go there and in the PRD's open-questions section — not in this file.
