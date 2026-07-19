import { useEffect, useState } from 'react'
import {
  ApiError,
  getReview,
  resolveReview,
  type DuplicateDetail,
  type ResolveBody,
  type ReviewCandidate,
} from '../api'
import './ReviewPanel.css'

interface ReviewPanelProps {
  reviewId: string
  /** The row's recommendation: `"duplicate"` → the keep-which branch, anything
   *  else → a weak/ambiguous match. Carried on the SSE event (T-017) so this panel
   *  renders the right question without a round-trip. */
  rec: string | null
  /** The normalized title the pipeline searched on — shown so the owner can see
   *  what was looked up, which is often why the match is weak. */
  query: string
  /** Weak-match candidates, straight off the `track.review_required` event. Empty
   *  for a duplicate (its detail is fetched) or a candidate-less park. */
  candidates: ReviewCandidate[]
  /** Called after a resolve is accepted by the server. The card re-subscribes on
   *  this; the panel then unmounts as the job leaves `review_required`. */
  onResolved: () => void
}

/**
 * The review queue's decision surface (T-017, spec §6, ADR-009/010).
 *
 * Two questions share it, keyed by `rec`:
 *  - **weak match** — "which of these is it?" — renders `candidates` inline.
 *  - **duplicate** — "you already have this; keep which copy?" — fetches the
 *    existing-vs-incoming detail (a library read the SSE event can't carry).
 *
 * Built for fast look-over-and-decide (ADR-009): reject is as reachable as accept
 * (it is often the right call — the candidates are all weak by construction), the
 * whole thing is keyboard-resolvable, and nothing reloads between items.
 */
export function ReviewPanel({
  reviewId,
  rec,
  query,
  candidates,
  onResolved,
}: ReviewPanelProps) {
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  /** Resolve, and on success hand off to the card's re-subscribe. Stays
   *  `submitting` on success — the panel unmounts when the job advances, so there
   *  is no re-enable to race, and the buttons can't be double-fired in the gap. */
  async function submit(body: ResolveBody) {
    setSubmitting(true)
    setError(null)
    try {
      await resolveReview(reviewId, body)
      onResolved()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not resolve the review.')
      setSubmitting(false)
    }
  }

  return (
    <section className="review" aria-label="Review this track">
      {rec === 'duplicate' ? (
        <DuplicatePanel
          reviewId={reviewId}
          submitting={submitting}
          onSubmit={submit}
        />
      ) : (
        <WeakMatchPanel
          query={query}
          candidates={candidates}
          submitting={submitting}
          onSubmit={submit}
        />
      )}

      {error && (
        <p className="review__error" role="alert">
          {error}
        </p>
      )}
    </section>
  )
}

// --- weak match --------------------------------------------------------------

interface WeakMatchProps {
  query: string
  candidates: ReviewCandidate[]
  submitting: boolean
  onSubmit: (body: ResolveBody) => void
}

/**
 * "Which of these is it?" — a candidate is picked and accepted, or the song is
 * rejected. Accept and reject carry equal weight on purpose: the field is five
 * weak, similar scores by construction (a strong match would have auto-tagged),
 * so "none of these" is a first-class answer, not an exception.
 */
function WeakMatchPanel({ query, candidates, submitting, onSubmit }: WeakMatchProps) {
  // Default to the top candidate, but only among those that can actually be
  // accepted: an id-only fallback row (seam raised at park) has a null candidate_id
  // and can't be resolved, so it must not be the default selection. Lazy initializer
  // — the scan runs once, not on every render.
  const [choice, setChoice] = useState<string | null>(
    () => candidates.find((c) => c.candidate_id)?.candidate_id ?? null,
  )

  function accept(e: React.FormEvent) {
    e.preventDefault()
    if (submitting || !choice) return
    onSubmit({ choice })
  }

  return (
    <form className="review__weak" onSubmit={accept}>
      <p className="review__query">
        {query ? (
          <>
            Searched <span className="review__query-term">{query}</span> — no
            confident match. Pick the right one, or reject.
          </>
        ) : (
          'No title could be read from the file — pick the right match below, or reject.'
        )}
      </p>

      {candidates.length === 0 ? (
        <p className="review__empty">
          No candidates were found for this song. Reject it to discard the download.
        </p>
      ) : (
        <ul className="review__candidates" role="radiogroup" aria-label="Candidate matches">
          {candidates.map((c, i) => (
            <CandidateRow
              key={c.candidate_id ?? `id-only-${i}`}
              candidate={c}
              // Guard the null match: a candidate with no id must never read as
              // selected just because `choice` is also null (nothing usable to pick).
              checked={c.candidate_id !== null && c.candidate_id === choice}
              disabled={submitting}
              onSelect={() => c.candidate_id && setChoice(c.candidate_id)}
            />
          ))}
        </ul>
      )}

      <div className="review__actions">
        <button
          type="submit"
          className="review__btn review__btn--accept"
          disabled={submitting || !choice}
        >
          {submitting ? 'Resolving…' : 'Accept selected'}
        </button>
        <button
          type="button"
          className="review__btn review__btn--reject"
          disabled={submitting}
          onClick={() => onSubmit({ choice: 'reject' })}
        >
          Reject
        </button>
      </div>
    </form>
  )
}

interface CandidateRowProps {
  candidate: ReviewCandidate
  checked: boolean
  disabled: boolean
  onSelect: () => void
}

function CandidateRow({ candidate, checked, disabled, onSelect }: CandidateRowProps) {
  const usable = candidate.candidate_id !== null
  return (
    <li className="review__candidate" data-usable={usable}>
      <label className="review__candidate-label">
        <input
          type="radio"
          name="candidate"
          className="review__radio"
          checked={checked}
          disabled={disabled || !usable}
          onChange={onSelect}
        />
        <span className="review__candidate-text">
          <span className="review__candidate-title">
            {candidate.title || 'Unknown title'}
          </span>
          <span className="review__candidate-artist">
            {candidate.artist || 'Unknown artist'}
          </span>
        </span>
        <ScoreBar score={candidate.score} />
      </label>
    </li>
  )
}

/**
 * Match strength as a bar, never a raw float. The real scores sit in a narrow band
 * (~0.34–0.46 on the one measured park) a few thousandths apart, so `0.4598`
 * printed next to `0.4415` asserts a difference the number can't support. A bar on
 * an absolute 0–1 scale tells the honest story — a row of short, similar bars reads
 * as "all weak, take your pick", which is the truth. No "best match" label.
 */
function ScoreBar({ score }: { score: number | null }) {
  if (score === null) {
    return <span className="review__score review__score--unknown">no score</span>
  }
  const pct = Math.round(Math.min(1, Math.max(0, score)) * 100)
  return (
    <span
      className="review__score"
      role="meter"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={pct}
      aria-label={`Match strength ${pct}%`}
    >
      <span className="review__score-track">
        <span className="review__score-fill" style={{ width: `${pct}%` }} />
      </span>
    </span>
  )
}

// --- duplicate ---------------------------------------------------------------

interface DuplicateProps {
  reviewId: string
  submitting: boolean
  onSubmit: (body: ResolveBody) => void
}

/**
 * "You already have this — keep which copy?" The existing-vs-incoming detail isn't
 * on the SSE event (it needs a beets library read), so this fetches the row's detail
 * on mount. It uses the NARROW `GET /api/reviews/{id}` — reading one row, not
 * re-hydrating the whole queue (T-017 review, finding 5). A transient failure is
 * retryable rather than terminal (finding 3).
 */
function DuplicatePanel({ reviewId, submitting, onSubmit }: DuplicateProps) {
  const [detail, setDetail] = useState<DuplicateDetail | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  // Bumped by the retry button: a `--reload` blip must not leave a duplicate
  // permanently unresolvable, the way TrackCard's one-shot reconcile doesn't.
  const [attempt, setAttempt] = useState(0)
  const [suffix, setSuffix] = useState('(alternate)')

  useEffect(() => {
    let cancelled = false
    getReview(reviewId)
      .then((row) => {
        if (cancelled) return
        if (row.duplicate) setDetail(row.duplicate)
        else setLoadError('This duplicate review has no detail to show.')
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setLoadError(
          err instanceof ApiError && err.status === 404
            ? 'This review is no longer in the queue.'
            : err instanceof Error
              ? err.message
              : 'Could not load the duplicate detail.',
        )
      })
    return () => {
      cancelled = true
    }
  }, [reviewId, attempt])

  if (loadError) {
    return (
      <div className="review__load-error">
        <p className="review__error" role="alert">
          {loadError}
        </p>
        <button
          type="button"
          className="review__btn"
          // Clear the error and re-run the load effect. State is reset here, in the
          // handler, not in the effect body — a synchronous reset inside the effect
          // is the set-state-in-effect anti-pattern.
          onClick={() => {
            setLoadError(null)
            setDetail(null)
            setAttempt((a) => a + 1)
          }}
        >
          Try again
        </button>
      </div>
    )
  }
  if (!detail) {
    return (
      <p className="review__loading" role="status">
        Loading the copy you already have…
      </p>
    )
  }

  const incomingGone = !detail.incoming.exists

  return (
    <div className="review__dup">
      <p className="review__query">
        You already have this song. Keep which copy?
      </p>

      <div className="review__dup-compare">
        <div className="review__dup-side">
          <span className="review__dup-heading">In your library</span>
          {detail.existing.length === 0 ? (
            <p className="review__dup-meta">No matching library copy found.</p>
          ) : (
            detail.existing.map((e, i) => (
              <div key={e.path ?? i} className="review__dup-copy">
                <span className="review__dup-title">{e.title || 'Unknown title'}</span>
                <span className="review__dup-meta">
                  {[e.artist, e.album].filter(Boolean).join(' · ') || 'No artist or album'}
                </span>
                <span className="review__dup-bitrate">{formatBitrate(e.bitrate)}</span>
              </div>
            ))
          )}
        </div>

        <div className="review__dup-side">
          <span className="review__dup-heading">Just downloaded</span>
          {incomingGone ? (
            <p className="review__dup-meta review__dup-gone">
              The downloaded copy is no longer on disk.
            </p>
          ) : (
            <div className="review__dup-copy">
              <span className="review__dup-title">
                {detail.incoming.title || 'Unknown title'}
              </span>
              <span className="review__dup-meta">
                {detail.incoming.artist || 'Unknown artist'}
              </span>
              <span className="review__dup-bitrate">
                {formatBitrate(detail.incoming.bitrate)}
              </span>
            </div>
          )}
        </div>
      </div>

      {incomingGone && (
        <p className="review__note">
          Only “keep existing” is available — the download would need to be fetched
          again to keep or replace with it.
        </p>
      )}

      <div className="review__actions">
        <button
          type="button"
          className="review__btn review__btn--accept"
          disabled={submitting}
          onClick={() => onSubmit({ choice: 'keep_existing' })}
        >
          {submitting ? 'Resolving…' : 'Keep existing'}
        </button>
        <button
          type="button"
          className="review__btn"
          disabled={submitting || incomingGone}
          onClick={() => onSubmit({ choice: 'replace' })}
        >
          Replace with download
        </button>
      </div>

      <div className="review__keep-both">
        <label className="review__suffix-label">
          Keep both — label the new copy
          <input
            type="text"
            className="review__suffix-input"
            value={suffix}
            maxLength={60}
            disabled={submitting || incomingGone}
            onChange={(e) => setSuffix(e.target.value)}
          />
        </label>
        <button
          type="button"
          className="review__btn"
          disabled={submitting || incomingGone || !suffix.trim()}
          onClick={() => onSubmit({ choice: 'keep_both', suffix: suffix.trim() })}
        >
          Keep both
        </button>
      </div>
    </div>
  )
}

/** beets/mediafile bitrate is bits per second; show it as the kbps the owner reads
 *  off a file. `0` means we couldn't read it — say so rather than print "0 kbps". */
function formatBitrate(bitrate: number): string {
  return bitrate > 0 ? `${Math.round(bitrate / 1000)} kbps` : 'bitrate unknown'
}
