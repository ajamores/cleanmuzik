import { useCallback, useEffect, useMemo, useState } from 'react'
import { createJob, getJob, isBatchResponse, listReviews, type ReviewRow } from './api'
import { TrackCard } from './components/TrackCard'
import { BatchCard } from './components/BatchCard'
import { AcquireDial, type DialMode } from './components/AcquireDial'
import { ReviewInbox } from './components/ReviewInbox'
import { CrestLogo } from './components/CrestLogo'
import { AmbientLine } from './components/AmbientLine'
import { useSignalGlow } from './useSignalGlow'
import './App.css'

/** One thing on the deck: a single-song job (the R1 card) or an expanded batch (T-310).
 *  A union, not two lists, so the deck stays in one newest-first timeline. */
type DeckItem =
  | { kind: 'single'; jobId: string; url: string }
  | { kind: 'batch'; playlistId: string }

function App() {
  const [url, setUrl] = useState('')
  const [mode, setMode] = useState<DialMode>('single')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [items, setItems] = useState<DeckItem[]>([])
  const [reviews, setReviews] = useState<ReviewRow[]>([])
  // T-102: when the inbox resolves a review, the corresponding TrackCard (if present)
  // must re-subscribe to its SSE stream so it picks up the resume events (track.tagging →
  // track.done). Each card watches its own epoch; a bump opens a fresh EventSource.
  const [resolveEpochs, setResolveEpochs] = useState<Record<string, number>>({})

  useSignalGlow()

  const refreshInbox = useCallback(() => {
    listReviews()
      .then(setReviews)
      .catch(() => {})
  }, [])

  useEffect(() => {
    refreshInbox()
  }, [refreshInbox])

  // T-102 cold-load re-park watch: with no live card there is no SSE to catch a resume
  // that fails and re-parks the review, and the re-park lands only AFTER the worker's
  // async resume (tag/art/transcode/land/scan — routinely >3s, ADR-001). So poll the
  // job snapshot until it settles rather than guess a single delay. `getJob` is the
  // documented "the stream can't answer this" fallback (api.ts); this is the one path
  // with no stream at all. Stops on `review` (re-parked → resurface it) or done/error
  // (settled, nothing to show); bounded so a stuck job can't poll forever.
  const watchColdResolve = useCallback(
    (jobId: string) => {
      const DELAY_MS = 2500
      const MAX_ATTEMPTS = 24 // ~60s ceiling
      let attempts = 0
      const tick = () => {
        getJob(jobId)
          .then((snap) => {
            if (snap.status === 'review') {
              refreshInbox() // the resume re-parked — bring the row back
            } else if (snap.status !== 'done' && snap.status !== 'error') {
              if (++attempts < MAX_ATTEMPTS) setTimeout(tick, DELAY_MS)
            }
          })
          .catch(() => {
            // A transient blip costs one attempt, no more — same posture as refreshInbox.
            if (++attempts < MAX_ATTEMPTS) setTimeout(tick, DELAY_MS)
          })
      }
      setTimeout(tick, DELAY_MS)
    },
    [refreshInbox],
  )

  // T-102: the inbox (top-level OR a batch card's "needs you" bucket) owns the resolve
  // lifecycle. On resolve, refresh the queue (the row leaves it at once — `claim_review`
  // flips it to `resolving`, which `GET /api/reviews` excludes) and signal the card to
  // re-subscribe. With no live single card, watch the job for a later re-park the way the
  // card's SSE stream otherwise would (a batch member has no single card, so it takes
  // this path — its resume tail also rides the batch stream, updating that card live).
  const handleInboxResolved = useCallback(
    (jobId: string) => {
      refreshInbox()
      setResolveEpochs((prev) => ({ ...prev, [jobId]: (prev[jobId] ?? 0) + 1 }))
      const hasLiveCard = items.some((i) => i.kind === 'single' && i.jobId === jobId)
      if (!hasLiveCard) {
        watchColdResolve(jobId)
      }
    },
    [refreshInbox, items, watchColdResolve],
  )

  // Partition the parked queue: a review with no `playlist_id` is a single-song park (the
  // top-level inbox owns it); one with a `playlist_id` belongs to its batch card's "needs
  // you" bucket. Same rows, same resolve seam, one place each — never both (design gate,
  // screen 04: "batching doesn't invent a second place to look").
  const looseReviews = useMemo(
    () => reviews.filter((r) => !r.playlist_id),
    [reviews],
  )
  const reviewsByBatch = useMemo(() => {
    const map: Record<string, ReviewRow[]> = {}
    for (const r of reviews) {
      if (r.playlist_id) (map[r.playlist_id] ??= []).push(r)
    }
    return map
  }, [reviews])

  // The deck to render: the session's items, PLUS a recovered batch card for any batch
  // that has a parked review but no live card. Without this, a page reload (which starts
  // `items` empty) would filter a batch member's park OUT of the top-level inbox — it
  // carries a `playlist_id` — while no batch card exists to show it, stranding the review
  // in neither place, unseen and unresolvable. The recovered card cold-loads its snapshot
  // (T-312) and renders the parked rows from `reviewsByBatch`, so a batch is always
  // reachable as long as it has a parked review to resurface it.
  const deck = useMemo<DeckItem[]>(() => {
    const batchItemIds = new Set(
      items.filter((i) => i.kind === 'batch').map((i) => i.playlistId),
    )
    const recovered: DeckItem[] = Object.keys(reviewsByBatch)
      .filter((id) => !batchItemIds.has(id))
      .map((id) => ({ kind: 'batch', playlistId: id }))
    return [...items, ...recovered]
  }, [items, reviewsByBatch])

  const handleMode = useCallback((m: DialMode) => {
    setMode(m)
    setError(null) // a mode change abandons a prior submit — clear its stale banner (#5)
  }, [])

  const trimmed = url.trim()
  const isMulti = mode === 'multi'
  const canSubmit = trimmed.length > 0 && !submitting && !isMulti

  // A light, advisory URL-shape read for the dial's note line — the backend is the
  // authority on expand-vs-single (ADR-029); this only decides which quiet hint to show.
  const hasList = /[?&]list=/.test(url)
  const hasVideo = /[?&]v=/.test(url) || /youtu\.be\//.test(url)
  const note =
    mode === 'single' && hasList && hasVideo
      ? { t: 'Playlist attached — taking just this song.', s: 'Want the whole list? Turn the dial to Playlist.' }
      : mode === 'playlist' && hasVideo && !hasList
        ? { t: 'A single-song URL.', s: 'Lands as one song — a quiet note, not an error.' }
        : null

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!canSubmit) return

    setSubmitting(true)
    setError(null)
    try {
      // The dial's intent goes on the wire only for the wired stops; `multi` never
      // submits (the form is inert there). An absent intent leaves the backend on its R1
      // shape inference — the single-song walk-away path unchanged.
      const intent = mode === 'playlist' ? 'playlist' : 'single'
      const res = await createJob(trimmed, intent)
      if (isBatchResponse(res)) {
        setItems((prev) => [{ kind: 'batch', playlistId: res.playlist_id }, ...prev])
      } else {
        setItems((prev) => [{ kind: 'single', jobId: res.job_id, url: trimmed }, ...prev])
      }
      setUrl('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <>
      <AmbientLine />
      <div className="shell">
        {/* The console rail: brand, the acquire dial, input strip, and the pipeline
            legend. Sticky at desktop so the paste bar is always at hand. */}
        <aside className="console">
          <header className="console__brand">
            <CrestLogo />
            <h1 className="console__wordmark">CleanMuzik</h1>
            <p className="console__tagline">
              Set the dial, paste a YouTube URL, and it lands, tagged, in your library.
            </p>
          </header>

          <AcquireDial mode={mode} onChange={handleMode} />

          {isMulti ? (
            // Multi is a present-but-inert stop (ADR-029): its geometry is reserved and
            // the roadmap is on screen, but the build is backlog (T-046).
            <div className="console__soon">
              <div className="console__soon-k">Multi · coming soon</div>
              <p className="console__soon-t">
                Queue up a handful of songs by hand into one set — not a playlist, just your own
                pick. The set will assemble here when it lands.
              </p>
            </div>
          ) : (
            <>
              <form className="url-form" onSubmit={handleSubmit}>
                <input
                  className="url-form__input"
                  type="text"
                  inputMode="url"
                  placeholder={
                    mode === 'playlist'
                      ? 'https://www.youtube.com/playlist?list=…'
                      : 'https://www.youtube.com/watch?v=…'
                  }
                  value={url}
                  onChange={(e) => {
                    setUrl(e.target.value)
                    if (error) setError(null)
                  }}
                  aria-label={mode === 'playlist' ? 'YouTube playlist URL' : 'YouTube song URL'}
                  aria-invalid={error ? true : undefined}
                  disabled={submitting}
                />
                <button className="url-form__go" type="submit" disabled={!canSubmit}>
                  {submitting ? 'Working…' : 'Go'}
                </button>
              </form>

              {note && (
                <p className="url-form__note" role="note">
                  <b>{note.t}</b>
                  <br />
                  {note.s}
                </p>
              )}
            </>
          )}

          {error && (
            <p className="app__error" role="alert">
              {error}
            </p>
          )}

          {/* The signal path — the five stages every track passes through. */}
          <div className="console__path" aria-hidden="true">
            {['Download', 'Transcode', 'Identify', 'Tag', 'Land'].map((stage) => (
              <span className="console__path-stage" key={stage}>
                {stage}
              </span>
            ))}
          </div>
        </aside>

        <main className="deck">
          <ReviewInbox reviews={looseReviews} onReviewResolved={handleInboxResolved} />

          <section className="app__jobs" aria-labelledby="app__tracks-label">
            <div className="deck__head">
              <h2 className="deck__title" id="app__tracks-label">
                {deck.some((i) => i.kind === 'batch') ? 'Batches & tracks' : 'Tracks'}
              </h2>
              {deck.length > 0 && <span className="deck__count">{deck.length}</span>}
            </div>
            {deck.length === 0 ? (
              <div className="app__empty">
                <p className="app__empty-line">No tracks yet.</p>
                <p className="app__empty-sub">
                  Paste a URL and the first one opens here, live.
                </p>
              </div>
            ) : (
              deck.map((item) =>
                item.kind === 'single' ? (
                  <div key={`s:${item.jobId}`}>
                    <TrackCard
                      jobId={item.jobId}
                      url={item.url}
                      onReviewParked={refreshInbox}
                      resolveEpoch={resolveEpochs[item.jobId] ?? 0}
                    />
                  </div>
                ) : (
                  <div key={`b:${item.playlistId}`}>
                    <BatchCard
                      playlistId={item.playlistId}
                      reviews={reviewsByBatch[item.playlistId] ?? []}
                      onReviewResolved={handleInboxResolved}
                      onReviewParked={refreshInbox}
                    />
                  </div>
                ),
              )
            )}
          </section>
        </main>
      </div>
    </>
  )
}

export default App
