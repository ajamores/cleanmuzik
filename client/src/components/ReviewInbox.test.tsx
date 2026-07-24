/**
 * ReviewInbox — the keystone of R1.1 (T-101, spec §7/§8).
 *
 * The gap R1 shipped: the review lifecycle lived inside TrackCard, an ephemeral card
 * that boots empty on reload, so a parked review — durably stored and served by
 * `GET /api/reviews` — was invisible and unreachable on a fresh load. These tests pin
 * the fix at the two levels that matter:
 *
 * 1. The pure component renders the queue, an empty resting state, and the
 *    weak-vs-duplicate tag.
 * 2. The App wiring proves the load-bearing behaviour: a review parked in a previous
 *    session appears on a COLD load with no live card present (the mount fetch), and the
 *    card→App seam keeps the inbox in sync as reviews park and resolve live.
 */

import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import App from '../App'
import { ReviewInbox } from './ReviewInbox'
import type { ReviewRow } from '../api'
import { FakeEventSource, installFakeEventSource } from '../test/fakeEventSource'

const WEAK_ROW: ReviewRow = {
  review_id: 'rev-1',
  job_id: 'job-1',
  query: 'nines outro',
  rec: 'low',
  candidates: [{ candidate_id: 'rec-A', title: 'Outro', artist: 'Nines', score: 0.46 }],
}

const DUP_ROW: ReviewRow = {
  review_id: 'rev-2',
  job_id: 'job-2',
  query: 'take on me',
  rec: 'duplicate',
  candidates: [],
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('ReviewInbox (pure)', () => {
  it('renders one row per review, tagged by branch', () => {
    render(
      <ReviewInbox
        reviews={[WEAK_ROW, DUP_ROW]}
        liveJobIds={new Set()}
        onReview={() => {}}
      />,
    )
    expect(screen.getByText('nines outro')).toBeInTheDocument()
    expect(screen.getByText('take on me')).toBeInTheDocument()
    // The weak-match-vs-keep-which tag: `rec === "duplicate"` is the keep-which branch.
    expect(screen.getByText('Weak match')).toBeInTheDocument()
    expect(screen.getByText('Duplicate')).toBeInTheDocument()
  })

  it('shows a resting empty state when nothing is waiting', () => {
    render(<ReviewInbox reviews={[]} liveJobIds={new Set()} onReview={() => {}} />)
    expect(screen.getByText(/nothing waiting/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /review/i })).not.toBeInTheDocument()
  })

  it("disables Review for a row whose card isn't live, enables it when it is", () => {
    const onReview = vi.fn()
    render(
      <ReviewInbox
        reviews={[WEAK_ROW]}
        liveJobIds={new Set(['job-1'])}
        onReview={onReview}
      />,
    )
    const button = screen.getByRole('button', { name: /review/i })
    expect(button).toBeEnabled()
    fireEvent.click(button)
    expect(onReview).toHaveBeenCalledWith(WEAK_ROW)
  })

  it("keeps Review inert for a cold-loaded review with no card", () => {
    render(
      <ReviewInbox reviews={[WEAK_ROW]} liveJobIds={new Set()} onReview={() => {}} />,
    )
    expect(screen.getByRole('button', { name: /review/i })).toBeDisabled()
  })
})

describe('App wiring — cold load + the card→App seam', () => {
  // Mutable server state the fetch mock reads, so a test can change the queue between the
  // mount fetch and a later refetch (exactly what park/resolve do server-side).
  let reviewsData: ReviewRow[]

  beforeEach(() => {
    installFakeEventSource()
    vi.restoreAllMocks()
    reviewsData = []
    vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      if (url.endsWith('/api/reviews') && method === 'GET') {
        return Promise.resolve(jsonResponse(reviewsData))
      }
      if (url.includes('/resolve')) {
        return Promise.resolve(jsonResponse({ ok: true }))
      }
      if (/\/api\/reviews\/[^/]+$/.test(url)) {
        return Promise.resolve(jsonResponse(WEAK_ROW))
      }
      if (url.endsWith('/api/jobs') && method === 'POST') {
        return Promise.resolve(jsonResponse({ job_id: 'job-1' }))
      }
      throw new Error(`unexpected fetch: ${method} ${url}`)
    })
  })

  function inbox() {
    return within(screen.getByRole('region', { name: 'Needs review' }))
  }

  it('surfaces a previous session’s parked review on cold load, with no live card', async () => {
    // The DONE-WHEN: a review parked before this session (served by GET /api/reviews)
    // appears on mount, reached through the fetch alone — no job, no TrackCard.
    reviewsData = [WEAK_ROW]
    render(<App />)
    await waitFor(() =>
      expect(inbox().getByText('nines outro')).toBeInTheDocument(),
    )
    // Proven independent of any card: nothing in the jobs list is mounted.
    expect(document.querySelector('.track-card')).toBeNull()
    expect(screen.getByText('No tracks yet.')).toBeInTheDocument()
  })

  it('shows the resting empty state when the queue is empty on cold load', async () => {
    render(<App />)
    await waitFor(() =>
      expect(inbox().getByText(/nothing waiting/i)).toBeInTheDocument(),
    )
  })

  it('appends a row when a live card parks a review, and removes it on resolve', async () => {
    render(<App />)
    // Cold load: empty queue, no rows.
    await waitFor(() =>
      expect(inbox().getByText(/nothing waiting/i)).toBeInTheDocument(),
    )

    // Start a job so a card (and its per-card SSE stream) exists.
    fireEvent.change(screen.getByLabelText(/youtube song url/i), {
      target: { value: 'https://youtu.be/abc' },
    })
    fireEvent.click(screen.getByRole('button', { name: /^go$/i }))
    await waitFor(() => expect(FakeEventSource.instances.length).toBe(1))

    // The card's stream parks the review. Server-side the row is now in the queue; the
    // park signal makes App re-read it.
    reviewsData = [WEAK_ROW]
    FakeEventSource.latest().emit('track.review_required', {
      review_id: 'rev-1',
      rec: 'low',
      query: 'nines outro',
      candidates: WEAK_ROW.candidates,
    })
    await waitFor(() =>
      expect(inbox().getByText('nines outro')).toBeInTheDocument(),
    )

    // Resolve it: the row leaves the server queue, and the resolve signal drops it.
    reviewsData = []
    fireEvent.click(await screen.findByRole('button', { name: /accept/i }))
    await waitFor(() =>
      expect(inbox().queryByText('nines outro')).not.toBeInTheDocument(),
    )
    expect(inbox().getByText(/nothing waiting/i)).toBeInTheDocument()
  })
})
