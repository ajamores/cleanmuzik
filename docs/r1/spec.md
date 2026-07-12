# R1 Spec — CleanMuzik

> **Status: SKELETON — not yet written.** This is the structure; the content gets filled in
> together, with real answers. The test of done: *an agent that has never seen this project
> could read this file and build the right thing without asking a question.* If a section
> would still make it guess, that section has a hole.

Product brief this narrows: `cleanmuzik-prd.md`.

---

## 1. Goal of R1

_One paragraph. What does shipping R1 give the owner that he doesn't have today?_

## 2. In scope

_Bullet list. The specific things R1 builds._

## 3. Explicitly out of scope

_Bullet list. Things R1 does NOT do — the fence that stops scope creep. e.g. playlists?
migrate-existing? review-queue art picker?_

## 4. User flow (R1)

_Step by step, paste-URL → landed-in-Jellyfin. What the owner sees at each step._

## 5. Behaviour details

- **Match confidence gate:** _what counts as strong (auto-tag) vs weak (review queue)?_
- **Review queue:** _what does it show for a weak match? what can the owner pick?_
- **Failure of one track:** _surface per-track error, continue batch — how is it shown?_
- **Output:** _MP3 320 (decided, ADR-002)._

## 6. Interfaces

- **API routes:** _FastAPI endpoints — list them._
- **SSE events:** _event names + payload shape for live per-track progress._
- **Disk layout:** _the Jellyfin folder structure beets writes into (Artist/Album/…)._

## 7. Acceptance checklist (R1 is "done" when…)

_Checkable items, not vibes. e.g. "Pasting a single YouTube URL lands a correctly-tagged
MP3 320 with embedded art in the Jellyfin watched folder, visible in Jellyfin after a scan."_
