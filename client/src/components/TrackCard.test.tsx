/**
 * Harness smoke tests, written against the *existing* T-016 card rather than a
 * toy component — a harness that only proves it can render a `<div>` proves
 * nothing about whether it can drive this app.
 *
 * These pin the two stream behaviours T-017 must inherit rather than reinvent:
 * the card closes its stream on `track.review_required`, and a dropped
 * connection triggers exactly one snapshot per outage (not one per retry).
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
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

describe('T-026 album/playlist note', () => {
  const PLAYLIST = /part of a playlist/i
  const ALBUM = /part of an album/i

  it('shows the playlist note when job.queued carries list_kind=playlist', async () => {
    const es = renderCard()
    es.emit('job.queued', { job_id: 'job-1', url: 'x', list_kind: 'playlist' })
    await waitFor(() => expect(screen.getByText(PLAYLIST)).toBeInTheDocument())
  })

  it('shows the album note when list_kind=album', async () => {
    const es = renderCard()
    es.emit('job.queued', { job_id: 'job-1', url: 'x', list_kind: 'album' })
    await waitFor(() => expect(screen.getByText(ALBUM)).toBeInTheDocument())
  })

  it('stays silent for a bare song (list_kind null)', () => {
    const es = renderCard()
    es.emit('job.queued', { job_id: 'job-1', url: 'x', list_kind: null })
    es.emit('track.downloading', {})
    expect(screen.queryByText(PLAYLIST)).not.toBeInTheDocument()
    expect(screen.queryByText(ALBUM)).not.toBeInTheDocument()
  })

  it('holds the note across a resume job.queued that omits the flag (monotonic)', async () => {
    const es = renderCard()
    es.emit('job.queued', { job_id: 'job-1', url: 'x', list_kind: 'playlist' })
    await waitFor(() => expect(screen.getByText(PLAYLIST)).toBeInTheDocument())
    // Belt-and-braces: the server now rides list_kind on the resume-reopen too, but a
    // frame that somehow omits it must not clear an already-shown note.
    es.emit('job.queued', { job_id: 'job-1', url: 'x' })
    expect(screen.getByText(PLAYLIST)).toBeInTheDocument()
  })
})

describe('stream lifecycle T-017 must not break', () => {
  it('closes the stream on track.review_required', async () => {
    const es = renderCard()
    es.emit('track.review_required', { review_id: 'rev-1' })
    await waitFor(() => expect(es.closed).toBe(true))
  })

  it('renders the review panel from the stream payload', async () => {
    const es = renderCard()
    es.emit('track.review_required', PARKED)
    await waitFor(() => expect(screen.getByText('Outro')).toBeInTheDocument())
    // From the SSE event alone — no GET /api/reviews round-trip for a weak match.
    expect(screen.getByRole('button', { name: /accept/i })).toBeInTheDocument()
  })

  it('re-hydrates the review panel from a snapshot when the stream never delivered it (restart)', async () => {
    // A process restart wipes the in-memory channel, so the fresh stream never
    // replays track.review_required — `review` stays null. The snapshot says the job
    // is parked; the card must fetch the row and render the panel, not a dead note.
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const url = String(input)
      if (url.includes('/api/reviews/'))
        return Promise.resolve(
          jsonResponse({
            review_id: 'rev-1',
            job_id: 'job-1',
            query: 'nines outro',
            rec: 'low',
            candidates: [{ candidate_id: 'rec-A', title: 'Outro', artist: 'Nines', score: 0.46 }],
          }),
        )
      if (url.includes('/api/jobs/'))
        return Promise.resolve(
          jsonResponse({ job_id: 'job-1', status: 'review', review_id: 'rev-1' }),
        )
      throw new Error(`unexpected fetch: ${url}`)
    })

    const es = renderCard()
    es.fail() // stream drops with no terminal event delivered
    await waitFor(() => expect(screen.getByText('Outro')).toBeInTheDocument())
    expect(screen.getByRole('button', { name: /accept/i })).toBeInTheDocument()
  })

  it('recovers the landing receipt from the snapshot when track.done was lost (T-020)', async () => {
    // The song landed while the stream was down and the SSE channel is gone, so
    // track.done never arrives. The durable snapshot carries path + tags; the card
    // must show *where the song went*, not a bare "Done".
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const url = String(input)
      if (url.includes('/api/jobs/'))
        return Promise.resolve(
          jsonResponse({
            job_id: 'job-1',
            status: 'done',
            path: '/mnt/c/Users/aj_am/Music/CleanMuzik/Band/Song.mp3',
            tags: { title: 'Song', artist: 'Band', genre: 'Rock', has_art: true },
          }),
        )
      throw new Error(`unexpected fetch: ${url}`)
    })

    const es = renderCard()
    es.fail() // stream drops after the song landed, with no track.done delivered
    await waitFor(() =>
      expect(
        screen.getByText('/mnt/c/Users/aj_am/Music/CleanMuzik/Band/Song.mp3'),
      ).toBeInTheDocument(),
    )
    expect(screen.getByText('Rock')).toBeInTheDocument()
    expect(screen.getByText('Art')).toBeInTheDocument()
  })

  it('recovers when a restart outlasts the first reconnect check (T-020)', async () => {
    // The failure a browser surfaced: the stream drops, the first snapshot check runs
    // while the backend is still down (no answer), then the backend returns with the
    // job already terminal (empty replay, no event). A latch that counted the failed
    // check would freeze the card on its last stage forever; the answered-only latch
    // must let a later retry recover.
    let jobCalls = 0
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const url = String(input)
      if (url.includes('/api/jobs/')) {
        jobCalls += 1
        // First check: backend is down — fetch rejects (→ ApiError status 0, transient).
        if (jobCalls === 1) return Promise.reject(new TypeError('backend down'))
        // Backend back: the orphaned job was reconciled to `error`.
        return Promise.resolve(jsonResponse({ job_id: 'job-1', status: 'error' }))
      }
      throw new Error(`unexpected fetch: ${url}`)
    })

    const es = renderCard()
    es.emit('track.identifying', {}) // card is mid-job when the stream drops
    es.fail() // outage begins; the one check runs while the backend is down
    await waitFor(() => expect(jobCalls).toBe(1))
    await Promise.resolve() // let checkOnce's transient catch clear the latch
    es.fail() // EventSource's next retry — backend is back now
    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent(/failed/i),
    )
    // Recovered honestly, not frozen on "Identifying" and not falsely "detached".
    expect(screen.queryByText(/no longer exists/i)).not.toBeInTheDocument()
  })

  it('shows a bare Done with no receipt on an event-less duplicate-skip finish (T-020)', async () => {
    // A duplicate skip finishes "done" with nothing landed: the snapshot omits
    // path/tags, and the card must not invent a blank landing line.
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const url = String(input)
      if (url.includes('/api/jobs/'))
        return Promise.resolve(jsonResponse({ job_id: 'job-1', status: 'done' }))
      throw new Error(`unexpected fetch: ${url}`)
    })

    const es = renderCard()
    es.fail()
    await waitFor(() => expect(screen.getByText('Done')).toBeInTheDocument())
    expect(screen.queryByTitle(/\.mp3$/)).not.toBeInTheDocument()
  })

  it('re-subscribes on resolve with a fresh stream that keeps the reconcile fallback', async () => {
    // POST /resolve → ok; the resume then settles via the snapshot (a reject-style
    // branch emits no terminal event, so stream-close + GET /api/jobs is the signal).
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const url = String(input)
      if (url.includes('/resolve')) return Promise.resolve(jsonResponse({ ok: true }))
      if (url.includes('/api/jobs/'))
        return Promise.resolve(jsonResponse({ job_id: 'job-1', status: 'done' }))
      throw new Error(`unexpected fetch: ${url}`)
    })

    const es1 = renderCard()
    es1.emit('track.review_required', PARKED)
    await waitFor(() => expect(es1.closed).toBe(true))

    fireEvent.click(await screen.findByRole('button', { name: /accept/i }))

    // A FRESH EventSource opens for the resume episode — not a reused/naive stream.
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(2))
    const es2 = FakeEventSource.latest()
    expect(es2.url).toBe('/api/jobs/job-1/events')

    // The resume emits no terminal event (reject/keep_existing shape); the fresh
    // stream must still settle via the one-shot snapshot rather than loop forever.
    es2.fail()
    await waitFor(() => expect(screen.getByText('Done')).toBeInTheDocument())
  })

  it('re-parks a failed resume into a usable panel, not a dead one (T-029)', async () => {
    // A resume that fails on the releasable path re-emits track.review_required for the
    // SAME review, with id-only candidates (the rich rows died with the failed resolve).
    // The panel that just fired the (failed) pick has `submitting` latched true; keying
    // it by review id + epoch remounts it, clearing the latch. And because the re-park
    // candidates are id-only, the card re-hydrates the rich rows via GET /api/reviews/{id}
    // (finding #1) — otherwise the retry screen shows blank choices.
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const url = String(input)
      if (url.includes('/resolve')) return Promise.resolve(jsonResponse({ ok: true }))
      if (url.includes('/api/reviews/'))
        return Promise.resolve(
          jsonResponse({
            review_id: 'rev-1',
            job_id: 'job-1',
            query: 'nines outro',
            rec: 'low',
            candidates: [{ candidate_id: 'rec-A', title: 'Outro (hydrated)', artist: 'Nines', score: 0.46 }],
            last_error: "That match couldn't be applied — the recording no longer resolves.",
          }),
        )
      if (url.includes('/api/jobs/'))
        return Promise.resolve(jsonResponse({ job_id: 'job-1', status: 'review', review_id: 'rev-1' }))
      throw new Error(`unexpected fetch: ${url}`)
    })

    const es1 = renderCard()
    es1.emit('track.review_required', PARKED)
    await waitFor(() => expect(es1.closed).toBe(true))

    fireEvent.click(await screen.findByRole('button', { name: /accept/i }))
    // The pick is in flight: the panel latches `submitting`.
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /resolving/i })).toBeDisabled(),
    )

    // The resume fails and re-parks the same review — id-only candidates + the reason.
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(2))
    FakeEventSource.latest().emit('track.review_required', {
      review_id: 'rev-1',
      rec: 'low',
      query: 'nines outro',
      candidates: [{ candidate_id: 'rec-A', title: null, artist: null, score: null }],
      message: "That match couldn't be applied — the recording no longer resolves.",
    })

    // The panel is usable again — remounted, latch cleared — says why, AND the id-only
    // candidate has been upgraded to its real title via re-hydration (not left blank).
    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent(/no longer resolves/i),
    )
    expect(screen.getByRole('button', { name: /accept/i })).toBeEnabled()
    await waitFor(() => expect(screen.getByText('Outro (hydrated)')).toBeInTheDocument())
  })

  it('recovers the re-park reason from the row when the live event was missed (T-029 #2)', async () => {
    // The failure `message` rides only the live SSE frame. If the card missed it (a
    // stream drop during the resume episode), it re-hydrates via GET /api/reviews/{id},
    // which carries the persisted `last_error` — so the owner still learns why.
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const url = String(input)
      if (url.includes('/api/reviews/'))
        return Promise.resolve(
          jsonResponse({
            review_id: 'rev-1',
            job_id: 'job-1',
            query: 'nines outro',
            rec: 'low',
            candidates: [{ candidate_id: 'rec-A', title: 'Outro', artist: 'Nines', score: 0.46 }],
            last_error: 'That match could not be applied — musicbrainz was down.',
          }),
        )
      if (url.includes('/api/jobs/'))
        return Promise.resolve(jsonResponse({ job_id: 'job-1', status: 'review', review_id: 'rev-1' }))
      throw new Error(`unexpected fetch: ${url}`)
    })

    const es = renderCard()
    es.fail() // the resume-episode stream drops before the re-park event is seen
    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent(/musicbrainz was down/i),
    )
  })

  it('re-enables the panel after a failed pick recovers via the reconnect fallback (T-029 #4)', async () => {
    // The live re-park event can be MISSED: the resume stream drops before it arrives.
    // The card falls back to GET /api/jobs → status `review` → GET /api/reviews/{id}.
    // That fallback must REMOUNT the panel — otherwise the `submitting` latch from the
    // failed pick stays set, every button is dead, and with the stream closed nothing
    // re-enables them. Distinct from the live-re-park test above: here es2 FAILS rather
    // than delivering the event, and the prior Accept click is the load-bearing setup.
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const url = String(input)
      if (url.includes('/resolve')) return Promise.resolve(jsonResponse({ ok: true }))
      if (url.includes('/api/reviews/'))
        return Promise.resolve(
          jsonResponse({
            review_id: 'rev-1',
            job_id: 'job-1',
            query: 'nines outro',
            rec: 'low',
            candidates: [{ candidate_id: 'rec-A', title: 'Outro', artist: 'Nines', score: 0.46 }],
            last_error: "That match couldn't be applied — the recording no longer resolves.",
          }),
        )
      if (url.includes('/api/jobs/'))
        return Promise.resolve(jsonResponse({ job_id: 'job-1', status: 'review', review_id: 'rev-1' }))
      throw new Error(`unexpected fetch: ${url}`)
    })

    const es1 = renderCard()
    es1.emit('track.review_required', PARKED)
    await waitFor(() => expect(es1.closed).toBe(true))

    fireEvent.click(await screen.findByRole('button', { name: /accept/i }))
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /resolving/i })).toBeDisabled(),
    )

    // The resume episode's stream DROPS before any re-park event — the fallback path.
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(2))
    FakeEventSource.latest().fail()

    // Recovered through GET /api/reviews: the reason shows AND the buttons live again.
    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent(/no longer resolves/i),
    )
    expect(screen.getByRole('button', { name: /accept/i })).toBeEnabled()
  })

  it('keeps the prior candidates instead of flashing blank rows on a live re-park (T-029 #7)', async () => {
    // A re-park carries id-only candidates (title/artist null); the rich rows come from
    // GET /api/reviews. Rather than flash "Unknown title" rows — or persist them if the
    // hydrate is slow/failing — the panel keeps the candidates already on screen until
    // the refresh lands. Here the hydrate FAILS, so the id-only rows would otherwise
    // remain; the assertion is that they never appear and the prior row stays.
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const url = String(input)
      if (url.includes('/resolve')) return Promise.resolve(jsonResponse({ ok: true }))
      if (url.includes('/api/reviews/')) return Promise.reject(new Error('hydrate failed'))
      if (url.includes('/api/jobs/'))
        return Promise.resolve(jsonResponse({ job_id: 'job-1', status: 'review', review_id: 'rev-1' }))
      throw new Error(`unexpected fetch: ${url}`)
    })

    const es1 = renderCard()
    es1.emit('track.review_required', PARKED)
    await waitFor(() => expect(screen.getByText('Outro')).toBeInTheDocument())
    await waitFor(() => expect(es1.closed).toBe(true))
    fireEvent.click(await screen.findByRole('button', { name: /accept/i }))

    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(2))
    FakeEventSource.latest().emit('track.review_required', {
      review_id: 'rev-1',
      rec: 'low',
      query: 'nines outro',
      candidates: [{ candidate_id: 'rec-A', title: null, artist: null, score: null }],
      message: "That match couldn't be applied — please pick again.",
    })

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent(/pick again/i),
    )
    // Never a blank id-only row: the prior candidate stays visible through the re-park.
    expect(screen.queryByText('Unknown title')).not.toBeInTheDocument()
    expect(screen.getByText('Outro')).toBeInTheDocument()
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
