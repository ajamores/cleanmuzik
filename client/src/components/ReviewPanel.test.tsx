/**
 * ReviewPanel — the two questions the queue asks (T-017, spec §6, ADR-009/010).
 *
 * These pin behaviour a click-through can't see and the DoD's acceptance check
 * demands: the exact resolve body per branch, that reject is a first-class peer of
 * accept, that a raw float is never printed as a verdict, and that the duplicate
 * branch fetches the library detail the SSE event can't carry.
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ReviewPanel } from './ReviewPanel'
import type { ReviewCandidate } from '../api'

beforeEach(() => {
  vi.restoreAllMocks()
})

/**
 * Route fetch by URL + method: GET /api/reviews/{id} → one row (or 404 when no
 * `review` is given), POST resolve → {ok}. `review` may be a function so a test can
 * fail the first call and succeed the retry.
 */
function mockBackend(opts: {
  review?: unknown | (() => Response)
  resolve?: () => Response
  /** `POST /reviews/{id}/search` (T-103). A function so a test can answer differently
   *  on a second call — "search again" has to actually re-query. */
  search?: () => Response
}) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    if (url.includes('/search')) {
      return Promise.resolve(
        opts.search?.() ?? jsonResponse({ artist: '', title: '', candidates: [] }),
      )
    }
    if (url.includes('/resolve')) {
      return Promise.resolve(opts.resolve?.() ?? jsonResponse({ ok: true }))
    }
    if (/\/api\/reviews\/[^/]+$/.test(url) && method === 'GET') {
      if (typeof opts.review === 'function') {
        return Promise.resolve((opts.review as () => Response)())
      }
      if (opts.review === undefined) {
        return Promise.resolve(jsonResponse({ detail: 'gone' }, 404))
      }
      return Promise.resolve(jsonResponse(opts.review))
    }
    throw new Error(`unexpected fetch: ${method} ${url}`)
  })
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

/** The body a resolve POST carried, parsed. */
function resolveBody(fetchMock: ReturnType<typeof vi.spyOn>): unknown {
  const call = fetchMock.mock.calls.find((c: unknown[]) =>
    String(c[0]).includes('/resolve'),
  )
  if (!call) throw new Error('no resolve POST was made')
  return JSON.parse((call[1] as RequestInit).body as string)
}

const CANDIDATES: ReviewCandidate[] = [
  { candidate_id: 'rec-A', title: 'Outro', artist: 'Nines', score: 0.4598 },
  { candidate_id: 'rec-B', title: 'Freestyle', artist: 'Nines', score: 0.4415 },
]

describe('weak match — "which of these is it?"', () => {
  it('renders each candidate title and artist', () => {
    mockBackend({})
    render(
      <ReviewPanel
        reviewId="rev-1"
        rec="low"
        query="nines outro"
        candidates={CANDIDATES}
        onResolved={() => {}}
      />,
    )
    expect(screen.getByText('Outro')).toBeInTheDocument()
    expect(screen.getByText('Freestyle')).toBeInTheDocument()
    expect(screen.getAllByText('Nines')).toHaveLength(2)
  })

  it('shows strength as a meter, never the raw float (ADR-010 honesty)', () => {
    mockBackend({})
    render(
      <ReviewPanel
        reviewId="rev-1"
        rec="low"
        query="nines outro"
        candidates={CANDIDATES}
        onResolved={() => {}}
      />,
    )
    // The precise distance must not be asserted as a verdict.
    expect(screen.queryByText(/0\.45/)).not.toBeInTheDocument()
    const meters = screen.getAllByRole('meter')
    expect(meters[0]).toHaveAttribute('aria-valuenow', '46')
    expect(meters[1]).toHaveAttribute('aria-valuenow', '44')
  })

  it('accepts the top candidate by default', async () => {
    const onResolved = vi.fn()
    const fetchMock = mockBackend({})
    render(
      <ReviewPanel
        reviewId="rev-1"
        rec="low"
        query="q"
        candidates={CANDIDATES}
        onResolved={onResolved}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /accept/i }))
    await waitFor(() => expect(onResolved).toHaveBeenCalledOnce())
    expect(resolveBody(fetchMock)).toEqual({ choice: 'rec-A' })
  })

  it('accepts an alternate once picked', async () => {
    const onResolved = vi.fn()
    const fetchMock = mockBackend({})
    render(
      <ReviewPanel
        reviewId="rev-1"
        rec="low"
        query="q"
        candidates={CANDIDATES}
        onResolved={onResolved}
      />,
    )
    fireEvent.click(screen.getByRole('radio', { name: /freestyle/i }))
    fireEvent.click(screen.getByRole('button', { name: /accept/i }))
    await waitFor(() => expect(onResolved).toHaveBeenCalledOnce())
    expect(resolveBody(fetchMock)).toEqual({ choice: 'rec-B' })
  })

  it('rejects — a first-class peer, always reachable', async () => {
    const onResolved = vi.fn()
    const fetchMock = mockBackend({})
    render(
      <ReviewPanel
        reviewId="rev-1"
        rec="low"
        query="q"
        candidates={CANDIDATES}
        onResolved={onResolved}
      />,
    )
    const reject = screen.getByRole('button', { name: /^reject$/i })
    expect(reject).toBeEnabled()
    fireEvent.click(reject)
    await waitFor(() => expect(onResolved).toHaveBeenCalledOnce())
    expect(resolveBody(fetchMock)).toEqual({ choice: 'reject' })
  })

  it('a candidate-less park can still be rejected, not accepted', () => {
    mockBackend({})
    render(
      <ReviewPanel
        reviewId="rev-1"
        rec="none"
        query="q"
        candidates={[]}
        onResolved={() => {}}
      />,
    )
    expect(screen.getByText(/no candidates/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /accept/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /^reject$/i })).toBeEnabled()
  })

  it('surfaces a resolve failure and re-enables the buttons', async () => {
    mockBackend({ resolve: () => jsonResponse({ detail: 'already resolved' }, 409) })
    render(
      <ReviewPanel
        reviewId="rev-1"
        rec="low"
        query="q"
        candidates={CANDIDATES}
        onResolved={() => {}}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /accept/i }))
    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent(/already resolved/i),
    )
    expect(screen.getByRole('button', { name: /accept/i })).toBeEnabled()
  })
})

describe('park story — why it parked (T-206/T-207)', () => {
  it('shows the reason, the disagreeing senses as badges, and captions the list as ranked', () => {
    mockBackend({})
    render(
      <ReviewPanel
        reviewId="rev-1"
        rec="low"
        query="frank ocean strawberry swing"
        candidates={CANDIDATES}
        reason="Fingerprint and Shazam both matched Coldplay; the title said Frank Ocean."
        contradictions={['fp: Coldplay — Strawberry Swing', 'yt: Frank Ocean ≠ Coldplay']}
        onResolved={() => {}}
      />,
    )
    expect(screen.getByText(/why this parked/i)).toBeInTheDocument()
    expect(screen.getByText(/both matched Coldplay/i)).toBeInTheDocument()
    // The terse `fp:`/`yt:` prefixes become sense badges, remainder as text.
    expect(screen.getByText('fingerprint')).toBeInTheDocument()
    expect(screen.getByText('youtube')).toBeInTheDocument()
    expect(screen.getByText(/Coldplay — Strawberry Swing/)).toBeInTheDocument()
    expect(screen.getByText(/ranked by the adjudicator/i)).toBeInTheDocument()
  })

  it('renders nothing on the R1/degrade park — no reason, no story, no ranked caption', () => {
    mockBackend({})
    render(
      <ReviewPanel
        reviewId="rev-1"
        rec="low"
        query="q"
        candidates={CANDIDATES}
        reason={null}
        contradictions={[]}
        onResolved={() => {}}
      />,
    )
    expect(screen.queryByText(/why this parked/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/ranked by the adjudicator/i)).not.toBeInTheDocument()
  })

  it('adjudication unavailable: shows the reason, but no contradictions and no ranked claim', () => {
    mockBackend({})
    render(
      <ReviewPanel
        reviewId="rev-1"
        rec="low"
        query="nines outro"
        candidates={CANDIDATES}
        reason="Adjudication unavailable — the identity service didn't answer for this track."
        contradictions={[]}
        onResolved={() => {}}
      />,
    )
    expect(screen.getByText(/adjudication unavailable/i)).toBeInTheDocument()
    // No contradictions were produced, so the list must not claim an adjudicated order.
    expect(screen.queryByText(/ranked by the adjudicator/i)).not.toBeInTheDocument()
  })

  it('a note with no recognised sense prefix still renders, as a plain line', () => {
    mockBackend({})
    render(
      <ReviewPanel
        reviewId="rev-1"
        rec="low"
        query="q"
        candidates={CANDIDATES}
        reason="Senses disagree."
        contradictions={['no single sense could confirm the recording']}
        onResolved={() => {}}
      />,
    )
    expect(
      screen.getByText(/no single sense could confirm the recording/i),
    ).toBeInTheDocument()
    // The whole string is the text — nothing was mis-parsed into a badge.
    expect(screen.queryByText('fingerprint')).not.toBeInTheDocument()
  })

  it('does not mistake a hyphenated first word for a sense (colon-only separator)', () => {
    mockBackend({})
    render(
      <ReviewPanel
        reviewId="rev-1"
        rec="low"
        query="q"
        candidates={CANDIDATES}
        reason="Senses disagree."
        contradictions={['youtube-dl: no stream returned']}
        onResolved={() => {}}
      />,
    )
    // "youtube-dl:" must NOT resolve to a 'youtube' sense badge — the whole note is text.
    expect(screen.queryByText('youtube')).not.toBeInTheDocument()
    expect(screen.getByText(/youtube-dl: no stream returned/i)).toBeInTheDocument()
  })

  it('drops the story once the owner re-searches — it belongs to the original park', async () => {
    mockBackend({
      search: () =>
        jsonResponse({
          artist: 'Frank Ocean',
          title: 'Strawberry Swing',
          candidates: [
            { candidate_id: 'rec-new', title: 'Strawberry Swing', artist: 'Frank Ocean', score: 0.9 },
          ],
        }),
    })
    render(
      <ReviewPanel
        reviewId="rev-1"
        rec="low"
        query="q"
        candidates={CANDIDATES}
        reason="Senses disagree."
        contradictions={['fp: Coldplay']}
        onResolved={() => {}}
      />,
    )
    expect(screen.getByText(/why this parked/i)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /none of these/i }))
    fireEvent.click(screen.getByRole('button', { name: /re-search/i }))
    await waitFor(() => expect(screen.getByText('Strawberry Swing')).toBeInTheDocument())
    // The park story described the original park, not this fresh MusicBrainz list.
    expect(screen.queryByText(/why this parked/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/ranked by the adjudicator/i)).not.toBeInTheDocument()
  })
})

describe('re-parked after a failed resume (T-029)', () => {
  it('shows the reason the previous pick failed, above the still-usable panel', () => {
    mockBackend({})
    render(
      <ReviewPanel
        reviewId="rev-1"
        rec="low"
        query="q"
        candidates={CANDIDATES}
        onResolved={() => {}}
        message="That match couldn't be applied — the chosen recording no longer resolves."
      />,
    )
    expect(screen.getByRole('alert')).toHaveTextContent(/no longer resolves/i)
    // The panel is re-usable, not dead: accept and reject are both live so the owner
    // can pick again. (The remount that clears a latched `submitting` is TrackCard's
    // job, via the review key/epoch.)
    expect(screen.getByRole('button', { name: /accept/i })).toBeEnabled()
    expect(screen.getByRole('button', { name: /^reject$/i })).toBeEnabled()
  })

  it('shows no re-park notice on a first park', () => {
    mockBackend({})
    render(
      <ReviewPanel
        reviewId="rev-1"
        rec="low"
        query="q"
        candidates={CANDIDATES}
        onResolved={() => {}}
      />,
    )
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})

const DUPLICATE_ROW = {
  review_id: 'rev-dup',
  job_id: 'job-1',
  query: 'take on me',
  rec: 'duplicate',
  candidates: [],
  duplicate: {
    existing: [
      {
        path: '/music/a-ha/Take On Me.mp3',
        bitrate: 192000,
        title: 'Take On Me',
        artist: 'a-ha',
        album: 'Hunting High and Low',
      },
    ],
    incoming: { exists: true, bitrate: 320000, title: 'Take On Me', artist: 'a-ha' },
  },
}

describe('duplicate — "you already have this; keep which?"', () => {
  it('fetches the library detail the event cannot carry, and shows both bitrates', async () => {
    mockBackend({ review: DUPLICATE_ROW })
    render(
      <ReviewPanel
        reviewId="rev-dup"
        rec="duplicate"
        query="take on me"
        candidates={[]}
        onResolved={() => {}}
      />,
    )
    await waitFor(() => expect(screen.getByText('192 kbps')).toBeInTheDocument())
    expect(screen.getByText('320 kbps')).toBeInTheDocument()
  })

  it('each branch is reachable and sends the right body', async () => {
    const onResolved = vi.fn()
    const fetchMock = mockBackend({ review: DUPLICATE_ROW })
    render(
      <ReviewPanel
        reviewId="rev-dup"
        rec="duplicate"
        query="q"
        candidates={[]}
        onResolved={onResolved}
      />,
    )
    fireEvent.click(await screen.findByRole('button', { name: /keep existing/i }))
    await waitFor(() => expect(onResolved).toHaveBeenCalledOnce())
    expect(resolveBody(fetchMock)).toEqual({ choice: 'keep_existing' })
  })

  it('keep both sends the owner-typed suffix', async () => {
    const onResolved = vi.fn()
    const fetchMock = mockBackend({ review: DUPLICATE_ROW })
    render(
      <ReviewPanel
        reviewId="rev-dup"
        rec="duplicate"
        query="q"
        candidates={[]}
        onResolved={onResolved}
      />,
    )
    await screen.findByRole('button', { name: /keep both/i })
    const input = screen.getByRole('textbox')
    fireEvent.change(input, { target: { value: '(2015 Remaster)' } })
    fireEvent.click(screen.getByRole('button', { name: /keep both/i }))
    await waitFor(() => expect(onResolved).toHaveBeenCalledOnce())
    expect(resolveBody(fetchMock)).toEqual({
      choice: 'keep_both',
      suffix: '(2015 Remaster)',
    })
  })

  it('a swept-away download disables the landing branches, keeps discard reachable', async () => {
    const gone = {
      ...DUPLICATE_ROW,
      duplicate: {
        ...DUPLICATE_ROW.duplicate,
        incoming: { exists: false, bitrate: 0, title: null, artist: null },
      },
    }
    mockBackend({ review: gone })
    render(
      <ReviewPanel
        reviewId="rev-dup"
        rec="duplicate"
        query="q"
        candidates={[]}
        onResolved={() => {}}
      />,
    )
    await screen.findByRole('button', { name: /replace/i })
    expect(screen.getByRole('button', { name: /replace/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /keep both/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /keep existing/i })).toBeEnabled()
  })

  it('says so plainly when the review has left the queue', async () => {
    mockBackend({}) // no review → 404
    render(
      <ReviewPanel
        reviewId="rev-dup"
        rec="duplicate"
        query="q"
        candidates={[]}
        onResolved={() => {}}
      />,
    )
    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent(/no longer in the queue/i),
    )
  })

  it('retries a transient load failure instead of dead-ending', async () => {
    let calls = 0
    mockBackend({
      review: () => {
        calls += 1
        // First load fails (a --reload blip); the retry succeeds.
        return calls === 1
          ? new Response('nope', { status: 500 })
          : jsonResponse(DUPLICATE_ROW)
      },
    })
    render(
      <ReviewPanel
        reviewId="rev-dup"
        rec="duplicate"
        query="q"
        candidates={[]}
        onResolved={() => {}}
      />,
    )
    fireEvent.click(await screen.findByRole('button', { name: /try again/i }))
    await waitFor(() => expect(screen.getByText('192 kbps')).toBeInTheDocument())
  })
})

/**
 * Re-search — the exit that fixes the dead-end (T-103, ADR-020 exit 1).
 *
 * The dead-end has two shapes and both are covered: an EMPTY candidate list, and a
 * wrong-but-present one. The second is the trap — five confident-looking rows are
 * indistinguishable from useful ones until you read them — so "None of these?" has to
 * be reachable even when the list looks fine.
 */
describe('re-search — correcting the question', () => {
  const FOUND = {
    artist: 'Frank Ocean',
    title: 'Strawberry Swing',
    candidates: [
      {
        candidate_id: '908e389b-256c-4f6a-9d75-0e0a81815444',
        title: 'Strawberry Swing',
        artist: 'Frank Ocean',
        score: 0.889,
      },
    ],
  }

  it('pre-fills the form with what the machine searched with', () => {
    mockBackend({})
    render(
      <ReviewPanel
        reviewId="rev-1"
        rec="none"
        query="Frank Ocean - Strawberry Swing"
        candidates={[]}
        // The real fixture's shape: yt-dlp wrote the UPLOADER into the artist tag.
        guess={{ artist: 'Jon Hunt Playlists', title: 'Frank Ocean - Strawberry Swing' }}
        onResolved={() => {}}
      />,
    )
    // Showing the wrong values IS the point — it's how the owner spots the mistake.
    expect(screen.getByLabelText(/artist/i)).toHaveValue('Jon Hunt Playlists')
    expect(screen.getByLabelText(/title/i)).toHaveValue('Frank Ocean - Strawberry Swing')
  })

  it('opens the form unprompted when there is nothing to pick from', () => {
    mockBackend({})
    render(
      <ReviewPanel reviewId="rev-1" rec="none" query="q" candidates={[]} onResolved={() => {}} />,
    )
    // A candidate-less park has no list to say "none of these" about.
    expect(screen.getByRole('button', { name: /re-search/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /none of these/i })).not.toBeInTheDocument()
  })

  it('keeps the form behind a control when there ARE candidates to pick', () => {
    mockBackend({})
    render(
      <ReviewPanel reviewId="rev-1" rec="low" query="q" candidates={CANDIDATES} onResolved={() => {}} />,
    )
    expect(screen.queryByRole('button', { name: /re-search/i })).not.toBeInTheDocument()
    // But it must still be reachable: a wrong-but-present list is the harder dead-end.
    fireEvent.click(screen.getByRole('button', { name: /none of these/i }))
    expect(screen.getByRole('button', { name: /re-search/i })).toBeInTheDocument()
  })

  it('falls back to the raw query when no guess rode along', () => {
    mockBackend({})
    render(
      <ReviewPanel reviewId="rev-1" rec="none" query="Outro" candidates={[]} onResolved={() => {}} />,
    )
    expect(screen.getByLabelText(/title/i)).toHaveValue('Outro')
    expect(screen.getByLabelText(/artist/i)).toHaveValue('')
  })

  it('swaps the two fields in one click', () => {
    mockBackend({})
    render(
      <ReviewPanel
        reviewId="rev-1"
        rec="none"
        query="q"
        candidates={[]}
        guess={{ artist: 'All Get Right', title: 'Nipsey Hussle' }}
        onResolved={() => {}}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /swap/i }))
    expect(screen.getByLabelText(/artist/i)).toHaveValue('Nipsey Hussle')
    expect(screen.getByLabelText(/title/i)).toHaveValue('All Get Right')
  })

  it('sends the corrected terms and replaces the list with what comes back', async () => {
    const fetchMock = mockBackend({ search: () => jsonResponse(FOUND) })
    render(
      <ReviewPanel
        reviewId="rev-1"
        rec="low"
        query="q"
        candidates={CANDIDATES}
        onResolved={() => {}}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /none of these/i }))
    fireEvent.change(screen.getByLabelText(/artist/i), { target: { value: 'Frank Ocean' } })
    fireEvent.change(screen.getByLabelText(/title/i), { target: { value: 'Strawberry Swing' } })
    fireEvent.click(screen.getByRole('button', { name: /re-search/i }))

    await waitFor(() =>
      expect(screen.getByRole('radiogroup', { name: /new results/i })).toBeInTheDocument(),
    )
    const call = fetchMock.mock.calls.find((c: unknown[]) => String(c[0]).includes('/search'))
    expect(JSON.parse((call![1] as RequestInit).body as string)).toEqual({
      artist: 'Frank Ocean',
      title: 'Strawberry Swing',
    })
    // The parked candidates are gone from the list — they were the wrong answer.
    expect(screen.queryByText('Freestyle')).not.toBeInTheDocument()
  })

  it('lands the re-searched recording, which was never a parked candidate', async () => {
    // The whole point of ADR-020's first binding consequence, end to end on the client.
    const onResolved = vi.fn()
    const fetchMock = mockBackend({ search: () => jsonResponse(FOUND) })
    render(
      <ReviewPanel
        reviewId="rev-1"
        rec="none"
        query="q"
        candidates={[]}
        onResolved={onResolved}
      />,
    )
    fireEvent.change(screen.getByLabelText(/title/i), { target: { value: 'Strawberry Swing' } })
    fireEvent.click(screen.getByRole('button', { name: /re-search/i }))
    // The best result is preselected, so accepting is one click.
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /accept/i })).toBeEnabled(),
    )
    fireEvent.click(screen.getByRole('button', { name: /accept/i }))
    await waitFor(() => expect(onResolved).toHaveBeenCalledOnce())
    expect(resolveBody(fetchMock)).toEqual({
      choice: '908e389b-256c-4f6a-9d75-0e0a81815444',
    })
  })

  it('an empty result is not a dead panel — the form stays open to try again', async () => {
    let calls = 0
    mockBackend({
      search: () => {
        calls += 1
        return calls === 1
          ? jsonResponse({ artist: 'Nines', title: 'Nonsense', candidates: [] })
          : jsonResponse(FOUND)
      },
    })
    render(
      <ReviewPanel reviewId="rev-1" rec="none" query="q" candidates={[]} onResolved={() => {}} />,
    )
    fireEvent.change(screen.getByLabelText(/title/i), { target: { value: 'Nonsense' } })
    fireEvent.click(screen.getByRole('button', { name: /re-search/i }))

    await waitFor(() => expect(screen.getByText(/no record of that/i)).toBeInTheDocument())
    // ADR-020 consequence 2: exits, never a terminal state. Reject stays, and the form
    // is still there to search with different terms.
    expect(screen.getByRole('button', { name: /reject/i })).toBeEnabled()
    const searchAgain = screen.getByRole('button', { name: /re-search/i })
    expect(searchAgain).toBeEnabled()

    // And searching again genuinely re-queries rather than showing a cached miss.
    fireEvent.change(screen.getByLabelText(/title/i), { target: { value: 'Strawberry Swing' } })
    fireEvent.click(searchAgain)
    await waitFor(() => expect(screen.getByText('Strawberry Swing')).toBeInTheDocument())
  })

  it('keeps the corrected terms when the form is closed and reopened', async () => {
    // The bug an altitude review caught: a successful search collapsed the form, and
    // reopening it REMOUNTED it, re-seeding both fields from `guess` — silently binning
    // what the owner typed. Not an edge case: ADR-020's amendment measured that
    // MusicBrainz almost never returns nothing, so "many results, all wrong" is the
    // normal outcome and a SECOND search is the ordinary next move.
    mockBackend({ search: () => jsonResponse(FOUND) })
    render(
      <ReviewPanel
        reviewId="rev-1"
        rec="low"
        query="q"
        candidates={CANDIDATES}
        guess={{ artist: 'Jon Hunt Playlists', title: 'wrong title' }}
        onResolved={() => {}}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /none of these/i }))
    fireEvent.change(screen.getByLabelText(/artist/i), { target: { value: 'Frank Ocean' } })
    fireEvent.change(screen.getByLabelText(/title/i), { target: { value: 'Strawberry Swing' } })
    fireEvent.click(screen.getByRole('button', { name: /re-search/i }))

    // Results arrive and the form collapses.
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: /re-search/i })).not.toBeInTheDocument(),
    )
    fireEvent.click(screen.getByRole('button', { name: /none of these/i }))
    expect(screen.getByLabelText(/artist/i)).toHaveValue('Frank Ocean')
    expect(screen.getByLabelText(/title/i)).toHaveValue('Strawberry Swing')
  })

  it('a failed search leaves the panel usable, not stuck on "Searching…"', async () => {
    mockBackend({ search: () => jsonResponse({ detail: 'MusicBrainz is unreachable' }, 503) })
    render(
      <ReviewPanel reviewId="rev-1" rec="none" query="q" candidates={[]} onResolved={() => {}} />,
    )
    fireEvent.change(screen.getByLabelText(/title/i), { target: { value: 'Outro' } })
    fireEvent.click(screen.getByRole('button', { name: /re-search/i }))
    await waitFor(() =>
      expect(screen.getByText(/MusicBrainz is unreachable/i)).toBeInTheDocument(),
    )
    // A search changes nothing server-side, so unlike a resolve the button must return.
    expect(screen.getByRole('button', { name: /re-search/i })).toBeEnabled()
  })

  it('refuses to search with both fields empty', () => {
    mockBackend({})
    render(
      <ReviewPanel reviewId="rev-1" rec="none" query="" candidates={[]} onResolved={() => {}} />,
    )
    expect(screen.getByRole('button', { name: /re-search/i })).toBeDisabled()
  })
})

/**
 * Keep-untagged — "land it with my own tags" (T-103B, ADR-020 exit 2).
 *
 * The escape hatch for songs MusicBrainz doesn't know: the owner provides artist
 * and title, and the track lands without a MusicBrainz match — no cover art, no
 * auto-genre. Always reachable from the weak-match panel, regardless of whether
 * candidates exist.
 */
describe('keep-untagged — landing with manual tags', () => {
  it('"Keep with my tags" is always visible in the action bar', () => {
    mockBackend({})
    render(
      <ReviewPanel
        reviewId="rev-1"
        rec="low"
        query="q"
        candidates={CANDIDATES}
        onResolved={() => {}}
      />,
    )
    expect(screen.getByRole('button', { name: /keep with my tags/i })).toBeEnabled()
  })

  it('opens the form and hides the candidate list', () => {
    mockBackend({})
    render(
      <ReviewPanel
        reviewId="rev-1"
        rec="low"
        query="q"
        candidates={CANDIDATES}
        onResolved={() => {}}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /keep with my tags/i }))
    // The candidate list is gone; the form is up.
    expect(screen.queryByRole('radiogroup')).not.toBeInTheDocument()
    expect(screen.getByText(/your tags/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /land with these tags/i })).toBeInTheDocument()
  })

  it('"Back" returns to the candidate view', () => {
    mockBackend({})
    render(
      <ReviewPanel
        reviewId="rev-1"
        rec="low"
        query="q"
        candidates={CANDIDATES}
        onResolved={() => {}}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /keep with my tags/i }))
    fireEvent.click(screen.getByRole('button', { name: /back/i }))
    expect(screen.getByRole('radiogroup')).toBeInTheDocument()
  })

  it('sends the correct body with artist and title', async () => {
    const onResolved = vi.fn()
    const fetchMock = mockBackend({})
    render(
      <ReviewPanel
        reviewId="rev-1"
        rec="low"
        query="q"
        candidates={CANDIDATES}
        onResolved={onResolved}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /keep with my tags/i }))
    fireEvent.change(screen.getByLabelText(/artist/i), { target: { value: 'Nines' } })
    fireEvent.change(screen.getByLabelText(/title/i), { target: { value: 'Outro' } })
    fireEvent.click(screen.getByRole('button', { name: /land with these tags/i }))
    await waitFor(() => expect(onResolved).toHaveBeenCalledOnce())
    expect(resolveBody(fetchMock)).toEqual({
      choice: 'keep_untagged',
      artist: 'Nines',
      title: 'Outro',
    })
  })

  it('includes album and year when provided', async () => {
    const onResolved = vi.fn()
    const fetchMock = mockBackend({})
    render(
      <ReviewPanel
        reviewId="rev-1"
        rec="none"
        query="q"
        candidates={[]}
        onResolved={onResolved}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /keep with my tags/i }))
    fireEvent.change(screen.getByLabelText(/artist/i), { target: { value: 'Nipsey Hussle' } })
    fireEvent.change(screen.getByLabelText(/title/i), { target: { value: 'Grinding All My Life' } })
    fireEvent.change(screen.getByLabelText(/album/i), { target: { value: 'Victory Lap' } })
    fireEvent.change(screen.getByLabelText(/year/i), { target: { value: '2018' } })
    fireEvent.click(screen.getByRole('button', { name: /land with these tags/i }))
    await waitFor(() => expect(onResolved).toHaveBeenCalledOnce())
    expect(resolveBody(fetchMock)).toEqual({
      choice: 'keep_untagged',
      artist: 'Nipsey Hussle',
      title: 'Grinding All My Life',
      album: 'Victory Lap',
      year: 2018,
    })
  })

  it('refuses to submit when artist is empty', () => {
    mockBackend({})
    render(
      <ReviewPanel
        reviewId="rev-1"
        rec="none"
        query="q"
        candidates={[]}
        onResolved={() => {}}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /keep with my tags/i }))
    fireEvent.change(screen.getByLabelText(/artist/i), { target: { value: '' } })
    fireEvent.change(screen.getByLabelText(/title/i), { target: { value: 'Outro' } })
    expect(screen.getByRole('button', { name: /land with these tags/i })).toBeDisabled()
  })

  it('refuses to submit when title is empty', () => {
    mockBackend({})
    render(
      <ReviewPanel
        reviewId="rev-1"
        rec="none"
        query="q"
        candidates={[]}
        onResolved={() => {}}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /keep with my tags/i }))
    fireEvent.change(screen.getByLabelText(/artist/i), { target: { value: 'Nines' } })
    fireEvent.change(screen.getByLabelText(/title/i), { target: { value: '' } })
    expect(screen.getByRole('button', { name: /land with these tags/i })).toBeDisabled()
  })

  it('pre-fills from the re-search state, not from guess', () => {
    mockBackend({})
    render(
      <ReviewPanel
        reviewId="rev-1"
        rec="low"
        query="nines outro"
        candidates={CANDIDATES}
        guess={{ artist: 'Jon Hunt Playlists', title: 'Nines - Outro' }}
        onResolved={() => {}}
      />,
    )
    // The keep-untagged form shares the corrected-term state with the re-search form.
    // If the owner corrected the artist first, that correction carries over.
    fireEvent.click(screen.getByRole('button', { name: /none of these/i }))
    fireEvent.change(screen.getByLabelText(/artist/i), { target: { value: 'Nines' } })
    fireEvent.change(screen.getByLabelText(/title/i), { target: { value: 'Outro' } })
    // Now switch to keep-untagged — the corrected values should carry.
    // First go back to candidate view to access the keep button.
    fireEvent.click(screen.getByRole('button', { name: /keep with my tags/i }))
    expect(screen.getByLabelText(/artist/i)).toHaveValue('Nines')
    expect(screen.getByLabelText(/title/i)).toHaveValue('Outro')
  })

  it('omits year when it is out of range', async () => {
    const onResolved = vi.fn()
    const fetchMock = mockBackend({})
    render(
      <ReviewPanel
        reviewId="rev-1"
        rec="none"
        query="q"
        candidates={[]}
        onResolved={onResolved}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /keep with my tags/i }))
    fireEvent.change(screen.getByLabelText(/artist/i), { target: { value: 'Test' } })
    fireEvent.change(screen.getByLabelText(/title/i), { target: { value: 'Song' } })
    fireEvent.change(screen.getByLabelText(/year/i), { target: { value: '1800' } })
    fireEvent.click(screen.getByRole('button', { name: /land with these tags/i }))
    await waitFor(() => expect(onResolved).toHaveBeenCalledOnce())
    const body = resolveBody(fetchMock) as Record<string, unknown>
    expect(body.year).toBeUndefined()
  })
})
