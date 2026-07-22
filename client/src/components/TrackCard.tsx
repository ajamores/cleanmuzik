import { useEffect, useRef, useState } from 'react'
import { ApiError, getJob, getReview, type ReviewCandidate } from '../api'
import { ReviewPanel } from './ReviewPanel'
import './TrackCard.css'

/**
 * The stages a track moves through (spec §4 / SSE event names in §6). The shell
 * (T-015) only ever renders `queued`; the full set is declared here so T-016
 * can drive the card off the live stream without redefining the model.
 */
export type Stage =
  | 'queued'
  | 'downloading'
  | 'transcoding'
  | 'identifying'
  | 'review_required'
  | 'tagging'
  | 'done'
  | 'error'

const STAGE_LABEL: Record<Stage, string> = {
  queued: 'Queued',
  downloading: 'Downloading',
  transcoding: 'Transcoding',
  identifying: 'Identifying',
  review_required: 'Needs review',
  tagging: 'Tagging',
  done: 'Done',
  error: 'Error',
}

/** Spec §6 event name → the stage it puts the card in. (`ping` is absent: it's a
 *  keepalive and must not move the card.) */
const EVENT_STAGE: Record<string, Stage | undefined> = {
  'job.queued': 'queued',
  'track.downloading': 'downloading',
  'track.transcoding': 'transcoding',
  'track.identifying': 'identifying',
  'track.review_required': 'review_required',
  'track.tagging': 'tagging',
  'track.done': 'done',
  'track.error': 'error',
}

/**
 * The events that end the *stream* (not necessarily the owner's workflow).
 *
 * The server closes the channel on every terminal path — done, error AND review
 * (`_finish` → `bus.close`) — and a browser EventSource reads that EOF as a
 * dropped connection and auto-reconnects (~3s). The route then re-streams an
 * already-terminal job: replay, EOF, reconnect… forever. So the card closes the
 * stream itself on all three. `review_required` is terminal for the stream even
 * though T-017 resolves the review afterwards (it re-subscribes then).
 */
const STREAM_TERMINAL: ReadonlySet<string> = new Set([
  'track.done',
  'track.error',
  'track.review_required',
])

/** Spec §6 `track.error.stage`. */
type ErrorStage = 'download' | 'transcode' | 'identify' | 'tag' | 'land' | 'scan'

const ERROR_STAGE_LABEL: Record<ErrorStage, string> = {
  download: 'Download',
  transcode: 'Transcode',
  identify: 'Identify',
  tag: 'Tagging',
  land: 'Landing',
  scan: 'Jellyfin scan',
}

/** The rail the card animates along: spec §4 step 3 → 4 → 6 → 7. */
const RAIL: { key: ErrorStage; label: string }[] = [
  { key: 'download', label: 'Download' },
  { key: 'transcode', label: 'Transcode' },
  { key: 'identify', label: 'Identify' },
  { key: 'tag', label: 'Tag' },
  { key: 'land', label: 'Land' },
]

/** Which rail step a stage lights up. `done` completes every step; `error` is
 *  positioned from the stage the server named, so the rail itself shows where it
 *  broke. `scan` shares the Land step (both are "getting it into the library"). */
const STAGE_STEP: Record<Stage, number> = {
  queued: -1,
  downloading: 0,
  transcoding: 1,
  identifying: 2,
  // A weak-match park is an UNFINISHED identify awaiting the owner's pick — the review
  // IS the identify decision (which MusicBrainz match), not a tagging one. So it sits on
  // Identify (2), not Tag (3): parking on Tag lit Identify as complete on a track that
  // never got a confident match, and pre-lit Tag before any tagging happened (T-020,
  // carried from a T-016 review). Tagging only fires after the owner resolves.
  review_required: 2,
  tagging: 3,
  done: RAIL.length,
  error: -1,
}

/** Which rail step an error stage lights up — derived from RAIL so the two can't
 *  drift when a step is added or reordered (T-020, carried from a T-016 review; it
 *  was a hand-kept copy of RAIL's indices). `scan` has no rail step of its own — it
 *  shares Land, both being "getting it into the library" — so it maps to Land's index. */
const ERROR_STEP: Record<ErrorStage, number> = {
  ...(Object.fromEntries(
    RAIL.map((step, i) => [step.key, i]),
  ) as Record<ErrorStage, number>),
  scan: RAIL.findIndex((s) => s.key === 'land'),
}

/** `track.tagging.chosen` / the display subset of `track.done.tags`. Every field
 *  is optional: the server nulls what it doesn't know. */
interface Match {
  title?: string | null
  artist?: string | null
  album?: string | null
  year?: number | null
}

interface DoneTags extends Match {
  genre?: string | null
  has_art?: boolean | null
  has_lyrics?: boolean | null
}

interface Landed {
  path?: string | null
  tags?: DoneTags | null
}

interface TrackError {
  stage: ErrorStage | null
  message: string
}

/** The `track.review_required` payload the panel renders from (spec §6). `rec`
 *  tells the panel which question it's asking; `candidates` is empty for a
 *  duplicate (the panel fetches that detail itself). */
interface ReviewInfo {
  reviewId: string
  rec: string | null
  query: string
  candidates: ReviewCandidate[]
  /** Set only when a resume FAILED and re-parked this same review (T-029): the reason
   *  the previous pick couldn't be applied, so the owner isn't silently sent back to
   *  the panel. Absent on a first park. */
  message?: string | null
}

interface TrackCardProps {
  jobId: string
  url: string
}

/**
 * One track's live card, keyed by job id.
 *
 * Subscribes to `GET /api/jobs/{job_id}/events` and animates off the spec §6
 * event names (T-016). Three things about that stream are load-bearing:
 *
 * 1. **Every event is named**, so `onmessage` never fires — each name gets its
 *    own `addEventListener`.
 * 2. **The stream replays its buffer on connect** (the card mounts a beat after
 *    `POST /api/jobs`, by which time `job.queued` and `track.downloading` may
 *    already have fired), so handlers arrive in a burst and must be correct
 *    out of a burst — each one is an idempotent assignment, never a transition
 *    computed from the previous stage.
 * 3. **The server closes the channel on every terminal path** and EventSource
 *    reconnects on EOF — see STREAM_TERMINAL above.
 */
export function TrackCard({ jobId, url }: TrackCardProps) {
  const [stage, setStage] = useState<Stage>('queued')
  // T-026: the pasted URL named one song but carried a curated album/playlist, so the
  // other tracks were not taken. A property of the URL, not a stage — shown under the
  // URL through the whole run. The server rides `list_kind` on every `job.queued`
  // (acquire AND resolve-reopen), so a reload rebuilds it; the set-once-if-present here
  // is belt-and-braces against any future job.queued that omits it.
  const [listKind, setListKind] = useState<'album' | 'playlist' | null>(null)
  // Set by `track.tagging` ONLY. The done payload is not written through to it:
  // one display concern, one writer. `displayMatch` below derives the rest.
  const [tagged, setTagged] = useState<Match | null>(null)
  const [landed, setLanded] = useState<Landed | null>(null)
  const [error, setError] = useState<TrackError | null>(null)
  // Detached, NOT failed: the stream is unusable but the snapshot says the job is
  // fine. Kept separate from `error` so the card doesn't claim a healthy job died
  // — the owner would re-paste the URL and duplicate it.
  const [streamLost, setStreamLost] = useState<string | null>(null)
  // High-water mark of the rail: the furthest step actually reached. The rail must
  // never walk backwards, least of all when we lose the stream mid-job.
  const [reachedStep, setReachedStep] = useState(-1)
  // The `track.review_required` payload, captured so the panel can render it.
  const [review, setReview] = useState<ReviewInfo | null>(null)
  // Bumped every time a fresh `track.review_required` is captured, and folded into the
  // panel's `key`. A T-029 re-park re-emits the SAME review_id, so keying on the id
  // alone would REUSE the panel instance — whose `submitting` latched true on the pick
  // that just failed — leaving the owner a re-shown panel with dead buttons. Bumping
  // this remounts it, resetting the latch, exactly as a brand-new review would.
  const [reviewEpoch, setReviewEpoch] = useState(0)
  // Bumped when the owner resolves a review: it re-runs the effect below, opening a
  // FRESH EventSource for the resume episode (T-016 closed the old stream on
  // `review_required`; T-014 re-opens the channel server-side before the resolve
  // POST returns). The reconcile-on-death fallback is reused wholesale, which is not
  // optional: `reject`/`keep_existing` settle the job to `done` with NO terminal
  // `track.*` event, so the fresh stream closes silently and only the GET /api/jobs
  // snapshot tells the card it's done.
  const [episode, setEpisode] = useState(0)
  // The rail high-water mark, kept in a ref so it SURVIVES the effect re-run on
  // resolve. Without it `maxStepSeen` would reset to -1 and a replayed resume event
  // could repaint an already-completed step as fresh.
  const reachedRef = useRef(-1)

  // Subscribes to the job's SSE stream. `jobId` is in the dep array because the effect
  // reads it, but it never actually changes for a mounted card: App.tsx keys each card
  // by jobId, so a new job is a new instance with fresh state, not a jobId swap on this
  // one (which would re-subscribe but leave the previous job's stage/landed/rail behind).
  // `episode` is the real re-run trigger — a resolved review re-opens the stream.
  useEffect(() => {
    const es = new EventSource(`/api/jobs/${jobId}/events`)
    // Guards a `setState` from a snapshot that resolves after unmount, and stops
    // the error path from re-firing once we've deliberately given up.
    let unmounted = false
    let maxStepSeen = reachedRef.current
    let sawTerminalEvent = false
    // At-most-once guard for the review re-hydration below: a snapshot that finds the
    // job parked fetches the panel's row once, not on every retry's snapshot.
    let hydratedReview = false
    // One ANSWERED snapshot per outage — NOT a retry budget.
    //
    // T-016 originally bounded the reattaching with a consecutive-failure counter
    // and gave up permanently when it ran out. Two review passes killed three
    // successive versions of that logic (see docs/learnings.md, 2026-07-18): the
    // counter was defeatable by the server's replay, then reset too rarely, and
    // "give up" always fired in the wrong direction — instantly on a restart blip,
    // or never at all. The mistake was building a failure POLICY that nothing here
    // can execute or observe.
    //
    // So there is no policy now. EventSource already retries a dropped connection
    // on its own, and the server replays its buffer to every new subscriber, so
    // recovery is the platform's job and it does it losslessly. This flag exists
    // only to make sure the ONE thing the stream structurally cannot report — a
    // job that finished with no §6 event (the duplicate skip, `jobs.py:368`, or a
    // restart's empty replay) — is asked about once per outage rather than on every
    // retry. The nuance the browser taught us (T-020): the "one" is one *answered*
    // check. A check that gets NO answer (backend still down) doesn't count — it
    // clears the latch (see checkOnce's transient catch) so the next retry asks again
    // once the backend returns. Latching a no-answer check is what froze the card on a
    // restart. One *answered* snapshot per outage is the ADR-005 boundary; one per
    // retry against a live server would be polling.
    let outageChecked = false

    /**
     * Every §6 event is NAMED (`event: track.downloading`), and `onmessage` only
     * ever fires for unnamed/`message` frames — so a card wired to `onmessage`
     * sits on "Queued" forever and looks like a server bug. One listener per
     * name, and each one owns the whole reaction: the stage, the payload, and
     * closing the stream if the name is terminal.
     */
    const on = (name: string, handler?: (data: Record<string, unknown>) => void) => {
      es.addEventListener(name, (e: MessageEvent<string>) => {
        let data: Record<string, unknown> = {}
        try {
          const parsed: unknown = JSON.parse(e.data)
          if (parsed && typeof parsed === 'object') data = parsed as Record<string, unknown>
        } catch {
          // A malformed frame shouldn't kill the card — the event name alone
          // still carries the stage, which is the part that must not be lost.
        }
        // The stream is delivering, so whatever outage preceded this is over.
        outageChecked = false
        setStreamLost(null)
        const next = EVENT_STAGE[name]
        if (next) {
          setStage(next)
          // High-water mark only: a replayed burst re-delivers earlier steps and
          // must never walk the rail backwards.
          const step = STAGE_STEP[next]
          if (step > maxStepSeen) {
            maxStepSeen = step
            reachedRef.current = step
            setReachedStep(step)
          }
        }
        handler?.(data)
        if (STREAM_TERMINAL.has(name)) {
          sawTerminalEvent = true
          es.close()
        }
      })
    }

    on('job.queued', (data) => {
      if (data.list_kind === 'album' || data.list_kind === 'playlist') {
        setListKind(data.list_kind)
      }
    })
    on('track.downloading')
    on('track.transcoding')
    on('track.identifying')
    on('track.review_required', (data) => {
      // Capture the payload T-017's panel renders from. `rec` picks the question
      // (weak match vs duplicate); on a FIRST park the candidates ride inline (rich),
      // so a weak match needs no re-hydration round-trip. STREAM_TERMINAL still closes
      // the stream here — the panel re-subscribes via `episode` once the owner resolves.
      const reviewId = asString(data.review_id) ?? ''
      // Present only on a T-029 re-park (a resume that failed on the releasable path).
      const message = asString(data.message)
      setReview((prev) => ({
        reviewId,
        rec: asString(data.rec),
        query: asString(data.query) ?? '',
        // A re-park re-offers the SAME recording, but its inline candidates are id-only
        // (the rich rows died with the failed resolve). Keep the rich rows already on
        // screen from the first park until hydrateReview refreshes them (finding #7),
        // rather than flashing "Unknown title" rows — or, if the hydrate is slow/failing,
        // showing them until it lands. A first park (or a re-park of a *different* review
        // than the panel is showing) has no prior rich rows to keep, so it uses its own
        // inline candidates — which on a first park are already rich.
        candidates:
          message && prev?.reviewId === reviewId
            ? prev.candidates
            : asCandidates(data.candidates),
        message,
      }))
      setReviewEpoch((n) => n + 1)
      // A re-park's inline candidates are id-only (the rich rows died with the failed
      // resolve's in-memory result), so upgrade them from the durable row (finding #1).
      // Only on a re-park — a first park is already rich and needs no round-trip.
      if (message && reviewId) void hydrateReview(reviewId)
    })
    // A keepalive with an empty payload — registered only so the catalogue here
    // is complete and it's clear it's known and deliberately inert.
    on('ping')

    on('track.tagging', (data) => {
      setTagged(asMatch(data.chosen))
    })
    on('track.done', (data) => {
      setLanded({ path: asString(data.path), tags: asDoneTags(data.tags) })
    })
    on('track.error', (data) => {
      setError({
        stage: asErrorStage(data.stage),
        message: asString(data.message) || 'The job failed.',
      })
    })

    /**
     * The stream died without a terminal event. EventSource can't read a status
     * code — a 404 (unknown job), a dead backend, and a *successful but
     * event-less* finish (the duplicate skip, which `_finish` closes with the
     * sentinel and no §6 event) all land here identically.
     *
     * So ask the one route that can tell them apart: `GET /api/jobs/{id}` — spec
     * §6's own "reconnect / SSE fallback" snapshot, which `app.jobs` explicitly
     * points the client at for the skip path. One shot, on stream death only:
     * this is not polling (no timer, ADR holds).
     *
     * If the job is still running there is nothing to do: EventSource reconnects
     * by itself and the replay buffer makes that lossless. We only act on a
     * TERMINAL answer, which is the case the stream cannot deliver.
     *
     * Deliberately NOT here: any notion of giving up. Deciding when a stream is
     * "too broken to keep trying" needs evidence this sandbox cannot produce
     * (real drops, real restarts, real races), and three attempts at that policy
     * shipped three different wrong answers. Reattach-with-backoff is its own
     * ticket, to be built where it can be driven. Until then the platform's own
     * retry is the whole recovery story, and it is a good one.
     */
    /**
     * Refill the review panel from `GET /api/reviews/{id}` when the SSE payload was
     * lost (a restart wipes the in-memory channel the candidates rode in on). Best
     * effort: on failure the card keeps the "parked" note and a later reconcile can
     * try again — never worse than the null-`review` state this replaces.
     */
    async function hydrateReview(reviewId: string, remount = false) {
      try {
        const row = await getReview(reviewId)
        if (unmounted) return
        // `remount` controls the epoch bump. The live re-park path (review_required
        // handler) already bumped, so it passes false — bumping again would remount a
        // second time and drop an in-progress selection. The reconnect FALLBACK path
        // (checkOnce → here) never bumped, so it passes true: without a remount, a panel
        // whose `submitting` latched on the failed pick is reused with its buttons dead,
        // and the closed stream can never re-enable them (finding #4). Bumping when the
        // panel was null (a fresh restart mount) is harmless — there is nothing to lose.
        if (remount) setReviewEpoch((n) => n + 1)
        setReview({
          reviewId: row.review_id,
          rec: row.rec,
          query: row.query,
          candidates: row.candidates,
          // The reason a re-park happened is persisted on the row (T-029, finding #2),
          // so it survives the reconnect/reload this path recovers from — the live SSE
          // `message` is already gone by the time we're here.
          message: row.last_error,
        })
      } catch {
        // 404 (resolved/gone) or a transient failure: leave the note, allow a retry
        // on the next outage by NOT latching `hydratedReview` back — a resolved
        // review will simply keep 404ing, which is harmless.
      }
    }

    async function checkOnce() {
      try {
        const snap = await getJob(jobId)
        // Re-check AFTER the await: the stream may have reconnected and replayed a
        // terminal event while this was in flight. Acting on a stale snapshot is
        // how a finished card got a "still running" notice pasted under its path.
        if (unmounted || sawTerminalEvent) return
        if (snap.status === 'done') {
          es.close()
          setStage('done')
          // Recover the landing receipt the dead stream never delivered (T-020). The
          // durable snapshot carries `path` + `tags` for a landed job, so a card that
          // reconnected after `track.done` was lost still shows *where the song went*
          // instead of a bare "Done". Absent for a duplicate-skip "done" (nothing
          // landed) — `asString`/`asDoneTags` narrow that to null, and `displayMatch`
          // keeps whatever `track.tagging` already showed. Off-the-wire, so narrowed.
          if (snap.path || snap.tags) {
            setLanded({ path: asString(snap.path), tags: asDoneTags(snap.tags) })
          }
        } else if (snap.status === 'review') {
          es.close()
          setStage('review_required')
          // The panel's candidates ride the SSE event, which a restart wipes — so on
          // this fallback path `review` may be null and the card would show a dead
          // "parked" note with no way to resolve. The snapshot carries the review_id;
          // re-hydrate the panel from it. Skip if we already have it (a live park that
          // merely lost the stream after review_required arrived).
          if (snap.review_id && !hydratedReview) {
            hydratedReview = true
            // remount: this fallback may be recovering a panel left mid-submit by a
            // failed pick; a remount clears its `submitting` latch so the buttons live
            // again (finding #4). Harmless on the fresh-restart mount (review was null).
            void hydrateReview(snap.review_id, true)
          }
        } else if (snap.status === 'error') {
          es.close()
          setStage('error')
          setError({
            stage: asErrorStage(snap.stage),
            message: snap.error || 'The job failed.',
          })
        }
        // else: still queued/running — a transient drop. Say nothing, change
        // nothing, and let EventSource reconnect.
      } catch (err) {
        if (unmounted || sawTerminalEvent) return
        // A 404 is the one error worth reporting: the backend answered and does not
        // have this job (reset DB, stale id), so no amount of retrying will help and
        // the card would otherwise sit on "Queued" forever with no explanation.
        if (err instanceof ApiError && err.status === 404) {
          es.close()
          setStreamLost('This job no longer exists on the server.')
          return
        }
        // Anything else is transient — a dead backend mid-`uvicorn --reload`, or a
        // restart that outlasts this attempt. Crucially we got NO answer, so this is
        // NOT the outage's one allowed check: clear the latch so the next `onerror`
        // (EventSource keeps retrying) asks again once the backend is back. Without
        // this, a restart that lands/errors the job while the stream is down freezes
        // the card on its last stage forever — the first check fails during downtime,
        // latches, and the terminal job then replays an empty buffer and closes with
        // no event to clear the latch, so the recovery snapshot never fires (T-020,
        // observed in a browser: a hard restart mid-job left the card stuck at
        // "Identifying" while the server said `error`).
        outageChecked = false
      }
    }

    es.onerror = () => {
      // Fires on every failed retry. `outageChecked` makes this one snapshot per
      // outage, not one per retry (ADR-005): it's set true up-front (before the await,
      // so concurrent onerrors can't launch parallel checks) and cleared by the next
      // delivered event OR by a check that got no answer (checkOnce's transient catch).
      // A check that DID get an answer stays latched — a still-running job shouldn't be
      // re-polled until an event moves it. EventSource owns the reconnecting; this only
      // asks the question the stream can't: did the job finish while we were away?
      if (unmounted || sawTerminalEvent || outageChecked) return
      outageChecked = true
      void checkOnce()
    }

    // Closing here is what makes React 19 StrictMode's dev double-mount harmless:
    // the first EventSource is closed before the second opens.
    return () => {
      unmounted = true
      es.close()
    }
  }, [jobId, episode])

  // An error the server attributed to a stage positions the rail there. An error
  // it couldn't attribute falls back to the furthest step we actually watched
  // complete — NOT to `STAGE_STEP.error` (-1), which repainted every dot as
  // pending and told the owner nothing had happened when four stages had.
  const activeStep =
    stage === 'error'
      ? error?.stage
        ? ERROR_STEP[error.stage]
        : reachedStep
      : STAGE_STEP[stage]
  const tags = landed?.tags
  // Derived, not stored: the landed tags win when they actually name something,
  // otherwise the match `track.tagging` already showed stands. An empty
  // `tags: {}` therefore can't erase a good match.
  const displayMatch = asMatch(tags) ?? tagged

  return (
    <article className="track-card" data-stage={stage}>
      <div className="track-card__head">
        <span className="track-card__status" role="status">
          {STAGE_LABEL[stage]}
        </span>
        <span className="track-card__job" title={`Job ${jobId}`}>
          {jobId}
        </span>
      </div>
      <p className="track-card__url" title={url}>
        {url}
      </p>

      {listKind && (
        <p className="track-card__playlist-note" role="note">
          {listKind === 'album'
            ? 'This link was part of an album — only the named song was taken. Downloading whole albums is coming later.'
            : 'This link was part of a playlist — only the named song was taken. Downloading whole playlists is coming later.'}
        </p>
      )}

      <ol className="track-card__rail" aria-hidden="true">
        {RAIL.map((step, i) => (
          <li
            key={step.key}
            className="track-card__step"
            data-state={stepState(i, activeStep, stage)}
          >
            <span className="track-card__dot" />
            <span className="track-card__step-label">{step.label}</span>
          </li>
        ))}
      </ol>

      {displayMatch && (
        <div className="track-card__match">
          <p className="track-card__match-title">
            {displayMatch.title || 'Unknown title'}
          </p>
          <p className="track-card__match-meta">
            {[displayMatch.artist, displayMatch.album, displayMatch.year]
              .filter(Boolean)
              .join(' · ') || 'No artist or album match'}
          </p>
        </div>
      )}

      {stage === 'review_required' &&
        (review ? (
          <ReviewPanel
            // Key by review identity AND epoch: a re-park (T-017 finding 4, or a T-029
            // resume that failed and re-parked the SAME id) must remount the panel
            // rather than reuse an instance whose `submitting` latched true on the pick
            // that just failed — otherwise the re-shown panel has dead buttons.
            key={`${review.reviewId}:${reviewEpoch}`}
            reviewId={review.reviewId}
            rec={review.rec}
            query={review.query}
            candidates={review.candidates}
            message={review.message}
            // Re-subscribe for the resume episode. The panel stays mounted (and its
            // buttons disabled) until this moves the stage off `review_required`.
            onResolved={() => setEpisode((e) => e + 1)}
          />
        ) : (
          <p className="track-card__note">Weak match — parked for your review.</p>
        ))}

      {stage === 'done' && (
        <>
          {landed?.path && (
            <p className="track-card__path" title={landed.path}>
              {landed.path}
            </p>
          )}
          {tags && (
            <ul className="track-card__tags">
              {tags.genre && <li>{tags.genre}</li>}
              {tags.has_art && <li>Art</li>}
              {tags.has_lyrics && <li>Lyrics</li>}
            </ul>
          )}
        </>
      )}

      {stage === 'error' && error && (
        <p className="track-card__error" role="alert">
          <strong>
            {error.stage ? `${ERROR_STAGE_LABEL[error.stage]} failed` : 'Failed'}
          </strong>{' '}
          — {error.message}
        </p>
      )}

      {streamLost && stage !== 'error' && (
        <p className="track-card__detached" role="status">
          {streamLost}
        </p>
      )}
    </article>
  )
}

/** A rail step's state, given the stage's active step. */
function stepState(
  i: number,
  activeStep: number,
  stage: Stage,
): 'complete' | 'active' | 'failed' | 'review' | 'pending' {
  if (i < activeStep) return 'complete'
  if (i > activeStep) return 'pending'
  if (stage === 'error') return 'failed'
  if (stage === 'review_required') return 'review'
  return 'active'
}

// --- payload narrowing -------------------------------------------------------
// The stream is JSON off the wire; nothing about its shape is guaranteed by the
// type system. Every display field can legitimately be null (the server's
// `_id_only_candidates` fallback nulls a whole candidate row), so these narrow
// rather than cast.

function asString(v: unknown): string | null {
  return typeof v === 'string' ? v : null
}

/**
 * The `track.review_required.candidates[]` rows off the wire → typed candidates.
 *
 * Every field can legitimately be null: the id-only fallback (`jobs._id_only_
 * candidates`, emitted when the seam raised at park) nulls title/artist, and a
 * pre-T-028 park has a null score. A non-array (or a non-object row) narrows to
 * empty rather than throwing — a malformed frame must not blank the panel.
 */
function asCandidates(v: unknown): ReviewCandidate[] {
  if (!Array.isArray(v)) return []
  return v.map((row) => {
    const o = row && typeof row === 'object' ? (row as Record<string, unknown>) : {}
    return {
      candidate_id: asString(o.candidate_id),
      title: asString(o.title),
      artist: asString(o.artist),
      score: typeof o.score === 'number' ? o.score : null,
    }
  })
}

/**
 * The four display fields — or **null when it names nothing**.
 *
 * The all-null case is reachable, not defensive: `Outcome.tags`/`chosen` are
 * `dict | None` server-side and `jobs.py` emits `landed.tags or {}`, so
 * `track.done` can legitimately carry `tags: {}`. Returning a truthy object of
 * nulls would let the terminal event paint "Unknown title" over a match already
 * shown from `track.tagging` — the card would end a perfect match reading as a
 * failed one. "Nothing known" is null, and the caller falls back.
 */
function asMatch(v: unknown): Match | null {
  if (!v || typeof v !== 'object') return null
  const o = v as Record<string, unknown>
  const match: Match = {
    title: asString(o.title),
    artist: asString(o.artist),
    album: asString(o.album),
    year: typeof o.year === 'number' ? o.year : null,
  }
  return match.title || match.artist || match.album || match.year ? match : null
}

function asDoneTags(v: unknown): DoneTags | null {
  if (!v || typeof v !== 'object') return null
  const o = v as Record<string, unknown>
  // Built from `o` directly rather than bailing on a null `asMatch`: the tag
  // fields are independent, and a track with genre/art but no title still has
  // something worth showing.
  return {
    ...(asMatch(v) ?? { title: null, artist: null, album: null, year: null }),
    genre: asString(o.genre),
    has_art: o.has_art === true,
    has_lyrics: o.has_lyrics === true,
  }
}

function asErrorStage(v: unknown): ErrorStage | null {
  // `hasOwn`, never `in`: `in` walks the prototype chain, so `'toString' in
  // ERROR_STAGE_LABEL` is true and a stray `stage: "toString"` would pass this
  // guard and render Object.prototype.toString as a React child — garbage on the
  // one path whose whole job is to name the failing stage.
  return typeof v === 'string' && Object.hasOwn(ERROR_STAGE_LABEL, v)
    ? (v as ErrorStage)
    : null
}
