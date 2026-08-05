import { useCallback, useState } from 'react'
import type { ReviewRow } from '../api'
import { ReviewPanel } from './ReviewPanel'
import './ReviewInbox.css'

interface ReviewInboxProps {
  /** The whole parked queue, from `GET /api/reviews` on mount and re-fetched on every
   *  park/resolve signal. Rendered independent of any live TrackCard — this is what makes
   *  a review parked in a previous session reachable on a cold load (spec §7). */
  reviews: ReviewRow[]
  /** Fired after a review resolves from this inbox, so App can refresh the queue and
   *  signal the card (if any) to resume its SSE subscription. */
  onReviewResolved: (jobId: string) => void
}

/**
 * The Needs-review inbox — the durable, top-level surface for the parked queue.
 *
 * T-102: the review lifecycle moves here from TrackCard. Each row expands in-place to
 * show the full ReviewPanel (weak-match candidates, duplicate comparison, re-search,
 * keep-untagged). A cold-loaded review is fully resolvable from this surface with no
 * live card present.
 */
export function ReviewInbox({ reviews, onReviewResolved }: ReviewInboxProps) {
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const toggle = useCallback((reviewId: string) => {
    setExpandedId((prev) => (prev === reviewId ? null : reviewId))
  }, [])

  return (
    <section className="review-inbox" aria-label="Needs review">
      <div className="review-inbox__label-row">
        <h2 className="review-inbox__title">Needs review</h2>
        {reviews.length > 0 && (
          <span className="review-inbox__count">{reviews.length}</span>
        )}
      </div>

      {reviews.length === 0 ? (
        <p className="review-inbox__empty">Nothing waiting for review.</p>
      ) : (
        <ul className="review-inbox__list">
          {reviews.map((row) => {
            const duplicate = row.rec === 'duplicate'
            const expanded = expandedId === row.review_id
            return (
              <li
                key={row.review_id}
                className="review-inbox__row signal-glow"
                data-kind={duplicate ? 'duplicate' : 'weak'}
                data-expanded={expanded}
              >
                <div className="review-inbox__head">
                  <span className="review-inbox__disc" aria-hidden="true" />
                  <div className="review-inbox__body">
                    <p className="review-inbox__query" title={row.query}>
                      {row.query || 'Untitled download'}
                    </p>
                    <p className="review-inbox__sub">
                      {duplicate
                        ? 'Already in your library'
                        : row.guess?.artist || 'No confident match'}
                    </p>
                  </div>
                  <span
                    className="review-inbox__tag"
                    data-kind={duplicate ? 'duplicate' : 'weak'}
                  >
                    {duplicate ? 'Duplicate' : 'Weak match'}
                  </span>
                  <button
                    type="button"
                    className={`review-inbox__action${expanded ? ' review-inbox__action--active' : ''}`}
                    onClick={() => toggle(row.review_id)}
                    aria-expanded={expanded}
                  >
                    {expanded ? 'Close' : 'Review'}
                  </button>
                </div>

                {expanded && (
                  <div className="review-inbox__panel">
                    <ReviewPanel
                      key={row.review_id}
                      reviewId={row.review_id}
                      rec={row.rec}
                      query={row.query}
                      candidates={row.candidates}
                      guess={row.guess}
                      message={row.last_error}
                      onResolved={() => {
                        setExpandedId(null)
                        onReviewResolved(row.job_id)
                      }}
                    />
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
