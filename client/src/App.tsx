import { useCallback, useEffect, useMemo, useState } from 'react'
import { createJob, listReviews, type ReviewRow } from './api'
import { TrackCard } from './components/TrackCard'
import { ReviewInbox } from './components/ReviewInbox'
import './App.css'

interface Job {
  jobId: string
  url: string
}

/** The DOM id of a job's card wrapper — the scroll target when a Review row jumps to
 *  the card that hosts the panel. */
const cardDomId = (jobId: string) => `job-card-${jobId}`

function App() {
  const [url, setUrl] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [jobs, setJobs] = useState<Job[]>([])
  // The parked review queue, rendered by the Needs-review inbox. Its single source of
  // truth is the server (`GET /api/reviews`): fetched once on mount — which is what makes
  // a review parked in a PREVIOUS session reachable on a cold load, independent of any
  // live card — and re-fetched on every park/resolve signal a card sends up.
  const [reviews, setReviews] = useState<ReviewRow[]>([])

  // Reconcile the whole inbox from the server. Reused for the cold-load fetch AND every
  // live signal, so the inbox has exactly one way to build its state (no drift): the
  // card→App seam is a plain "something changed, re-read" nudge, not a per-row patch.
  // A refetch is cheap and robust here — single user, tiny queue — and it self-heals the
  // re-park churn (T-029) a hand-maintained array would have to special-case. Failures
  // are swallowed: a transient blip leaves the last good queue on screen rather than
  // blanking it, and the next signal (or reload) refreshes it.
  const refreshInbox = useCallback(() => {
    listReviews()
      .then(setReviews)
      .catch(() => {})
  }, [])

  // Cold load: populate the inbox once, before and independent of any job/card.
  useEffect(() => {
    refreshInbox()
  }, [refreshInbox])

  // Which reviews can be jumped to: a review whose job has a live card this session.
  const liveJobIds = useMemo(
    () => new Set(jobs.map((job) => job.jobId)),
    [jobs],
  )

  function handleReview(row: ReviewRow) {
    // Only live rows reach here (the inbox disables the rest). Scroll to the card that
    // hosts the ReviewPanel; the panel itself still lives in the card in R1.1 (lifting it
    // out so a cold-loaded review resolves in place is T-102). Optional call: jsdom has no
    // scrollIntoView, and a real browser may lack smooth behaviour.
    document
      .getElementById(cardDomId(row.job_id))
      ?.scrollIntoView?.({ behavior: 'smooth', block: 'start' })
  }

  const trimmed = url.trim()
  const canSubmit = trimmed.length > 0 && !submitting

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!canSubmit) return

    setSubmitting(true)
    setError(null)
    try {
      const { job_id } = await createJob(trimmed)
      // Newest card first.
      setJobs((prev) => [{ jobId: job_id, url: trimmed }, ...prev])
      setUrl('')
    } catch (err) {
      // createJob throws ApiError (a subclass of Error) for every failure path,
      // so one Error check covers them all; the else is pure defensiveness.
      setError(err instanceof Error ? err.message : 'Something went wrong.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="app">
      <header className="app__header">
        <h1>CleanMuzik</h1>
        <p>Paste one YouTube song URL and it lands, tagged, in your library.</p>
      </header>

      <form className="url-form" onSubmit={handleSubmit}>
        <input
          className="url-form__input"
          // Deliberately NOT type="url": native HTML5 URL validation silently
          // blocks form submission for a schemeless paste ("www.youtube.com/…"),
          // so Go looks dead. The backend is the real gate (it hands the URL to
          // yt-dlp and reports a stage error on a bad one). inputMode keeps the
          // URL keyboard on mobile.
          type="text"
          inputMode="url"
          placeholder="https://www.youtube.com/watch?v=…"
          value={url}
          onChange={(e) => {
            setUrl(e.target.value)
            if (error) setError(null)
          }}
          aria-label="YouTube song URL"
          aria-invalid={error ? true : undefined}
          disabled={submitting}
        />
        <button className="url-form__go" type="submit" disabled={!canSubmit}>
          {submitting ? 'Working…' : 'Go'}
        </button>
      </form>

      {error && (
        <p className="app__error" role="alert">
          {error}
        </p>
      )}

      <ReviewInbox
        reviews={reviews}
        liveJobIds={liveJobIds}
        onReview={handleReview}
      />

      <section className="app__jobs" aria-label="Tracks">
        {jobs.length === 0 ? (
          <p className="app__empty">No tracks yet.</p>
        ) : (
          jobs.map((job) => (
            // key IS load-bearing, not just React hygiene: TrackCard's stream effect
            // re-subscribes on a jobId change but does NOT reset the card's own state
            // (stage, landed, error, rail high-water), so a reused instance would show
            // the previous job's progress under a new id. Keying by jobId guarantees a
            // fresh mount per job, which is that reset. jobId is immutable per job, so
            // this never remounts a live card. (T-020, carried from a T-016 review.)
            // The id is the scroll target for the inbox's Review action.
            <div key={job.jobId} id={cardDomId(job.jobId)}>
              <TrackCard
                jobId={job.jobId}
                url={job.url}
                // The card→App seam: the card owns the SSE stream where
                // `track.review_required` lives (there is no app-wide EventSource), so it
                // nudges App to re-read the queue when its stream parks a review and when
                // one resolves. Both are the same "re-read" signal.
                onReviewParked={refreshInbox}
                onReviewResolved={refreshInbox}
              />
            </div>
          ))
        )}
      </section>
    </main>
  )
}

export default App
