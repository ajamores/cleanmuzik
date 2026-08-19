import { useEffect, useRef, useState } from 'react'
import {
  ApiError,
  getPlaylistState,
  type BatchState,
  type ReviewRow,
} from '../api'
import { CoverSwatch } from './CoverSwatch'
import { ReviewPanel } from './ReviewPanel'
import './BatchCard.css'

/**
 * The one aggregate card for a whole playlist batch (T-310, R2).
 *
 * A 50-song paste is watched through ONE card, not fifty — a browser caps ~6 SSE
 * connections per origin, so fifty cards would leave 44 streams dead (that limit is
 * correctness, not taste; it's why the batch stream exists — T-305). The card reads two
 * sources and keeps them in their lanes:
 *
 *   - the **durable tally + terminal state** (`landed / in-review / gone / skipped /
 *     queued` + the derived `state`) from `batch.progress` on the stream, seeded on cold
 *     load from `GET /api/playlists/{id}` (T-312) — so it is correct after a reload or a
 *     backend restart, when the replay buffer is empty;
 *   - the **per-track rows** accumulated live off the stream's stamped `track.*` events
 *     (each carries its member's `job_id` + `position`). These are live-only by design
 *     (ADR-027 seam 5 reserves no durable per-track read), so after a true restart the
 *     tally still shows the counts but the individual landed/gone rows are absent — the
 *     card stays whole, it just can't redraw detail it never persisted.
 *
 * The **"needs you"** bucket is the exception: parked tracks are durable (the reviews
 * table), so they come from the review inbox — the SAME rows, the SAME resolve seam
 * (ReviewPanel), scoped to this batch and hoisted to the top. "Batching doesn't invent a
 * second place to look" (design gate, screen 04).
 *
 * The warmth discipline the gate proved: failures read "gone / unavailable" in muted
 * ink, never error-red; album art rides landed rows ONLY (a parked/gone/queued row would
 * be asserting a cover that doesn't exist yet); parked > 0 ⇒ "waiting on you", never
 * "done"; and total 0 ⇒ "never started", never a green empty batch (screen 07).
 */

type Stage =
  | 'queued'
  | 'downloading'
  | 'transcoding'
  | 'identifying'
  | 'tagging'
  | 'done'
  | 'error'
  | 'review_required'
  | 'skipped'

/** The stage each stamped event puts a member's row in. `ping`/`batch.*` are absent —
 *  they don't move a track row. `job.queued` maps to `queued` (a member just opened). */
const EVENT_STAGE: Record<string, Stage | undefined> = {
  'job.queued': 'queued',
  'track.downloading': 'downloading',
  'track.transcoding': 'transcoding',
  'track.identifying': 'identifying',
  'track.tagging': 'tagging',
  'track.review_required': 'review_required',
  'track.done': 'done',
  'track.error': 'error',
  'track.skipped': 'skipped',
}

/** The five processing steps a live track walks (spec §4) — reused for the live strip's
 *  segmented meter, mirroring the single-song card's rail. */
const RAIL: { key: string; label: string }[] = [
  { key: 'download', label: 'Download' },
  { key: 'transcode', label: 'Transcode' },
  { key: 'identify', label: 'Identify' },
  { key: 'tag', label: 'Tag' },
  { key: 'land', label: 'Land' },
]

/** Which rail step a live stage lights. `queued` is pre-rail (-1); `tagging` is the tag
 *  step; `done` completes the rail. Only the processing stages appear here — a row that
 *  reaches a terminal leaves the live strip entirely. */
const STAGE_STEP: Record<string, number> = {
  queued: -1,
  downloading: 0,
  transcoding: 1,
  identifying: 2,
  tagging: 3,
  done: RAIL.length,
}

const STAGE_LABEL: Record<string, string> = {
  queued: 'Queued',
  downloading: 'Downloading',
  transcoding: 'Transcoding',
  identifying: 'Identifying',
  tagging: 'Tagging',
}

interface Match {
  title: string | null
  artist: string | null
  album: string | null
  year: number | null
  genre: string | null
  hasArt: boolean
}

/** One member's accumulated row. Outcome is derived from the latest stage; the display
 *  fields ride the terminal `track.*` event, exactly as the single-song card recovers
 *  them. A parked member's row is tracked only to clear the live strip — its visible row
 *  is rendered from the review inbox, not here. */
interface TrackRow {
  jobId: string
  position: number | null
  stage: Stage
  match: Match | null
  path: string | null
  errorMessage: string | null
}

interface Tally {
  landed: number
  in_review: number
  failed: number
  skipped: number
  queued: number
  total: number
  state: BatchState
}

interface BatchCardProps {
  playlistId: string
  /** This batch's parked reviews, already filtered to `playlist_id === playlistId` by
   *  App. Rendered as the "needs you" bucket with the shared ReviewPanel resolve seam. */
  reviews: ReviewRow[]
  /** Fired when a review in this card resolves — App refreshes the queue and re-subscribes
   *  the member (the same seam the top-level inbox uses). */
  onReviewResolved: (jobId: string) => void
  /** Fired when the live stream reports a fresh park, so App re-reads `GET /api/reviews`
   *  and this card's `reviews` prop fills in — the batch mirror of TrackCard's nudge. */
  onReviewParked: () => void
}

/** How many landed rows to show before collapsing the rest to a "+N more" line — the
 *  design's "so the journal isn't a wall" (screen 05). */
const LANDED_VISIBLE = 6

export function BatchCard({
  playlistId,
  reviews,
  onReviewResolved,
  onReviewParked,
}: BatchCardProps) {
  const [title, setTitle] = useState<string | null>(null)
  const [tally, setTally] = useState<Tally | null>(null)
  const [rows, setRows] = useState<Record<string, TrackRow>>({})
  const [liveJobId, setLiveJobId] = useState<string | null>(null)
  const [expandedReview, setExpandedReview] = useState<string | null>(null)
  const [coldError, setColdError] = useState<string | null>(null)
  // Whether to open the live stream, decided by the cold-load snapshot — NOT opened until
  // it resolves. A settled batch (done / never_started) has a closed server channel and an
  // empty replay buffer, so opening it would EOF-then-reconnect forever; the snapshot is
  // its whole truth, so we `skip`. Only a still-live batch (running / waiting_on_you) —
  // and a batch whose snapshot merely blipped — opens. This gate is what makes the
  // reconnect decision synchronous with the stream effect (the earlier ref-flag raced the
  // async snapshot: a settled channel's EOF could fire before the flag was set).
  const [streamMode, setStreamMode] = useState<'pending' | 'open' | 'skip'>('pending')

  // Cold-load seed: the durable snapshot (T-312) gives the tally, terminal state, and
  // title before (or instead of) any live event — so a reload or a post-restart open
  // renders the card whole immediately, and decides whether the stream opens at all.
  useEffect(() => {
    let cancelled = false
    getPlaylistState(playlistId)
      .then((snap) => {
        if (cancelled) return
        setTitle((t) => t ?? snap.title)
        setTally((prev) => prev ?? snapToTally(snap))
        setStreamMode(
          snap.state === 'done' || snap.state === 'never_started' ? 'skip' : 'open',
        )
      })
      .catch((err) => {
        if (cancelled) return
        // A 404 means the batch is gone from the server (reset DB, stale id) — nothing to
        // stream. Any other error is a transient blip: open the stream anyway, since a
        // live batch's events can seed the tally the snapshot failed to.
        if (err instanceof ApiError && err.status === 404) {
          setColdError('This batch no longer exists on the server.')
          setStreamMode('skip')
        } else {
          setStreamMode('open')
        }
      })
    return () => {
      cancelled = true
    }
  }, [playlistId])

  // Held in a ref so a re-render of App (which re-creates `onReviewParked`) never tears
  // down and rebuilds the live EventSource below — the stream effect depends only on the
  // playlist id, exactly like the single-song card keeps its parked-callback in a ref.
  const onReviewParkedRef = useRef(onReviewParked)
  useEffect(() => {
    onReviewParkedRef.current = onReviewParked
  }, [onReviewParked])

  // The live stream (T-305): one connection carrying `batch.queued` / `batch.progress`
  // plus every member's stamped `track.*`. Opened once per batch, and ONLY once the
  // cold-load has decided the batch is still live (`streamMode === 'open'`) — a settled
  // batch is never opened, which is what prevents the reconnect-loop the server's EOF
  // would otherwise spin. It replays its buffer on connect, so handlers arrive in a burst
  // and each must be an idempotent assignment (never a transition off the previous stage)
  // — the same discipline the single-song card learned. A batch that settles DURING an
  // open session closes itself on the terminal `batch.progress` (below).
  useEffect(() => {
    if (streamMode !== 'open') return
    const es = new EventSource(`/api/playlists/${playlistId}/events`)
    let closedTerminal = false

    es.addEventListener('batch.queued', wrap((data) => {
      const t = asString(data.title)
      if (t) setTitle(t)
    }))

    es.addEventListener('batch.progress', wrap((data) => {
      const next = asTally(data)
      if (next) {
        setTally(next)
        // Settled with nothing more coming — close so the EOF doesn't spin EventSource's
        // auto-retry. `waiting_on_you` stays OPEN: a parked member's later resolve still
        // emits its tail here.
        if (next.state === 'done' || next.state === 'never_started') {
          closedTerminal = true
          es.close()
        }
      }
    }))

    // Every stamped member event updates that member's row, keyed by its `job_id`.
    for (const name of Object.keys(EVENT_STAGE)) {
      es.addEventListener(name, wrap((data) => applyTrackEvent(name, data)))
    }
    es.addEventListener('ping', () => {}) // keepalive — inert, registered for completeness

    function applyTrackEvent(name: string, data: Record<string, unknown>) {
      const jobId = asString(data.job_id)
      if (!jobId) return
      const stage = EVENT_STAGE[name]
      if (!stage) return
      const position = typeof data.position === 'number' ? data.position : null

      setRows((prev) => {
        const existing = prev[jobId]
        const row: TrackRow = existing
          ? { ...existing }
          : { jobId, position, stage, match: null, path: null, errorMessage: null }
        row.position = position ?? row.position
        row.stage = stage
        if (name === 'track.tagging') row.match = mergeMatch(row.match, data.chosen)
        if (name === 'track.done') {
          row.match = mergeMatch(row.match, data.tags)
          row.path = asString(data.path)
        }
        if (name === 'track.error') {
          row.errorMessage = asString(data.message)
          row.path = asString(data.path) ?? row.path
        }
        return { ...prev, [jobId]: row }
      })

      // The live strip tracks the single in-flight member (sequential, ADR-001). A
      // processing stage claims it; a terminal stage that belongs to the current live
      // member clears it.
      if (stage === 'downloading' || stage === 'transcoding' || stage === 'identifying' || stage === 'tagging') {
        setLiveJobId(jobId)
      } else if (stage === 'done' || stage === 'error' || stage === 'skipped' || stage === 'review_required') {
        setLiveJobId((cur) => (cur === jobId ? null : cur))
        if (name === 'track.review_required') onReviewParkedRef.current()
      }
    }

    // A helper that parses the JSON frame once and swallows a malformed one — the event
    // name alone still carries the stage, which must not be lost to a bad payload.
    function wrap(handler: (data: Record<string, unknown>) => void) {
      return (e: MessageEvent<string>) => {
        let data: Record<string, unknown> = {}
        try {
          const parsed: unknown = JSON.parse(e.data)
          if (parsed && typeof parsed === 'object') data = parsed as Record<string, unknown>
        } catch {
          /* keep the empty object; named handlers guard every field */
        }
        setColdError(null) // the stream is delivering — any prior outage is over
        handler(data)
      }
    }

    es.onerror = () => {
      // The stream dropped. We only opened for a live batch, so a drop here is a transient
      // outage: EventSource reconnects on its own and the server replays its buffer, making
      // recovery lossless (the single-song card's hard-won posture — no give-up policy). A
      // batch that settles mid-session already closed itself on the terminal `batch.progress`
      // above, so there is no settled channel to poll-loop on. No per-error snapshot poll:
      // the tally is durable, unlike a single job whose finish the stream can't report.
    }

    return () => {
      if (!closedTerminal) es.close()
    }
  }, [playlistId, streamMode])

  if (coldError && !tally) {
    return (
      <article className="batch batch--lost">
        <p className="batch__lost" role="status">
          {coldError}
        </p>
      </article>
    )
  }

  // Bucket the accumulated rows by outcome. Needs-you comes from `reviews` (durable), not
  // from here — a member's own 'review_required' row is suppressed to avoid a double.
  const allRows = Object.values(rows)
  const landedRows = allRows
    .filter((r) => r.stage === 'done')
    .sort(byPosition)
  const goneRows = allRows.filter((r) => r.stage === 'error').sort(byPosition)
  // Skipped tracks render as the collapsed "already in your library" summary, not rows —
  // so only the durable tally count is needed, no per-row accumulation.
  const liveRow = liveJobId ? rows[liveJobId] : null

  const sortedReviews = [...reviews].sort(
    (a, b) => (a.position ?? 0) - (b.position ?? 0),
  )

  const state = tally?.state ?? 'running'
  // A re-paste is a settled batch that skipped some existing videos and added the rest —
  // it reads in the "already here · added · nothing wrong" voice (screen 06) rather than
  // the fresh-grind "N of M processed".
  const isRepaste = state === 'done' && (tally?.skipped ?? 0) > 0

  return (
    <article className="batch" aria-label={title ?? 'Batch'}>
      <header className="batch__top">
        <div className="batch__id">
          <h3 className="batch__title">{title ?? 'Playlist'}</h3>
          <p className="batch__src">
            {tally ? `${tally.total} tracks` : '…'}
            {state === 'waiting_on_you' || state === 'never_started'
              ? ' · restored from durable state'
              : ''}
          </p>
        </div>
        <StatusPill state={state} />
      </header>

      <BatchMeter tally={tally} state={state} isRepaste={isRepaste} />

      {tally && <BatchTally tally={tally} isRepaste={isRepaste} />}

      {/* Live strip — the one track processing right now. Absent once the grind settles. */}
      {liveRow && (state === 'running') && (
        <LiveStrip row={liveRow} total={tally?.total ?? 0} />
      )}

      {/* Screen 07: an empty batch that never got off the ground — a quiet "never started",
          no green, no alarm, pointing at the safe re-paste. */}
      {state === 'never_started' ? (
        <div className="batch__bucket">
          <div className="ready">
            <p className="ready__t">Nothing got queued.</p>
            <p className="ready__s">
              The paste was cut short before any tracks joined. Paste the playlist again — it
              picks up where it left off, nothing doubled.
            </p>
          </div>
        </div>
      ) : (
        <>
          {/* Needs you — hoisted to the top (durable, from the review inbox). */}
          {sortedReviews.length > 0 && (
            <div className="batch__bucket batch__bucket--needs">
              <div className="bucket__head">
                <h4 className="bucket__name">Needs you</h4>
                <span className="bucket__n">{sortedReviews.length}</span>
              </div>
              <div className="rows">
                {sortedReviews.map((row) => {
                  const expanded = expandedReview === row.review_id
                  return (
                    <div key={row.review_id} className="row row--needs" data-expanded={expanded}>
                      <div className="noart">
                        <span>filling</span>
                      </div>
                      <div className="row__body">
                        <div className="row__t" title={row.query}>
                          {row.query || 'Untitled download'}
                        </div>
                        <div className="row__m">
                          {row.position ? `track ${row.position} · ` : ''}
                          {row.rec === 'duplicate' ? 'already in your library' : 'weak match — resolve to file it'}
                        </div>
                        {expanded && (
                          <div className="row__panel">
                            <ReviewPanel
                              key={row.review_id}
                              reviewId={row.review_id}
                              rec={row.rec}
                              query={row.query}
                              candidates={row.candidates}
                              guess={row.guess}
                              reason={row.reason}
                              contradictions={row.contradictions}
                              message={row.last_error}
                              onResolved={() => {
                                setExpandedReview(null)
                                onReviewResolved(row.job_id)
                              }}
                            />
                          </div>
                        )}
                      </div>
                      <button
                        type="button"
                        className="resolve"
                        aria-expanded={expanded}
                        onClick={() =>
                          setExpandedReview((cur) => (cur === row.review_id ? null : row.review_id))
                        }
                      >
                        {expanded ? 'Close' : 'Resolve'}
                      </button>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* Landed / Added. Rows are live-only; the count comes from the durable tally, so
              after a restart the header count is right even when no rows redrew. */}
          {(tally?.landed ?? 0) > 0 && (
            <div className="batch__bucket">
              <div className="bucket__head">
                <h4 className="bucket__name">{isRepaste ? 'Added this time' : 'Landed'}</h4>
                <span className="bucket__n">{tally?.landed}</span>
              </div>
              {landedRows.length > 0 ? (
                <div className="rows">
                  {landedRows.slice(0, LANDED_VISIBLE).map((r) => (
                    <LandedRow key={r.jobId} row={r} added={isRepaste} />
                  ))}
                  {(tally?.landed ?? 0) > LANDED_VISIBLE && (
                    <div className="already">
                      <span className="already__n">
                        +{(tally?.landed ?? 0) - Math.min(LANDED_VISIBLE, landedRows.length)}
                      </span>
                      <span className="already__t">
                        more {isRepaste ? 'added' : 'landed'} — filed in your library.
                      </span>
                    </div>
                  )}
                </div>
              ) : (
                // Cold load / post-restart: no live rows, but the tally is durable.
                <div className="already">
                  <span className="already__n">{tally?.landed}</span>
                  <span className="already__t">
                    {isRepaste ? 'added' : 'landed'} and filed in your library.
                  </span>
                </div>
              )}
            </div>
          )}

          {/* Gone — muted "gone / unavailable", never error-red. */}
          {(tally?.failed ?? 0) > 0 && (
            <div className="batch__bucket">
              <div className="bucket__head">
                <h4 className="bucket__name">Gone</h4>
                <span className="bucket__n">{tally?.failed}</span>
              </div>
              {goneRows.length > 0 ? (
                <div className="rows">
                  {goneRows.map((r) => (
                    <div key={r.jobId} className="row row--gone">
                      <div className="noart">
                        <span>—</span>
                      </div>
                      <div className="row__body">
                        <div className="row__t">
                          {r.position ? `track ${r.position} — ` : ''}unavailable
                        </div>
                        <div className="row__m">
                          {r.errorMessage || 'deleted or region-locked · the batch carried on'}
                        </div>
                      </div>
                      <span className="row__state row__state--gone">Gone</span>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="already">
                  <span className="already__n">{tally?.failed}</span>
                  <span className="already__t">gone or unavailable · the batch carried on.</span>
                </div>
              )}
            </div>
          )}

          {/* Already in your library — the quiet re-paste collapse. */}
          {(tally?.skipped ?? 0) > 0 && (
            <div className="batch__bucket">
              <div className="bucket__head">
                <h4 className="bucket__name">Already in your library</h4>
                <span className="bucket__n">{tally?.skipped}</span>
              </div>
              <div className="already">
                <span className="already__n">{tally?.skipped}</span>
                <span className="already__t">
                  <b>Skipped, not re-downloaded</b> — exact same videos you already own, each added
                  to this playlist. No duplicate files, no re-prompts.
                </span>
              </div>
            </div>
          )}
        </>
      )}
    </article>
  )
}

function byPosition(a: TrackRow, b: TrackRow): number {
  return (a.position ?? 0) - (b.position ?? 0)
}

function StatusPill({ state }: { state: BatchState }) {
  const map: Record<BatchState, { cls: string; label: string }> = {
    running: { cls: 'pill--live', label: 'Processing' },
    waiting_on_you: { cls: 'pill--wait', label: 'Waiting on you' },
    done: { cls: 'pill--done', label: 'Done' },
    never_started: { cls: 'pill--never', label: 'Never started' },
  }
  const { cls, label } = map[state]
  return <span className={`pill ${cls}`}>{label}</span>
}

function BatchMeter({
  tally,
  state,
  isRepaste,
}: {
  tally: Tally | null
  state: BatchState
  isRepaste: boolean
}) {
  const total = tally?.total ?? 0
  const processed = tally ? total - tally.queued : 0
  const pct = total > 0 ? Math.round((processed / total) * 100) : 0
  const fillCls =
    state === 'done'
      ? 'agg__fill agg__fill--done'
      : state === 'waiting_on_you'
        ? 'agg__fill agg__fill--wait'
        : 'agg__fill'

  let count: string
  let right: React.ReactNode
  if (state === 'never_started') {
    count = '0 of 0 — nothing was queued'
    right = <span className="agg__pct">—</span>
  } else if (state === 'waiting_on_you') {
    count = `${total} of ${total} processed · ${tally?.in_review} waiting on you`
    right = <span className="agg__pct agg__pct--wait">Parked</span>
  } else if (isRepaste) {
    count = `${tally?.skipped} already here · ${tally?.landed} added · nothing wrong`
    right = <span className="agg__pct agg__pct--done">100%</span>
  } else {
    count = `${processed} of ${total} processed`
    right = (
      <span className={`agg__pct${state === 'done' ? ' agg__pct--done' : ''}`}>{pct}%</span>
    )
  }

  return (
    <div className="agg">
      <div className="agg__bar">
        {state !== 'never_started' && (
          <div className={fillCls} style={{ width: `${state === 'done' ? 100 : pct}%` }} />
        )}
      </div>
      <div className="agg__meta">
        <span className="agg__count">{count}</span>
        {right}
      </div>
    </div>
  )
}

function BatchTally({ tally, isRepaste }: { tally: Tally; isRepaste: boolean }) {
  const cells: { key: string; n: number; k: string; cls: string }[] = [
    { key: 'landed', n: tally.landed, k: isRepaste ? 'Added' : 'Landed', cls: 'tally__cell--landed' },
    { key: 'review', n: tally.in_review, k: 'In review', cls: 'tally__cell--review' },
    { key: 'failed', n: tally.failed, k: 'Gone', cls: 'tally__cell--failed' },
    { key: 'skipped', n: tally.skipped, k: 'Skipped', cls: 'tally__cell--skipped' },
    { key: 'queued', n: tally.queued, k: 'Queued', cls: '' },
  ]
  return (
    <div className="tally">
      {cells.map((c) => (
        <div
          key={c.key}
          className={`tally__cell ${c.cls}${c.n === 0 ? ' tally__cell--zero' : ''}`}
        >
          <span className="tally__n">{c.n}</span>
          <span className="tally__k">{c.k}</span>
        </div>
      ))}
    </div>
  )
}

function LiveStrip({ row, total }: { row: TrackRow; total: number }) {
  const step = STAGE_STEP[row.stage] ?? -1
  const label =
    row.match?.title && row.match?.artist
      ? `${row.match.title} — ${row.match.artist}`
      : STAGE_LABEL[row.stage] ?? 'Processing'
  return (
    <div className="live">
      <p className="live__lab">
        <span className="live__dot" />
        Now processing{row.position ? ` · track ${row.position} of ${total}` : ''}
      </p>
      <div className="live__now">{label}</div>
      <div className="live__sub">{STAGE_LABEL[row.stage] ?? '…'}</div>
      <div className="meter" aria-hidden="true">
        {RAIL.map((s, i) => (
          <span key={s.key} className="seg" data-s={segState(i, step)} />
        ))}
      </div>
      <div className="mlabels" aria-hidden="true">
        {RAIL.map((s, i) => (
          <span key={s.key} data-s={segState(i, step)}>
            {s.label}
          </span>
        ))}
      </div>
    </div>
  )
}

function LandedRow({ row, added }: { row: TrackRow; added: boolean }) {
  const m = row.match
  const seed = [m?.artist, m?.title].filter(Boolean).join(' ') || row.jobId
  return (
    <div className="row">
      {m?.hasArt ? (
        <CoverSwatch seed={seed} className="cover" size={44} />
      ) : (
        // Art on landed rows ONLY, and only when the track actually carries it — a landed
        // track with no embedded art gets no placeholder either (ADR-010/018 discipline).
        <div className="noart">
          <span>♪</span>
        </div>
      )}
      <div className="row__body">
        <div className="row__t">
          {m?.title || 'Landed track'}
          {m?.artist ? ` — ${m.artist}` : ''}
        </div>
        <div className="row__m" title={row.path ?? undefined}>
          {[m?.album, m?.year, m?.genre].filter(Boolean).join(' · ') || row.path || ''}
        </div>
      </div>
      <span className="row__state row__state--ok">{added ? 'Added' : 'Landed'}</span>
    </div>
  )
}

function segState(i: number, step: number): 'complete' | 'active' | 'pending' {
  if (i < step) return 'complete'
  if (i === step) return 'active'
  return 'pending'
}

// --- payload narrowing (same posture as TrackCard: the wire is untyped JSON) ---------

function asString(v: unknown): string | null {
  return typeof v === 'string' ? v : null
}

/** Merge a `track.tagging.chosen` / `track.done.tags` object into the row's match,
 *  keeping any field the new event doesn't name — a `track.done` with `tags: {}` must not
 *  erase the good match `track.tagging` already showed. */
function mergeMatch(prev: Match | null, v: unknown): Match | null {
  if (!v || typeof v !== 'object') return prev
  const o = v as Record<string, unknown>
  const next: Match = {
    title: asString(o.title) ?? prev?.title ?? null,
    artist: asString(o.artist) ?? prev?.artist ?? null,
    album: asString(o.album) ?? prev?.album ?? null,
    year: typeof o.year === 'number' ? o.year : (prev?.year ?? null),
    genre: asString(o.genre) ?? prev?.genre ?? null,
    hasArt: o.has_art === true || prev?.hasArt === true,
  }
  return next
}

function asTally(data: Record<string, unknown>): Tally | null {
  const state = data.state
  if (typeof state !== 'string') return null
  const n = (k: string) => (typeof data[k] === 'number' ? (data[k] as number) : 0)
  return {
    landed: n('landed'),
    in_review: n('in_review'),
    failed: n('failed'),
    skipped: n('skipped'),
    queued: n('queued'),
    total: n('total'),
    state: state as BatchState,
  }
}

function snapToTally(snap: {
  landed: number
  in_review: number
  failed: number
  skipped: number
  queued: number
  total: number
  state: BatchState
}): Tally {
  return {
    landed: snap.landed,
    in_review: snap.in_review,
    failed: snap.failed,
    skipped: snap.skipped,
    queued: snap.queued,
    total: snap.total,
    state: snap.state,
  }
}
