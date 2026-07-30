import { useEffect, useRef, useState } from 'react'
import {
  ApiError,
  getReview,
  resolveReview,
  searchReview,
  type DuplicateDetail,
  type ResolveBody,
  type ReviewCandidate,
  type ReviewGuess,
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
  /** What the machine searched with, to pre-fill the re-search form (T-103, ADR-020).
   *  Absent/null just means an empty form. */
  guess?: ReviewGuess | null
  /** Called after a resolve is accepted by the server. The card re-subscribes on
   *  this; the panel then unmounts as the job leaves `review_required`. */
  onResolved: () => void
  /** Set only when the previous resolve attempt failed and re-parked this review
   *  (T-029). Shown so the owner learns why the pick didn't apply rather than being
   *  silently handed the panel again. Absent on a first park. */
  message?: string | null
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
  guess,
  onResolved,
  message,
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
      {message && (
        <p className="review__reparked" role="alert">
          {message}
        </p>
      )}
      {rec === 'duplicate' ? (
        <DuplicatePanel
          reviewId={reviewId}
          submitting={submitting}
          onSubmit={submit}
        />
      ) : (
        <WeakMatchPanel
          reviewId={reviewId}
          query={query}
          candidates={candidates}
          guess={guess}
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
  reviewId: string
  query: string
  candidates: ReviewCandidate[]
  guess?: ReviewGuess | null
  submitting: boolean
  onSubmit: (body: ResolveBody) => void
}

/** The last re-search, or null when the list is still the park's own guesses. `artist`
 *  and `title` are the server's TRIMMED echo — the exact strings that went to
 *  MusicBrainz — so the header reports what was asked, not what was typed. */
interface Searched {
  artist: string
  title: string
  rows: ReviewCandidate[]
}

/**
 * "Which of these is it?" — a candidate is picked and accepted, the search is
 * corrected, or the song is rejected. Accept and reject carry equal weight on purpose:
 * the field is five weak, similar scores by construction (a strong match would have
 * auto-tagged), so "none of these" is a first-class answer, not an exception.
 *
 * **Re-search is the third answer (T-103, ADR-020 exit 1)**, and the one that fixes the
 * dead-end: when every candidate is wrong — or there are none — picking from the list
 * cannot help, because the *question* was wrong. The form re-queries MusicBrainz with
 * the owner's own words and replaces the list with what comes back.
 */
function WeakMatchPanel({
  reviewId,
  query,
  candidates,
  guess,
  submitting,
  onSubmit,
}: WeakMatchProps) {
  const [searched, setSearched] = useState<Searched | null>(null)
  const shown = searched?.rows ?? candidates

  // Default to the top candidate, but only among those that can actually be
  // accepted: an id-only fallback row (seam raised at park) has a null candidate_id
  // and can't be resolved, so it must not be the default selection. Lazy initializer
  // — the scan runs once, not on every render.
  const [choice, setChoice] = useState<string | null>(
    () => candidates.find((c) => c.candidate_id)?.candidate_id ?? null,
  )

  // **The owner's correction lives HERE, not in the form**, so collapsing the form is
  // presentation rather than data loss. It was in the form until a review caught the
  // consequence: after a successful search the form closes, and re-opening it remounted
  // the component, re-seeding both fields from `guess` — silently discarding what the
  // owner typed. That is not an edge case, it is the mainline: ADR-020's amendment
  // measured that MusicBrainz almost never returns nothing, so the real dead-end is
  // "many results, all wrong" and the SECOND search is the ordinary next move.
  const [artist, setArtist] = useState(guess?.artist ?? '')
  const [title, setTitle] = useState(guess?.title ?? query)

  // Derived, not tracked: the form is open when there is nothing to pick from, or when
  // the owner asked for it. Expressing the rule once here keeps it from being re-stated
  // at each transition — the version that tracked it had to re-assert "stay open if the
  // result was empty" inside the success handler, which is where a bug would hide.
  const [opened, setOpened] = useState(false)
  const searchOpen = shown.length === 0 || opened

  function accept(e: React.FormEvent) {
    e.preventDefault()
    if (submitting || !choice) return
    onSubmit({ choice })
  }

  /** Adopt a search's results and preselect its best row, so Accept is one click. */
  function adopt(result: Searched) {
    setSearched(result)
    setChoice(result.rows.find((c) => c.candidate_id)?.candidate_id ?? null)
    // Collapse the form on success; `searchOpen` keeps it open by itself when the
    // result was empty, because then there is still nothing to pick from.
    setOpened(false)
  }

  return (
    <form className="review__weak" onSubmit={accept}>
      <p className="review__query">
        {searched ? (
          <>
            Searched again for{' '}
            <span className="review__query-term">
              {[searched.artist, searched.title].filter(Boolean).join(' — ')}
            </span>
            {searched.rows.length === 0 ? ' — no results.' : '.'}
          </>
        ) : query ? (
          <>
            Searched <span className="review__query-term">{query}</span> — no
            confident match. Pick the right one, correct the search, or reject.
          </>
        ) : (
          'No title could be read from the file — correct the search below, or reject.'
        )}
      </p>

      {shown.length === 0 ? (
        <p className="review__empty">
          {searched
            ? // The honest reading, and the reason it is not an error: the owner just
              // asked MusicBrainz directly, in their own words. A miss means the
              // recording genuinely isn't in the database — normal for bootlegs,
              // mixtape rips and YouTube-only mixes.
              'MusicBrainz has no record of that. Try different terms, or reject the download.'
            : 'No candidates were found for this song. Correct the search, or reject it to discard the download.'}
        </p>
      ) : (
        <ul
          className="review__candidates"
          role="radiogroup"
          aria-label={searched ? 'New results' : 'Candidate matches'}
        >
          {shown.map((c, i) => (
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

      {searchOpen ? (
        <ReSearchForm
          reviewId={reviewId}
          artist={artist}
          title={title}
          onArtist={setArtist}
          onTitle={setTitle}
          disabled={submitting}
          onResults={adopt}
        />
      ) : (
        <button
          type="button"
          className="review__btn review__btn--ghost review__none-of-these"
          disabled={submitting}
          onClick={() => setOpened(true)}
        >
          None of these? Search again
        </button>
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

interface ReSearchFormProps {
  reviewId: string
  /** Controlled by `WeakMatchPanel` so the correction outlives this component — see the
   *  comment on its `artist`/`title` state for what went wrong when it didn't. */
  artist: string
  title: string
  onArtist: (v: string) => void
  onTitle: (v: string) => void
  disabled: boolean
  onResults: (result: Searched) => void
}

/**
 * "None of these? Search again" — the correction, pre-filled with the machine's guess.
 *
 * **The pre-fill is the teaching moment, not a convenience** (ADR-020). Seeing that the
 * artist field holds the uploader's channel name, or that the title holds both fields
 * in one string, is what makes the mistake obvious — and on the real fixtures those are
 * exactly the shapes it takes. Nothing here tries to repair the guess: a heuristic
 * split would be a guess about a guess, and one of the two live fixtures arrives
 * already correct.
 *
 * Purely presentational as to the terms — it renders and edits what the parent holds,
 * and owns only the in-flight state (`searching` / `error`) that dies with the request.
 *
 * Not a nested `<form>` (invalid HTML, and it would submit the accept form): the
 * re-search button is a plain button whose handler does the fetch, and Enter inside a
 * field is bound to it explicitly so the keyboard path still works.
 */
function ReSearchForm({
  reviewId,
  artist,
  title,
  onArtist,
  onTitle,
  disabled,
  onResults,
}: ReSearchFormProps) {
  const [searching, setSearching] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // A search can outlive this component — the job may progress and unmount the whole
  // panel while it is still in flight. Without this the response lands on a dead tree
  // and React warns; with the pre-fix 27-second round-trip it was near-certain rather
  // than theoretical. Kept even though the search is now ~1s: the window is smaller,
  // not gone.
  const live = useRef(true)
  useEffect(() => {
    live.current = true
    return () => {
      live.current = false
    }
  }, [])

  const empty = !artist.trim() && !title.trim()

  async function run() {
    if (disabled || searching || empty) return
    setSearching(true)
    setError(null)
    try {
      const result = await searchReview(reviewId, { artist, title })
      if (!live.current) return
      onResults({ artist: result.artist, title: result.title, rows: result.candidates })
    } catch (err) {
      if (!live.current) return
      setError(
        err instanceof Error ? err.message : 'Could not search MusicBrainz.',
      )
    } finally {
      // Unlike a resolve, a search leaves the panel mounted whatever happens — it
      // changes nothing server-side — so the button must always come back.
      if (live.current) setSearching(false)
    }
  }

  /** These inputs sit inside the accept `<form>`, so a bare Enter would submit THAT —
   *  landing whatever candidate is selected instead of running the search the owner
   *  just typed. Bind Enter to the search explicitly. */
  function onEnter(e: React.KeyboardEvent) {
    if (e.key !== 'Enter') return
    e.preventDefault()
    void run()
  }

  return (
    <div className="review__research">
      <p className="review__research-head">
        Correct the search — this is what was looked up
      </p>
      <div className="review__research-fields">
        <label className="review__field">
          Artist
          <input
            type="text"
            className="review__input review__input--inset"
            value={artist}
            disabled={disabled || searching}
            onChange={(e) => onArtist(e.target.value)}
            onKeyDown={onEnter}
          />
        </label>
        <label className="review__field">
          Title
          <input
            type="text"
            className="review__input review__input--inset"
            value={title}
            disabled={disabled || searching}
            onChange={(e) => onTitle(e.target.value)}
            onKeyDown={onEnter}
          />
        </label>
      </div>

      <div className="review__research-actions">
        <button
          type="button"
          className="review__btn review__btn--ghost"
          disabled={disabled || searching}
          // The commonest single correction: yt-dlp splits "Artist - Title" the wrong
          // way round often enough that swapping is worth one click.
          onClick={() => {
            onArtist(title)
            onTitle(artist)
          }}
        >
          Swap
        </button>
        <button
          type="button"
          className="review__btn review__btn--accept"
          disabled={disabled || searching || empty}
          onClick={() => void run()}
        >
          {searching ? 'Searching…' : 'Re-search'}
        </button>
      </div>

      {error && (
        <p className="review__error" role="alert">
          {error}
        </p>
      )}
    </div>
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
        <label className="review__field">
          Keep both — label the new copy
          <input
            type="text"
            className="review__input"
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
