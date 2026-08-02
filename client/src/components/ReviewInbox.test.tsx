/**
 * ReviewInbox — the durable review surface (T-101 → T-102).
 *
 * T-101 made parked reviews visible on cold load. T-102 makes them RESOLVABLE: the
 * review lifecycle moved from TrackCard into the inbox. Each row expands in place to
 * show ReviewPanel; resolve collapses the row and signals App.
 *
 * These tests pin:
 * 1. The pure component: rows, tags, expand/collapse, ReviewPanel inside the row.
 * 2. The App wiring: cold-load resolve, the card→inbox→App resolve signal, the
 *    delayed re-fetch safety net for cold-load re-parks.
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
        onReviewResolved={() => {}}
      />,
    )
    expect(screen.getByText('nines outro')).toBeInTheDocument()
    expect(screen.getByText('take on me')).toBeInTheDocument()
    expect(screen.getByText('Weak match')).toBeInTheDocument()
    expect(screen.getByText('Duplicate')).toBeInTheDocument()
  })

  it('shows a resting empty state when nothing is waiting', () => {
    render(<ReviewInbox reviews={[]} onReviewResolved={() => {}} />)
    expect(screen.getByText(/nothing waiting/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /review/i })).not.toBeInTheDocument()
  })

  it('Review is always enabled — no liveJobIds gate (T-102)', () => {
    render(
      <ReviewInbox
        reviews={[WEAK_ROW]}
        onReviewResolved={() => {}}
      />,
    )
    expect(screen.getByRole('button', { name: /review/i })).toBeEnabled()
  })

  it('expands a row in place on Review click, showing the ReviewPanel', async () => {
    render(
      <ReviewInbox
        reviews={[WEAK_ROW]}
        onReviewResolved={() => {}}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /review/i }))
    await waitFor(() =>
      expect(screen.getByText('Outro')).toBeInTheDocument(),
    )
    expect(screen.getByRole('button', { name: /accept/i })).toBeInTheDocument()
    // The button label toggles to "Close" when expanded.
    expect(screen.getByRole('button', { name: /close/i })).toBeInTheDocument()
  })

  it('collapses an expanded row on Close click', async () => {
    render(
      <ReviewInbox
        reviews={[WEAK_ROW]}
        onReviewResolved={() => {}}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /review/i }))
    await waitFor(() =>
      expect(screen.getByText('Outro')).toBeInTheDocument(),
    )
    fireEvent.click(screen.getByRole('button', { name: /close/i }))
    expect(screen.queryByText('Outro')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /review/i })).toBeInTheDocument()
  })

  it('fires onReviewResolved and collapses after a successful resolve', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const url = String(input)
      if (url.includes('/resolve')) return Promise.resolve(jsonResponse({ ok: true }))
      throw new Error(`unexpected fetch: ${url}`)
    })
    const onResolved = vi.fn()
    render(
      <ReviewInbox
        reviews={[WEAK_ROW]}
        onReviewResolved={onResolved}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /review/i }))
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /accept/i })).toBeInTheDocument(),
    )
    fireEvent.click(screen.getByRole('button', { name: /accept/i }))
    await waitFor(() => expect(onResolved).toHaveBeenCalledWith('job-1'))
  })

  it('shows the re-park reason from last_error', async () => {
    const reparked: ReviewRow = {
      ...WEAK_ROW,
      last_error: "That match couldn't be applied.",
    }
    render(
      <ReviewInbox
        reviews={[reparked]}
        onReviewResolved={() => {}}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /review/i }))
    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent(/couldn't be applied/i),
    )
  })
})

describe('App wiring — cold load + inbox resolve', () => {
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

  it('surfaces a parked review on cold load, with no live card', async () => {
    reviewsData = [WEAK_ROW]
    render(<App />)
    await waitFor(() =>
      expect(inbox().getByText('nines outro')).toBeInTheDocument(),
    )
    expect(document.querySelector('.track-card')).toBeNull()
    expect(screen.getByText('No tracks yet.')).toBeInTheDocument()
  })

  it('shows the resting empty state when the queue is empty on cold load', async () => {
    render(<App />)
    await waitFor(() =>
      expect(inbox().getByText(/nothing waiting/i)).toBeInTheDocument(),
    )
  })

  it('a cold-loaded review can be expanded and resolved from the inbox (T-102)', async () => {
    reviewsData = [WEAK_ROW]
    render(<App />)
    await waitFor(() =>
      expect(inbox().getByText('nines outro')).toBeInTheDocument(),
    )
    // Expand the review — no card needed.
    fireEvent.click(inbox().getByRole('button', { name: /review/i }))
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /accept/i })).toBeInTheDocument(),
    )
    // Resolve it.
    reviewsData = []
    fireEvent.click(screen.getByRole('button', { name: /accept/i }))
    await waitFor(() =>
      expect(inbox().queryByText('nines outro')).not.toBeInTheDocument(),
    )
    expect(inbox().getByText(/nothing waiting/i)).toBeInTheDocument()
  })

  it('appends a row when a live card parks a review', async () => {
    render(<App />)
    await waitFor(() =>
      expect(inbox().getByText(/nothing waiting/i)).toBeInTheDocument(),
    )

    fireEvent.change(screen.getByLabelText(/youtube song url/i), {
      target: { value: 'https://youtu.be/abc' },
    })
    fireEvent.click(screen.getByRole('button', { name: /^go$/i }))
    await waitFor(() => expect(FakeEventSource.instances.length).toBe(1))

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
    // The card shows the hand-off note, not the panel (T-102).
    expect(screen.getByText(/moved to your review inbox/i)).toBeInTheDocument()
  })

  it('resolving from the inbox while a card exists signals the card to resume', async () => {
    reviewsData = [WEAK_ROW]
    render(<App />)

    // Start a job so a card exists for job-1.
    fireEvent.change(screen.getByLabelText(/youtube song url/i), {
      target: { value: 'https://youtu.be/abc' },
    })
    fireEvent.click(screen.getByRole('button', { name: /^go$/i }))
    await waitFor(() => expect(FakeEventSource.instances.length).toBe(1))

    // Park it so the card is at review_required.
    FakeEventSource.latest().emit('track.review_required', {
      review_id: 'rev-1',
      rec: 'low',
      query: 'nines outro',
      candidates: WEAK_ROW.candidates,
    })
    await waitFor(() =>
      expect(inbox().getByText('nines outro')).toBeInTheDocument(),
    )

    // Expand and resolve from the inbox.
    fireEvent.click(inbox().getByRole('button', { name: /review/i }))
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /accept/i })).toBeInTheDocument(),
    )
    reviewsData = []
    fireEvent.click(screen.getByRole('button', { name: /accept/i }))

    // The card should re-subscribe — a FRESH EventSource opens.
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(2))
    const es2 = FakeEventSource.latest()
    expect(es2.url).toBe('/api/jobs/job-1/events')
  })
})
