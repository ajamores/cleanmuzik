import type { ReviewRow } from '../api'
import './ReviewInbox.css'

interface ReviewInboxProps {
  /** The whole parked queue, from `GET /api/reviews` on mount and re-fetched on every
   *  park/resolve signal (App owns the state). Rendered independent of any live
   *  TrackCard — this is what makes a review parked in a previous session reachable on a
   *  cold load (spec §7 gap R1 shipped). */
  reviews: ReviewRow[]
  /** Job ids that have a live TrackCard mounted this session. A review whose job is
   *  live can be jumped to (its card hosts the ReviewPanel); a cold-loaded review has
   *  no card, so its Review action is inert here — resolving from cold is T-102. */
  liveJobIds: ReadonlySet<string>
  /** Jump to the card hosting this review's panel. Only called for a live row. */
  onReview: (row: ReviewRow) => void
}

/**
 * The Needs-review inbox — the durable, top-level surface for the parked queue.
 *
 * R1 built the review lifecycle INSIDE TrackCard, an ephemeral card that boots empty
 * on reload, so a parked review was durably stored and served by `GET /api/reviews`
 * yet invisible on a fresh load. This inbox is the keystone fix: one row per parked
 * review, loaded on mount and kept in sync off the cards' park/resolve signals, so the
 * queue is reachable with no live card present.
 */
export function ReviewInbox({ reviews, liveJobIds, onReview }: ReviewInboxProps) {
  return (
    <section className="review-inbox" aria-label="Needs review">
      <h2 className="review-inbox__title">Needs review</h2>

      {reviews.length === 0 ? (
        <p className="review-inbox__empty">Nothing waiting for review.</p>
      ) : (
        <ul className="review-inbox__list">
          {reviews.map((row) => {
            // `rec === "duplicate"` is the keep-which branch; every other rec is a weak
            // match (api.ts ReviewRow). The tag tells the two apart at a glance.
            const duplicate = row.rec === 'duplicate'
            const live = liveJobIds.has(row.job_id)
            return (
              <li key={row.review_id} className="review-inbox__row">
                <div className="review-inbox__body">
                  <p className="review-inbox__query" title={row.query}>
                    {row.query || 'Untitled download'}
                  </p>
                  <span
                    className="review-inbox__tag"
                    data-kind={duplicate ? 'duplicate' : 'weak'}
                  >
                    {duplicate ? 'Duplicate' : 'Weak match'}
                  </span>
                </div>
                <button
                  type="button"
                  className="review-inbox__action"
                  onClick={() => onReview(row)}
                  disabled={!live}
                  title={
                    live
                      ? 'Jump to this review'
                      : "This review's card isn't open in this session"
                  }
                >
                  Review
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
