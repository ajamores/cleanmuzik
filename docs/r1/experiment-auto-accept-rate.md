# Experiment — will YouTube songs auto-file themselves?

**Status: complete, 2026-07-11. Answer: no — and here's precisely why, and what to build instead.**

This is the plain-English report of the beets review-queue spike. Its terse companion —
`spike-beets-review-queue.md` — is the lab notebook (every run, API note, and resume-here detail)
for an agent reproducing the work. This document is for *understanding what we learned*. The
binding decisions it produced are **ADR-006** and **ADR-007** in `adr.md`.

---

## What the app is trying to do

You paste a YouTube link. The app downloads the audio — but a YouTube file is *dirty*: the title
is something like `"Fleetwood Mac - Dreams (Official Audio)"`, and it carries no proper album,
year, or cover art. The app's job is to work out **"what song is this, really?"** and stamp it with
clean, correct tags before filing it into Jellyfin.

The tool that does the figuring-out is **beets**. Think of beets as a **customs officer**. A file
arrives with no reliable ID. beets inspects it, matches it against **MusicBrainz** — a giant public
encyclopaedia of every song ever released — and, if confident, stamps it and waves it through.

## The question this experiment had to answer

beets doesn't just say yes/no. For each file it reports a **confidence level**: `none`, `low`,
`medium`, or `strong`. The plan is:

- **`strong`** → wave it through automatically (**auto-accept**).
- Anything weaker → send it to a **review queue** for you to eyeball and approve by hand.

The original plan (the PRD) assumed **~80% of songs would auto-accept** — i.e. the review queue is a
small chore. The whole app is designed around that number. **If it's wrong, the app's shape is
wrong.** So before writing any real code, this throwaway test measured the *actual* auto-accept rate.

## How beets identifies a song — two clues

1. **The text tags** — the artist/title written on the file. Unreliable for YouTube (full of cruft
   like "(Official Audio)").
2. **The acoustic fingerprint** — via a tool called **chroma / AcoustID**. It listens to the actual
   audio and computes a fingerprint, like Shazam. This is the *reliable* clue — it doesn't care what
   the title says.

## Method

1. Downloaded 3 famous songs from YouTube — Take On Me, Never Gonna Give You Up, Dreams —
   deliberately *easy* cases, all certainly in MusicBrainz.
2. Fed them to beets and recorded the confidence it assigned each — **without filing anything**
   (measurement only; nothing was written to disk).
3. Then re-ran it after cleaning the titles, to isolate how much the YouTube cruft was hurting.

## Results

| Version | What beets was fed | Confidence result | Auto-accepted |
|---|---|---|---|
| Raw rip tags | titles as YouTube gives them | `none`, `medium`, `medium` | **0 / 3** |
| Cleaned titles | `"Dreams (Official Audio)"` → `"Dreams"` | `medium`, `medium`, `medium` | **0 / 3** |

Cleaning the titles helped in one real way: it pushed the *correct* match to the top of the list
in every case (and lifted `Dreams` from `none` to `medium`). But **not one famous song ever reached
`strong`.** Auto-accept was zero either way.

## Why — the finding

Two reasons, and the second is the important one:

1. **Title cruft hurt matching.** Cleaning the titles fixed the *ranking* — the right song jumped to
   number one. So a "clean the title first" step is worth building. But on its own it wasn't enough.

2. **A single song, on its own, structurally cannot reach `strong`.** beets is most confident when
   it matches a *whole album* — track 4 of 11, in this order, released this year. A one-off YouTube
   song (a **"singleton"**) has none of that supporting context, so its confidence hits a ceiling at
   `medium` no matter how clean it is. beets is being cautious — correctly — because it lacks
   corroboration.

   **But the fingerprint knew it was Take On Me the whole time.** The audio was identified
   correctly; beets simply wouldn't upgrade that to `strong` on the tag evidence alone.

## What it means for the app

- The PRD's "~80% auto-accept" is **false** for this use case. Left as-is, *almost every song* would
  land in the review queue.
- The fix is **not** to lower beets' standards (that would also let genuinely wrong matches
  through). The fix: **when the acoustic fingerprint is confident and unambiguous, trust it and
  auto-accept** — a custom rule written at the exact point the app hands a file to beets
  (`choose_match` / `choose_item`).
- This confirms the architecture's instinct that **the review queue is the spine of the product**,
  not a rare edge case.

## Decisions this produced

- **ADR-006** — auto-accept keys off dominant AcoustID fingerprint identity, not relaxed thresholds;
  the review queue is the primary path.
- **ADR-007** — beets 2.12 setup facts the backend must honour (MusicBrainz is now a separate
  plugin; the library API doesn't auto-load plugins).

## Honest caveats

- **Sample size is 3.** This is a *directional* result, not a calibrated one. The real product
  number depends on the fingerprint-trust rule, which doesn't exist yet — re-measure on a larger
  sample once it does.
- These were *easy* tracks (famous, well-covered). Obscure or live/remix uploads will fare worse,
  which only strengthens the "review queue is the spine" conclusion.

---

*Companion lab notebook: `spike-beets-review-queue.md`. Binding decisions: `adr.md` (ADR-006, 007).
Durable one-liners: `../learnings.md`.*
