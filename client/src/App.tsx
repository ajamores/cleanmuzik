import { useCallback, useEffect, useState } from 'react'
import { createJob, getJob, listReviews, type ReviewRow } from './api'
import { TrackCard } from './components/TrackCard'
import { ReviewInbox } from './components/ReviewInbox'
import './App.css'

interface Job {
  jobId: string
  url: string
}

function App() {
  const [url, setUrl] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [jobs, setJobs] = useState<Job[]>([])
  const [reviews, setReviews] = useState<ReviewRow[]>([])
  // T-102: when the inbox resolves a review, the corresponding TrackCard (if present)
  // must re-subscribe to its SSE stream so it picks up the resume events (track.tagging →
  // track.done). Each card watches its own epoch; a bump opens a fresh EventSource.
  const [resolveEpochs, setResolveEpochs] = useState<Record<string, number>>({})

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

  // T-102: the inbox owns the resolve lifecycle. On resolve, refresh the queue (the row
  // leaves it at once — `claim_review` flips it to `resolving`, which `GET /api/reviews`
  // excludes) and signal the card to re-subscribe. With no live card, watch the job for
  // a later re-park the way the card's SSE stream otherwise would.
  const handleInboxResolved = useCallback(
    (jobId: string) => {
      refreshInbox()
      setResolveEpochs((prev) => ({ ...prev, [jobId]: (prev[jobId] ?? 0) + 1 }))
      const hasLiveCard = jobs.some((j) => j.jobId === jobId)
      if (!hasLiveCard) {
        watchColdResolve(jobId)
      }
    },
    [refreshInbox, jobs, watchColdResolve],
  )

  const trimmed = url.trim()
  const canSubmit = trimmed.length > 0 && !submitting

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!canSubmit) return

    setSubmitting(true)
    setError(null)
    try {
      const { job_id } = await createJob(trimmed)
      setJobs((prev) => [{ jobId: job_id, url: trimmed }, ...prev])
      setUrl('')
    } catch (err) {
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
        onReviewResolved={handleInboxResolved}
      />

      <section className="app__jobs" aria-label="Tracks">
        {jobs.length === 0 ? (
          <p className="app__empty">No tracks yet.</p>
        ) : (
          jobs.map((job) => (
            <div key={job.jobId}>
              <TrackCard
                jobId={job.jobId}
                url={job.url}
                onReviewParked={refreshInbox}
                resolveEpoch={resolveEpochs[job.jobId] ?? 0}
              />
            </div>
          ))
        )}
      </section>
    </main>
  )
}

export default App
