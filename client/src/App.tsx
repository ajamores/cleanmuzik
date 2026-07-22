import { useState } from 'react'
import { createJob } from './api'
import { TrackCard } from './components/TrackCard'
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
            <TrackCard key={job.jobId} jobId={job.jobId} url={job.url} />
          ))
        )}
      </section>
    </main>
  )
}

export default App
