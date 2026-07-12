# Spike log — beets review-queue seam

**Status: RESOLVED, 2026-07-11.** Seam proven end-to-end; auto-accept rate measured; outcome
recorded as **ADR-006** (fingerprint-trust) and **ADR-007** (beets 2.12 plugin loading). This is
the working journal for the one gate before `spec.md`: prove how beets surfaces candidate matches
to a custom UI, and **measure the real auto-accept rate** for YouTube singleton imports. Read
`architecture.md` for the seam design this validated.

## Bottom line (the measured answer)

On 3 well-known, AcoustID-covered tracks imported as **singletons**, with fingerprint + tags:
**auto-accept (strong) = 0/3.** With raw YouTube-rip tags: `{none:1, medium:2}`. After cleaning the
title cruft (`"Fleetwood Mac - Dreams (Official Audio)"` → `"Dreams"`): **`{medium:3}`** — cleaning
promoted `Dreams` none→medium and ranked the *correct* candidate #1 in every case (top conf 0.889),
but **nothing reached `strong`**. The ~0.11 residual distance is a structural floor for singletons
(no album/track#/year to corroborate). Conclusion → ADR-006: auto-accept must key off dominant
AcoustID fingerprint identity in `choose_match`, not tag distance; the review queue is the
**primary** path, not the ~20% exception the PRD assumed. Sample is tiny (3) — directional, not
calibrated; a larger measured sweep belongs in the build once the fingerprint-trust rule exists.

This file is a lab notebook, not a spec — it records what was tried, what broke, and where we
stopped, so the debug can resume cold. Durable one-line rules also land in `../learnings.md`.
**For the plain-English writeup of what this experiment found and why, read the companion report
`experiment-auto-accept-rate.md`.**

## Goal

A throwaway script drives `beets.importer.ImportSession` on a few sample YouTube rips, reads
`task.rec` + `task.candidates` at the choice hook (instead of prompting), records the verdict,
writes nothing to disk, and reports the strong-match (auto-accept) rate. That rate is the number
the PRD's "~80%" claim needs replaced with a measured one — YouTube tracks import as **singletons**,
so the album-match confidence the PRD assumed does not apply.

## Environment (as built this session — all in the scratchpad, throwaway)

- **beets 2.12.0**, Python 3.10.12, in a venv. yt-dlp 2026.06.09 and ffmpeg 4.4.2 were already on the box.
- **venv gotcha:** `python3 -m venv` fails here — `ensurepip` unavailable (the `python3.10-venv`
  system package isn't installed, and installing it needs sudo we don't have). Workaround, no sudo:
  `pip install --user virtualenv` then `python3 -m virtualenv <dir>` — it bundles its own pip.
- **fpcalc gotcha:** the `chroma` plugin needs `fpcalc` (Chromaprint). `apt install
  libchromaprint-tools` needs sudo. No-sudo workaround: download the **static** binary from the
  Chromaprint GitHub release (`v1.5.1/chromaprint-fpcalc-1.5.1-linux-x86_64.tar.gz`), point the
  `FPCALC` env var at it. pyacoustid honours `FPCALC`. Confirmed working (fingerprints a file).
- Sample audio: 3 tracks pulled with `yt-dlp -x --audio-format mp3` via `ytsearch1:` (avoids
  hardcoded dead URLs) — a-ha "Take On Me", Rick Astley "Never Gonna Give You Up (2022 Remaster)",
  Fleetwood Mac "Dreams". All heavily covered in AcoustID/MusicBrainz — a deliberately *fair* test.

## beets 2.12 API notes (differ from most online tutorials, which are 1.x)

- `importer` is now a **package**. The action enum is `Action` (capitalised), not `action`:
  `from beets.importer import ImportSession, Action`; skip a task by returning `Action.SKIP`.
- Session choice hooks: `choose_match(task)` = album path; **`choose_item(task)` = singleton path**
  (the YouTube flow). Override both; also stub `resolve_duplicate` and `should_resume`.
- `Recommendation` values: `none / low / medium / strong`. Auto-accept == `strong`.
- `plugins.load_plugins()` takes **no arguments** in 2.12 — it reads `config['plugins']` itself and
  emits `pluginload`. (Older signature took a name list; passing one raises TypeError.)

## The load-bearing finding so far

**The beets library API does NOT auto-load plugins — only the CLI (`beets.ui`) does.** Driving
`ImportSession` programmatically without first calling `plugins.load_plugins()` means **chroma
never runs**, so singleton lookup silently falls back to tag-only MusicBrainz matching. For a
YouTube rip (junk tags) that yields **zero candidates, `rec = none`** — a false 0% that looks like
a real measurement. This is the single most important thing to carry into the real backend: the
FastAPI service must load plugins explicitly at startup.

## Runs

1. **Run 1 — `action` import error.** Script written against 1.x API. Fixed to `Action`.
2. **Run 2 — 0/3, `rec=none`, 0 candidates.** Looked like a real result; it was not — plugins
   never loaded (see finding above). Isolation test proved fingerprint + AcoustID lookup work:
   beets' own app key `1vOwZtEn` returns the correct a-ha "Take On Me" recording. Also observed a
   **transient `status: error`** from the AcoustID free service that cleared on retry — the tier is
   rate-limited/flaky; the real pipeline needs retry/backoff (candidate ADR / learnings item).
3. **Run 3 — added `plugins.load_plugins()`.** Confirms `plugins loaded: ['chroma']` — but **still
   0/3, `rec=none`, 0 candidates.** This is the current blocker.

4. **Run 4 — enabled `plugins: musicbrainz chroma`.** Root-caused the empty candidates:
   `item_candidates` returns `[]` when `self.mb is None`, and **in beets 2.12 MusicBrainz is its
   own plugin** that my config hadn't enabled (chroma resolves fingerprint MBIDs *through* it). New
   symptom surfaced: a MusicBrainz `400` on `…/recording?query=` — the autotagger's text-search ran
   with an **empty query** because my `-x` download had stripped all tags. → ADR-007.
5. **Run 5 — re-downloaded with `--embed-metadata`** (realistic: real rips carry the video's
   title/artist). Candidates appeared. `{none:1, medium:2}`; 0 strong. `Dreams` was `none` — its
   correct match ranked 3rd, buried under the title cruft `"Fleetwood Mac - Dreams (Official
   Audio)"`.
6. **Run 6 — cleaned the titles** (strip `(Official Audio)` etc. + leading `Artist - `). Result
   `{medium:3}`, correct candidate #1 everywhere at conf 0.889 — **but still 0 strong.** Proved the
   two findings behind ADR-006: (a) title-cleaning is a real, cheap lever for *correctness/ranking*;
   (b) it does not cross the `strong` bar — a bare singleton has a ~0.11 distance floor.

## Resolution

- **Seam works.** Subclassing `ImportSession` and overriding `choose_item` (singleton) /
  `choose_match` (album) gives clean access to `task.rec` + ranked `task.candidates` (each a
  `TrackMatch(distance, TrackInfo)`) at decision time, and returning `Action.SKIP` leaves disk
  untouched. This is the review-queue seam the architecture assumed — confirmed against beets 2.12.
- **Auto-accept rule → ADR-006:** trust dominant AcoustID fingerprint identity, don't relax
  thresholds. **Plugin loading → ADR-007.**
- Spike files live in the session scratchpad (`spike.py`, `debug_chroma.py`, `fpcalc`,
  `spike-audio/`, `spike-audio-clean/`, `beetsdir/`, `beets-spike-venv/`) — **ephemeral**; rebuild
  per the Environment section if a later session needs to re-measure on a larger sample.

## Still ahead (before `spec.md`)

- **Re-measure on a larger sample** once the fingerprint-trust `choose_match` rule exists — the 0%
  here is directional (n=3), and the real product number depends on that rule, not default config.
- The three owner facts the spec needs: Jellyfin watched-folder path; existing-library
  location/format/size; where the Last.fm/AcoustID keys live.
- Then write `spec.md`.
