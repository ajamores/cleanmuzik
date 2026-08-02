/**
 * TrackCard — the live pipeline card (T-016 → T-102).
 *
 * T-102 moved the review lifecycle to the inbox. The card now shows a hand-off note
 * at review_required instead of hosting ReviewPanel. These tests pin:
 * - Stream subscription and progress rendering
 * - Stream close on review_required (still terminal for the stream)
 * - The hand-off note (no panel, no candidates — just a message)
 * - The resolveEpoch prop re-subscribing the card after an inbox resolve
 * - The one-snapshot-per-outage reconnect fallback
 * - Album/playlist notes (T-026)
 * - Landing receipt rendering (ADR-015)
 */

import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { TrackCard } from './TrackCard'
import { FakeEventSource, installFakeEventSource } from '../test/fakeEventSource'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const PARKED = {
  review_id: 'rev-1',
  rec: 'low',
  query: 'nines outro',
  candidates: [{ candidate_id: 'rec-A', title: 'Outro', artist: 'Nines', score: 0.46 }],
}

beforeEach(() => {
  installFakeEventSource()
  vi.restoreAllMocks()
})

function renderCard(props?: { resolveEpoch?: number }) {
  const result = render(
    <TrackCard jobId="job-1" url="https://youtu.be/abc" {...props} />,
  )
  return { es: FakeEventSource.latest(), ...result }
}

describe('the harness can drive the real card', () => {
  it('subscribes to the job stream on mount', () => {
    const { es } = renderCard()
    expect(es.url).toBe('/api/jobs/job-1/events')
  })

  it('renders progress from a named event', async () => {
    const { es } = renderCard()
    es.emit('track.downloading', {})
    await waitFor(() => {
      expect(screen.getByText(/download/i)).toBeInTheDocument()
    })
  })
})

describe('T-026 album/playlist note', () => {
  const PLAYLIST = /part of a playlist/i
  const ALBUM = /part of an album/i

  it('shows the playlist note when job.queued carries list_kind=playlist', async () => {
    const { es } = renderCard()
    es.emit('job.queued', { job_id: 'job-1', url: 'x', list_kind: 'playlist' })
    await waitFor(() => expect(screen.getByText(PLAYLIST)).toBeInTheDocument())
  })

  it('shows the album note when list_kind=album', async () => {
    const { es } = renderCard()
    es.emit('job.queued', { job_id: 'job-1', url: 'x', list_kind: 'album' })
    await waitFor(() => expect(screen.getByText(ALBUM)).toBeInTheDocument())
  })

  it('stays silent for a bare song (list_kind null)', () => {
    const { es } = renderCard()
    es.emit('job.queued', { job_id: 'job-1', url: 'x', list_kind: null })
    es.emit('track.downloading', {})
    expect(screen.queryByText(PLAYLIST)).not.toBeInTheDocument()
    expect(screen.queryByText(ALBUM)).not.toBeInTheDocument()
  })

  it('holds the note across a resume job.queued that omits the flag (monotonic)', async () => {
    const { es } = renderCard()
    es.emit('job.queued', { job_id: 'job-1', url: 'x', list_kind: 'playlist' })
    await waitFor(() => expect(screen.getByText(PLAYLIST)).toBeInTheDocument())
    es.emit('job.queued', { job_id: 'job-1', url: 'x' })
    expect(screen.getByText(PLAYLIST)).toBeInTheDocument()
  })
})

describe('stream lifecycle and review hand-off (T-102)', () => {
  it('closes the stream on track.review_required', async () => {
    const { es } = renderCard()
    es.emit('track.review_required', { review_id: 'rev-1' })
    await waitFor(() => expect(es.closed).toBe(true))
  })

  it('shows the hand-off note, NOT the panel, on review_required (T-102)', async () => {
    const { es } = renderCard()
    es.emit('track.review_required', PARKED)
    await waitFor(() =>
      expect(screen.getByText(/moved to your review inbox/i)).toBeInTheDocument(),
    )
    // The panel's action buttons must NOT be here — the inbox owns the review.
    expect(screen.queryByRole('button', { name: /accept/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /reject/i })).not.toBeInTheDocument()
  })

  it('labels the hand-off as "Duplicate" for a duplicate park', async () => {
    const { es } = renderCard()
    es.emit('track.review_required', { ...PARKED, rec: 'duplicate' })
    await waitFor(() =>
      expect(screen.getByText(/duplicate.*moved to your review inbox/i)).toBeInTheDocument(),
    )
  })

  it('shows a hand-off from a snapshot fallback too (restart recovery)', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const url = String(input)
      if (url.includes('/api/jobs/'))
        return Promise.resolve(
          jsonResponse({ job_id: 'job-1', status: 'review', review_id: 'rev-1' }),
        )
      throw new Error(`unexpected fetch: ${url}`)
    })

    const { es } = renderCard()
    es.fail()
    await waitFor(() =>
      expect(screen.getByText(/moved to your review inbox/i)).toBeInTheDocument(),
    )
  })

  it('re-subscribes when resolveEpoch bumps (inbox resolved)', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const url = String(input)
      if (url.includes('/api/jobs/'))
        return Promise.resolve(jsonResponse({ job_id: 'job-1', status: 'done' }))
      throw new Error(`unexpected fetch: ${url}`)
    })

    const { es: es1, rerender } = renderCard({ resolveEpoch: 0 })
    es1.emit('track.review_required', PARKED)
    await waitFor(() => expect(es1.closed).toBe(true))

    // Inbox resolved — App bumps resolveEpoch.
    rerender(
      <TrackCard jobId="job-1" url="https://youtu.be/abc" resolveEpoch={1} />,
    )

    // A FRESH EventSource opens for the resume.
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(2))
    const es2 = FakeEventSource.latest()
    expect(es2.url).toBe('/api/jobs/job-1/events')

    // The resume settles via the snapshot fallback (reject/keep_existing has no terminal event).
    es2.fail()
    await waitFor(() => expect(screen.getByText('Done')).toBeInTheDocument())
  })

  it('fires onReviewParked on a re-park from the resume stream', async () => {
    const onReviewParked = vi.fn()
    const { rerender } = render(
      <TrackCard
        jobId="job-1"
        url="https://youtu.be/abc"
        onReviewParked={onReviewParked}
        resolveEpoch={0}
      />,
    )
    const es1 = FakeEventSource.latest()
    es1.emit('track.review_required', PARKED)
    await waitFor(() => expect(es1.closed).toBe(true))
    expect(onReviewParked).toHaveBeenCalledTimes(1)

    // Inbox resolve → App bumps resolveEpoch on the SAME card, which re-subscribes.
    // rerender (not a second render) is what exercises that path: a fresh render would
    // mount an independent card with prevResolveEpoch already at 1, firing nothing.
    onReviewParked.mockClear()
    rerender(
      <TrackCard
        jobId="job-1"
        url="https://youtu.be/abc"
        onReviewParked={onReviewParked}
        resolveEpoch={1}
      />,
    )

    // A fresh EventSource opens for the resume episode.
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(2))

    // The resume fails and re-parks — onReviewParked fires again so App refreshes the inbox.
    FakeEventSource.latest().emit('track.review_required', {
      ...PARKED,
      message: "That match couldn't be applied.",
    })
    await waitFor(() => expect(onReviewParked).toHaveBeenCalled())
  })

  it('renders the landing path and tags from the track.done event (ADR-015)', async () => {
    const { es } = renderCard()
    es.emit('track.done', {
      job_id: 'job-1',
      path: '/mnt/c/Users/aj_am/Music/CleanMuzik/Band/Song.mp3',
      tags: { title: 'Song', artist: 'Band', genre: 'Rock', has_art: true },
    })
    await waitFor(() =>
      expect(
        screen.getByText('/mnt/c/Users/aj_am/Music/CleanMuzik/Band/Song.mp3'),
      ).toBeInTheDocument(),
    )
    expect(screen.getByText('Rock')).toBeInTheDocument()
    expect(screen.getByText('Art')).toBeInTheDocument()
  })

  it('shows where the song went on a post-landing scan failure (ADR-015)', async () => {
    const { es } = renderCard()
    es.emit('track.error', {
      job_id: 'job-1',
      stage: 'scan',
      message: 'Jellyfin scan failed',
      path: '/mnt/c/Users/aj_am/Music/CleanMuzik/Band/Song.mp3',
      tags: { title: 'Song', artist: 'Band' },
    })
    await waitFor(() =>
      expect(
        screen.getByText('/mnt/c/Users/aj_am/Music/CleanMuzik/Band/Song.mp3'),
      ).toBeInTheDocument(),
    )
    expect(screen.getByRole('alert')).toHaveTextContent(/failed/i)
    expect(document.querySelector('.track-card__step[data-state="failed"]')).toBeNull()
    expect(document.querySelector('.track-card__tags')).toBeNull()
  })

  it('recovers when a restart outlasts the first reconnect check (T-020)', async () => {
    let jobCalls = 0
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const url = String(input)
      if (url.includes('/api/jobs/')) {
        jobCalls += 1
        if (jobCalls === 1) return Promise.reject(new TypeError('backend down'))
        return Promise.resolve(jsonResponse({ job_id: 'job-1', status: 'error' }))
      }
      throw new Error(`unexpected fetch: ${url}`)
    })

    const { es } = renderCard()
    es.emit('track.identifying', {})
    es.fail()
    await waitFor(() => expect(jobCalls).toBe(1))
    await Promise.resolve()
    es.fail()
    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent(/failed/i),
    )
    expect(screen.queryByText(/no longer exists/i)).not.toBeInTheDocument()
  })

  it('recovers when the outage check gets a 5xx during a restart (does not freeze)', async () => {
    let jobCalls = 0
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const url = String(input)
      if (url.includes('/api/jobs/')) {
        jobCalls += 1
        if (jobCalls === 1) return Promise.resolve(jsonResponse({ detail: 'bad gateway' }, 502))
        return Promise.resolve(jsonResponse({ job_id: 'job-1', status: 'done' }))
      }
      throw new Error(`unexpected fetch: ${url}`)
    })

    const { es } = renderCard()
    es.emit('track.identifying', {})
    es.fail()
    await waitFor(() => expect(jobCalls).toBe(1))
    await Promise.resolve()
    es.fail()
    await waitFor(() => expect(screen.getByText('Done')).toBeInTheDocument())
  })

  it('shows a bare Done with no receipt on an event-less duplicate-skip finish (T-020)', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const url = String(input)
      if (url.includes('/api/jobs/'))
        return Promise.resolve(jsonResponse({ job_id: 'job-1', status: 'done' }))
      throw new Error(`unexpected fetch: ${url}`)
    })

    const { es } = renderCard()
    es.fail()
    await waitFor(() => expect(screen.getByText('Done')).toBeInTheDocument())
    expect(screen.queryByTitle(/\.mp3$/)).not.toBeInTheDocument()
  })

  it('takes one snapshot per outage, not one per failed retry', async () => {
    const getJob = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(
        new Response(JSON.stringify({ job_id: 'job-1', status: 'running' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )

    const { es } = renderCard()
    es.fail()
    es.fail()
    es.fail()

    await waitFor(() => expect(getJob).toHaveBeenCalledTimes(1))
  })
})
