/**
 * Harness smoke tests, written against the *existing* T-016 card rather than a
 * toy component — a harness that only proves it can render a `<div>` proves
 * nothing about whether it can drive this app.
 *
 * These pin the two stream behaviours T-017 must inherit rather than reinvent:
 * the card closes its stream on `track.review_required`, and a dropped
 * connection triggers exactly one snapshot per outage (not one per retry).
 */

import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { TrackCard } from './TrackCard'
import { FakeEventSource, installFakeEventSource } from '../test/fakeEventSource'

beforeEach(() => {
  installFakeEventSource()
  vi.restoreAllMocks()
})

function renderCard() {
  render(<TrackCard jobId="job-1" url="https://youtu.be/abc" />)
  return FakeEventSource.latest()
}

describe('the harness can drive the real card', () => {
  it('subscribes to the job stream on mount', () => {
    const es = renderCard()
    expect(es.url).toBe('/api/jobs/job-1/events')
  })

  it('renders progress from a named event', async () => {
    const es = renderCard()
    es.emit('track.downloading', {})
    await waitFor(() => {
      expect(screen.getByText(/download/i)).toBeInTheDocument()
    })
  })
})

describe('stream lifecycle T-017 must not break', () => {
  it('closes the stream on track.review_required', async () => {
    const es = renderCard()
    es.emit('track.review_required', { review_id: 'rev-1' })
    await waitFor(() => expect(es.closed).toBe(true))
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

    const es = renderCard()
    es.fail()
    es.fail()
    es.fail()

    // EventSource fires onerror on every retry; the fallback is guarded per
    // outage. Three failures, one question asked.
    await waitFor(() => expect(getJob).toHaveBeenCalledTimes(1))
  })
})
