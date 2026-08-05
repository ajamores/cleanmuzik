import { useEffect, useRef, useState } from 'react'
import { ApiError, getJob } from '../api'
import { CoverSwatch } from './CoverSwatch'
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
 *  positioned by ERROR_STEP from the stage the server named, so the rail shows
 *  where it broke. */
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
 *  was a hand-kept copy of RAIL's indices). `scan` is the post-landing Jellyfin
 *  refresh: it runs AFTER the file has landed, so a scan failure means every rail
 *  step — Land included — actually completed. Mapping it to `RAIL.length` (one past
 *  the end) paints the whole rail complete rather than Land red: the file IS in the
 *  library (the error banner + LandingDetail path say so), only Jellyfin hasn't
 *  refreshed. Mapping scan to Land's index instead made the card contradict itself
 *  once the path render moved onto the error branch (ADR-015). */
const ERROR_STEP: Record<ErrorStage, number> = {
  ...(Object.fromEntries(
    RAIL.map((step, i) => [step.key, i]),
  ) as Record<ErrorStage, number>),
  scan: RAIL.length,
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

/** What the card keeps from a `track.review_required` event (T-102). The inbox owns
 *  the review lifecycle now, so the card holds only `rec` — enough to label its
 *  hand-off note (duplicate vs weak match). Everything else the panel needs lives on
 *  the inbox's own `GET /api/reviews` row. */
interface ReviewInfo {
  rec: string | null
}

interface TrackCardProps {
  jobId: string
  url: string
  /** Card→App seam (T-101): fired when this card's stream parks a review, so App can
   *  re-read `GET /api/reviews` and surface the row in the Needs-review inbox. SSE is
   *  per-card here — this event only exists on the card's own stream — so the inbox
   *  learns of a live park through this nudge, not a global listener. */
  onReviewParked?: () => void
  /** T-102: bumped by App when the inbox resolves a review for this job. The card
   *  re-subscribes to its SSE stream so it picks up the resume events (track.tagging →
   *  track.done). Absent or zero on mount; the card only acts on a CHANGE. */
  resolveEpoch?: number
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
export function TrackCard({
  jobId,
  url,
  onReviewParked,
  resolveEpoch,
}: TrackCardProps) {
  const [stage, setStage] = useState<Stage>('queued')
  const [listKind, setListKind] = useState<'album' | 'playlist' | null>(null)
  const [tagged, setTagged] = useState<Match | null>(null)
  const [landed, setLanded] = useState<Landed | null>(null)
  const [error, setError] = useState<TrackError | null>(null)
  const [streamLost, setStreamLost] = useState<string | null>(null)
  const [reachedStep, setReachedStep] = useState(-1)
  // T-102: the card no longer hosts ReviewPanel — the inbox owns the review lifecycle.
  // `review` is kept only so the hand-off note can name the branch (weak match vs
  // duplicate). It is NOT rendered as a panel.
  const [review, setReview] = useState<ReviewInfo | null>(null)
  // Bumped when the owner resolves a review: it re-runs the effect below, opening a
  // FRESH EventSource for the resume episode. T-102: the bump comes from the
  // `resolveEpoch` prop (the inbox resolved), not from a panel callback.
  const [episode, setEpisode] = useState(0)
  const reachedRef = useRef(-1)
  const onReviewParkedRef = useRef(onReviewParked)
  useEffect(() => {
    onReviewParkedRef.current = onReviewParked
  }, [onReviewParked])

  // T-102: the inbox resolved this job's review — re-subscribe for the resume events.
  const prevResolveEpoch = useRef(resolveEpoch ?? 0)
  useEffect(() => {
    const current = resolveEpoch ?? 0
    if (current > prevResolveEpoch.current) {
      prevResolveEpoch.current = current
      setEpisode((e) => e + 1)
    }
  }, [resolveEpoch])

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
      // T-102: the card no longer hosts ReviewPanel — the inbox owns the review. We
      // capture just `rec`, the one field the hand-off note reads (branch labelling).
      setReview({ rec: asString(data.rec) })
      onReviewParkedRef.current?.()
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
      // A post-landing scan failure carries where the song went on the error event
      // (ADR-015) — set it so the card shows the song is in the library, just not yet
      // refreshed in Jellyfin. A pre-landing error has no path/tags → narrowed to null,
      // and the error render's `landed?.path` guard shows nothing.
      setLanded({ path: asString(data.path), tags: asDoneTags(data.tags) })
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
          // No receipt to recover from the snapshot (ADR-015): the landing path/tags rode the
          // `track.done` event, so the path shows when that event is delivered live. This fallback
          // settles only the status and does NOT wait for the buffered event to replay — so if the
          // event wasn't delivered (a drop that overlapped completion, or a restart's empty buffer)
          // the card shows a bare "Done" with no path. That's fine and deliberate: the file is at a
          // known library path regardless (best-effort path, ADR-015).
        } else if (snap.status === 'review') {
          es.close()
          setStage('review_required')
          // T-102: the card shows a hand-off note, not the panel. The inbox hydrates
          // the review data from GET /api/reviews on its own cold-load fetch.
        } else if (snap.status === 'error') {
          es.close()
          setStage('error')
          setError({
            stage: asErrorStage(snap.stage),
            message: snap.error || 'The job failed.',
          })
          // As with `done`: a post-landing scan failure's path/tags rode the `track.error` event
          // (ADR-015), shown when that event is delivered live. This fallback settles only the
          // status; if the event wasn't delivered the card shows a bare error with no path. The
          // file is still on disk at its library path regardless (best-effort path, ADR-015).
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
        // Anything else is transient and did NOT give a definitive answer about the job:
        // a dead backend mid-`uvicorn --reload` (ApiError status 0), or a proxy answering
        // a briefly-down backend with a 5xx (status 502/504 — an error, not a job status).
        // Neither is the outage's one allowed check, so clear the latch: the next `onerror`
        // (EventSource keeps retrying) asks again once the backend is back. Without this, a
        // restart that lands/errors the job while the stream is down freezes the card on its
        // last stage forever — the first check fails during downtime, latches, and the
        // terminal job then replays an empty buffer and closes with no event to clear the
        // latch, so the recovery snapshot never fires (T-020, observed in a browser: a hard
        // restart mid-job left the card stuck at "Identifying" while the server said `error`).
        // A definitive still-running 2xx answer stays latched via the try-block (it changes
        // nothing), so this only re-checks when the job's fate is genuinely still unknown.
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

  // The result block (T-105): one place for the match, the landing path, the tag
  // chips and — where a landed track carries art — the cover swatch. Shown from
  // `tagging` (match only) through `done` (full) and on a post-landing scan `error`
  // (path/tags ride the event, ADR-015). Never for `review_required` (the handoff note
  // owns that), and null when there is nothing to show (a pre-landing error).
  const landedPath = landed?.path ?? null
  const showChips = Boolean(tags && (tags.genre || tags.has_art || tags.has_lyrics))
  const hasResult = Boolean(displayMatch || landedPath || showChips)
  // Art exists only once a track has landed; the swatch stands in for it (Option 2),
  // seeded off the track's identity so the same song always draws the same cover.
  const landedArt = (stage === 'done' || stage === 'error') && tags?.has_art === true
  const coverSeed =
    [displayMatch?.artist, displayMatch?.title].filter(Boolean).join(' ') || jobId

  const resultNode =
    hasResult && stage !== 'review_required' ? (
      <div className="track-card__result">
        {landedArt && <CoverSwatch seed={coverSeed} className="track-card__cover" />}
        <div className="track-card__result-text">
          {displayMatch && (
            <>
              <p className="track-card__match-title">
                {displayMatch.title || 'Unknown title'}
              </p>
              <p className="track-card__match-meta">
                {[displayMatch.artist, displayMatch.album, displayMatch.year]
                  .filter(Boolean)
                  .join(' / ') || 'No artist or album match'}
              </p>
            </>
          )}
          {landedPath && (
            <p className="track-card__path" title={landedPath}>
              {landedPath}
            </p>
          )}
          {showChips && tags && (
            <ul className="track-card__tags">
              {tags.genre && <li>{tags.genre}</li>}
              {tags.has_art && <li>Art</li>}
              {tags.has_lyrics && <li>Lyrics</li>}
            </ul>
          )}
        </div>
      </div>
    ) : null

  return (
    <article className="track-card signal-glow" data-stage={stage}>
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
            ? 'This link was part of an album; only the named song was taken. Downloading whole albums is coming later.'
            : 'This link was part of a playlist; only the named song was taken. Downloading whole playlists is coming later.'}
        </p>
      )}

      {/* The segmented meter rail (T-105): done segs solid, the current seg pulses,
          the rest unlit; a park holds amber, a failure holds red. The labels beneath
          carry the same state so colour alone reads the stage under reduced motion. */}
      <div className="track-card__meter" aria-hidden="true">
        {RAIL.map((step, i) => (
          <span
            key={step.key}
            className="track-card__seg"
            data-state={stepState(i, activeStep, stage)}
          />
        ))}
      </div>
      <div className="track-card__mlabels" aria-hidden="true">
        {RAIL.map((step, i) => (
          <span
            key={step.key}
            className="track-card__mlabel"
            data-state={stepState(i, activeStep, stage)}
          >
            {step.label}
          </span>
        ))}
      </div>

      {resultNode}

      {stage === 'review_required' && (
        <p className="track-card__handoff">
          <span className="track-card__handoff-arrow">→</span>
          {/* `review` is null on the snapshot-fallback path (the SSE `review_required`
              never arrived); the snapshot carries no `rec`, so drop the branch claim
              rather than assert "Weak match" over what may be a duplicate. */}
          {review?.rec === 'duplicate'
            ? 'Duplicate. Moved to your review inbox.'
            : review
              ? 'Weak match. Moved to your review inbox.'
              : 'Moved to your review inbox.'}
        </p>
      )}

      {stage === 'error' && error && (
        <p className="track-card__error" role="alert">
          <strong>
            {error.stage ? `${ERROR_STAGE_LABEL[error.stage]} failed` : 'Failed'}
          </strong>
          {': '}
          {error.message}
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
