import { useState } from 'react'
import { ApiError, createJob } from './api'
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
      setError(
        err instanceof ApiError || err instanceof Error
          ? err.message
          : 'Something went wrong.',
      )
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
          type="url"
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
            <TrackCard key={job.jobId} jobId={job.jobId} url={job.url} />
          ))
        )}
      </section>
    </main>
  )
}

export default App
