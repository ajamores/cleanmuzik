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
}) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
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
