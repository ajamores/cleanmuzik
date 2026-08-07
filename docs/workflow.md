# Build workflow — the mechanics behind the rules

The **rules** live in `CLAUDE.md` (Definition of Done, design gate, the reading order). This file
holds the **why** and the **procedure** — the parts a session only needs while actually doing the
thing, kept out of the always-loaded `CLAUDE.md` so they cost nothing on turns that don't touch them.

If a rule here and a rule in `CLAUDE.md` ever disagree, `CLAUDE.md` wins and this file is stale — fix it.

---

## Definition of Done — the rationale behind each step

`CLAUDE.md` lists the six steps as terse imperatives. Each earned its place from a mistake; the
evidence is filed in the store named, not restated here.

1. **Review pass** (`/code-review`). Correctness bugs + cleanup, read off the diff.

2. **Acceptance check** — a *different question* from the review pass, with different evidence.
   `/code-review` asks "is this code correct?"; this asks "is this the thing we asked for?" A diff
   review structurally **cannot** see the answer, because the ticket and the spec aren't in the diff.
   Code can be flawless and still not be the ticket. **If the ticket asks for something the spec's
   payload can't deliver, stop and amend — don't build the nearest thing.**
   *Why it's a separate step:* T-016 asked for cover art on `track.tagging` from `4a2f60f` until
   2026-07-17; that event has never carried art. Four tickets shipped through high-effort reviews —
   two of which caught data-loss and hang-forever bugs — and none caught it, because none of them was
   *asking*. → **ADR-010**.

3. **Observable artifact** — for pipeline tickets, `/verify`: drive the actual flow and confirm the
   real side effect (a correctly-tagged MP3 320 with embedded art landed in the Jellyfin folder).
   "The code looks right" is not done; "I watched it happen" is.

4. **Transcribe corrections to their owning store, at the moment they come up — not onto the session
   board.** A lesson written to `.claude/hot.md` instead of its store is a filing bug: the board is
   overwritten, the store is forever. (This lapsed from T-012 to T-015 and cost a whole session to
   unwind — `learnings.md` 2026-07-16.) Route by owner:
   - a decision that constrains future code → `docs/r1/adr.md`
   - a mistake paid for → `docs/learnings.md`
   - ticket scope/status → `docs/r1/tickets.md` (per-release `tickets.md`)
   - scope or intent → `cleanmuzik-prd.md`
   - **only** branch state / work-in-flight / what's next → `.claude/hot.md`

5. **Integration** — merge onto `main` and confirm the suite is green *there*. A ticket that passes
   1–4 in a worktree is **built**, not **done**: it isn't in the product until it's on `main`. Steps
   1–4 answer "is the work good?"; this answers "is it shipped?" — a different question, and the one
   that was unwritten until a ticket sat verified-but-unlanded and got called "done" (owner
   correction, 2026-07-17). **"Done" always implies integrated.**

6. **Ledger sync** — the commit that closes a ticket flips that ticket's own status line in the same
   commit, making the ledger true at merge time the way step 5 does integration. Doctrine ("remember
   to update it") is not enough — it existed as step 4 and still failed. A closed ticket the ledger
   still calls `todo`/`in-build` is as dangerous as an unmerged one it calls done: it invites a
   rebuild of shipped code. This bit **twice in one day** (`learnings.md` 2026-08-05) — T-102 read
   `todo` for three days after merging and a planning pass nearly rebuilt shipped code; T-040 was
   nearly re-fixed after an unrelated commit had already closed it.

`/code-review` and `/verify` are built-in Claude Code skills, not project code — `/code-review`
*reads* the diff, `/verify` *runs* it. Both cost tokens per run; `/verify` needs the app runnable.

---

## Design gate (UI tickets) — the rationale

The rule (in `CLAUDE.md`): a ticket that changes a user-visible **flow or state** passes a design
gate — flat HTML scenario screens, one per scenario including failure/edge states, owner-signed-off
— *before* component code, and *ahead of* the Definition of Done.

The detail: scope is flow/state changes only, **not** CSS/visual-only tweaks. Keep the screens flat
HTML with no live state — the moment they try to *be* the app, the gate costs more than it saves. It
does **not** replace `/verify`: platform-behaviour bugs (EventSource through the Vite proxy, native
`<input>` validation) still need a real browser; the gate narrows what's left for the browser, it
doesn't remove it. Full rationale + the T-020 evidence: **ADR-016**.

---

## Parallel build (fan-out) — the mechanics that work

Proven on T-002/03/04 and again on T-013 ∥ T-015. Reuse this shape; don't improvise a new one.

- **Only fan out tickets whose file sets are disjoint** (e.g. `server/` ∥ `client/`) and whose deps
  are already landed. Overlap means merge pain that costs more than the parallelism saves.
- **One worktree per agent.** Give each a self-contained brief that names the load-bearing risks up
  front — the agent can't see the others' work.
- **Integrate one at a time onto `main`**, in dependency order (the ticket others depend on lands
  first). Merge `--no-commit`, run the suite, `/code-review` the diff **in the working tree before
  committing**, reconcile shared files (`requirements.txt`, `README.md`, `main.py`) by hand.
- **The owner adjudicates every finding** — accept/reject is not the agent's call. Record rejections
  with the reason; they're evidence, not noise.

---

## Verifying — the full playbook

`CLAUDE.md` keeps the two load-bearing *warnings* inline. The full recipe lives in the **`/verify`
skill** (`.claude/skills/verify/SKILL.md`); the isolation hazards are in `docs/learnings.md`.

`localhost` HTTP is reachable from here (disproved the "sandbox blocks live sockets" claim,
`learnings.md` 2026-07-19), so `/verify` has two handles:

- **`TestClient`** — no server needed, best for route/pipeline logic. Drives the real pipeline (real
  yt-dlp/ffmpeg/fpcalc/AcoustID) without a server up.
- **The running server over HTTP** — `curl http://localhost:8137/...`, including `POST /api/jobs`,
  SSE, and the review endpoints. Exercises the real ASGI stack, DB, and Vite proxy target. Prefer it
  when the question is "does the deployed thing behave".

What still genuinely needs the **owner at a browser**: DOM rendering, `EventSource` reconnect,
DevTools offline toggling, and anything visual in Jellyfin. Scope tickets against *that* line, not
against a socket wall that doesn't exist.

Two standing hazards (also inline in `CLAUDE.md`):
- **Isolate `DB_PATH` + the beets library to a temp dir**, or the run pollutes the real library.
- **Check for a running dev server first** (`pgrep -af uvicorn`). It runs with `--reload`, so editing
  a module that mutates state at startup — `db.py` especially — re-runs the lifespan against the
  **live** database within seconds, unprompted.
