/**
 * BatchCard — the one aggregate card for a playlist batch (T-310).
 *
 * The card reads two sources in two lanes, and these tests pin the disciplines the
 * signed-off design gate is about, not the pixels:
 *
 *   - the durable tally + terminal state (cold-load snapshot AND live `batch.progress`);
 *   - per-track rows accumulated live off the stamped `track.*` stream;
 *   - the gate's warmth rules: parked > 0 ⇒ "waiting on you" not "done"; total 0 ⇒
 *     "never started" not "done"; a failure reads "gone", never an alarm; album art on
 *     landed rows ONLY; and the "needs you" bucket sourced from the (durable) review inbox.
 */

import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import App from '../App'
import { BatchCard } from './BatchCard'
import type { PlaylistSnapshot, ReviewRow } from '../api'
import { FakeEventSource, installFakeEventSource } from '../test/fakeEventSource'

const PID = 'pl-1'

function snap(over: Partial<PlaylistSnapshot>): PlaylistSnapshot {
  return {
    playlist_id: PID,
    title: 'August 2026 — night drives',
    landed: 0,
    in_review: 0,
    failed: 0,
    skipped: 0,
    queued: 0,
    total: 0,
    state: 'running',
    youtube_playlist_id: 'PL8u',
    jellyfin_playlist_id: null,
    created_at: '2026-08-19T00:00:00Z',
    ...over,
  }
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

let snapshotData: PlaylistSnapshot

beforeEach(() => {
  installFakeEventSource()
  vi.restoreAllMocks()
  snapshotData = snap({ state: 'running', total: 50, queued: 49, landed: 1 })
  vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    if (/\/api\/playlists\/[^/]+$/.test(url) && method === 'GET') {
      return Promise.resolve(jsonResponse(snapshotData))
    }
    if (url.includes('/resolve')) return Promise.resolve(jsonResponse({ ok: true }))
    if (/\/api\/reviews\/[^/]+$/.test(url)) return Promise.resolve(jsonResponse(snapshotData))
    throw new Error(`unexpected fetch: ${method} ${url}`)
  })
})

function renderCard(reviews: ReviewRow[] = []) {
  return render(
    <BatchCard
      playlistId={PID}
      reviews={reviews}
      onReviewResolved={vi.fn()}
      onReviewParked={vi.fn()}
    />,
  )
}

/** The batch's live stream — the card only opens it AFTER the cold-load snapshot resolves
 *  and reports a live (running / waiting_on_you) batch, so wait for construction. */
async function getStream(): Promise<FakeEventSource> {
  await waitFor(() => expect(FakeEventSource.instances.length).toBeGreaterThan(0))
  return FakeEventSource.latest()
}

describe('BatchCard — cold load from the durable snapshot', () => {
  it('renders header, tally and pill from the snapshot alone', async () => {
    snapshotData = snap({ state: 'waiting_on_you', total: 50, landed: 43, in_review: 4, failed: 3 })
    renderCard()
    await waitFor(() =>
      expect(screen.getByText('August 2026 — night drives')).toBeInTheDocument(),
    )
    // Parked > 0 ⇒ "waiting on you", NOT "done" (US22).
    expect(screen.getByText('Waiting on you')).toBeInTheDocument()
    expect(screen.queryByText('Done')).not.toBeInTheDocument()
    const tally = document.querySelector('.tally')!
    expect(within(tally as HTMLElement).getByText('43')).toBeInTheDocument()
    expect(within(tally as HTMLElement).getByText('4')).toBeInTheDocument()
  })

  it('an empty batch reads "never started", never a green done (screen 07)', async () => {
    snapshotData = snap({ state: 'never_started', total: 0 })
    renderCard()
    await waitFor(() => expect(screen.getByText('Never started')).toBeInTheDocument())
    expect(screen.getByText(/nothing got queued/i)).toBeInTheDocument()
    expect(screen.queryByText('Done')).not.toBeInTheDocument()
    // No phantom outcome buckets or rows over a batch that never ran (the tally cells,
    // which always carry the "Landed"/"Gone" labels, are not buckets).
    expect(document.querySelector('.batch__bucket--needs')).toBeNull()
    expect(document.querySelector('.row')).toBeNull()
  })

  it('surfaces a clear message when the batch is gone from the server', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse({ detail: 'no' }, 404))
    renderCard()
    await waitFor(() =>
      expect(screen.getByText(/no longer exists on the server/i)).toBeInTheDocument(),
    )
  })
})

describe('BatchCard — live stream', () => {
  it('updates the tally + pill from batch.progress', async () => {
    renderCard()
    await waitFor(() => expect(screen.getByText('Processing')).toBeInTheDocument())
    const es = await getStream()
    es.emit('batch.progress', {
      playlist_id: PID,
      landed: 28,
      in_review: 4,
      failed: 2,
      skipped: 0,
      queued: 16,
      total: 50,
      state: 'running',
    })
    await waitFor(() => expect(screen.getByText('34 of 50 processed')).toBeInTheDocument())
  })

  it('a stamped track.done adds a landed row WITH art; track.error adds a muted "gone" row', async () => {
    const { container } = renderCard()
    await waitFor(() => expect(screen.getByText('Processing')).toBeInTheDocument())
    const es = await getStream()
    // Make the buckets appear: two landed, one gone.
    es.emit('batch.progress', {
      playlist_id: PID, landed: 1, in_review: 0, failed: 1, skipped: 0, queued: 0, total: 2, state: 'done',
    })
    es.emit('track.done', {
      job_id: 'j1', position: 1, path: '/music/M83/…',
      tags: { title: 'Midnight City', artist: 'M83', album: 'Hurry Up', year: 2011, genre: 'Electronic', has_art: true },
    })
    es.emit('track.error', {
      job_id: 'j2', position: 7, stage: 'download', message: 'the uploader deleted it',
    })
    await waitFor(() => expect(screen.getByText(/Midnight City/)).toBeInTheDocument())
    // Art on the landed row only.
    expect(container.querySelector('.cover-swatch')).not.toBeNull()
    // The gone row is muted "Gone" — never an alarm word. (Scoped to the row, since the
    // tally's failed cell also carries a "Gone" label.)
    const goneRow = container.querySelector('.row--gone')!
    expect(goneRow).not.toBeNull()
    expect(within(goneRow as HTMLElement).getByText('Gone')).toBeInTheDocument()
    expect(screen.getByText(/uploader deleted it/i)).toBeInTheDocument()
    expect(screen.queryByText(/error/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/failed/i)).not.toBeInTheDocument()
  })

  it('a landed track WITHOUT embedded art gets no art placeholder on its row', async () => {
    const { container } = renderCard()
    await waitFor(() => expect(screen.getByText('Processing')).toBeInTheDocument())
    const es = await getStream()
    es.emit('batch.progress', {
      playlist_id: PID, landed: 1, in_review: 0, failed: 0, skipped: 0, queued: 0, total: 1, state: 'done',
    })
    es.emit('track.done', {
      job_id: 'j1', position: 1, path: '/x', tags: { title: 'No Art', artist: 'Nobody', has_art: false },
    })
    await waitFor(() => expect(screen.getByText(/No Art/)).toBeInTheDocument())
    // The landed bucket rendered, but the row asserts no cover it doesn't have.
    expect(container.querySelector('.cover-swatch')).toBeNull()
  })

  it('shows the live strip for the in-flight track and clears it when the track settles', async () => {
    renderCard()
    await waitFor(() => expect(screen.getByText('Processing')).toBeInTheDocument())
    const es = await getStream()
    es.emit('track.identifying', { job_id: 'j5', position: 35 })
    await waitFor(() => expect(screen.getByText(/Now processing/)).toBeInTheDocument())
    expect(screen.getByText(/track 35 of/)).toBeInTheDocument()
    // The track finishes → the live strip clears (sequential; nothing else in flight).
    es.emit('track.done', { job_id: 'j5', position: 35, tags: { title: 'x', has_art: false } })
    await waitFor(() => expect(screen.queryByText(/Now processing/)).not.toBeInTheDocument())
  })

  it('the re-paste voice: settled with skips reads "already here · added"', async () => {
    snapshotData = snap({ state: 'done', total: 48, landed: 3, skipped: 45 })
    renderCard()
    await waitFor(() =>
      expect(screen.getByText(/45 already here · 3 added · nothing wrong/)).toBeInTheDocument(),
    )
    expect(screen.getByText('Added this time')).toBeInTheDocument()
    expect(screen.getByText('Already in your library')).toBeInTheDocument()
  })
})

describe('BatchCard — the "needs you" bucket (from the durable review inbox)', () => {
  const REVIEW: ReviewRow = {
    review_id: 'rev-1',
    job_id: 'j12',
    playlist_id: PID,
    position: 12,
    query: 'teardrop massive attack',
    rec: 'low',
    candidates: [{ candidate_id: 'rec-A', title: 'Teardrop', artist: 'Massive Attack', score: 0.44 }],
  }

  it('hoists parked tracks to the top, scoped to this batch, with the shared resolve seam', async () => {
    renderCard([REVIEW])
    await waitFor(() => expect(screen.getByText('Needs you')).toBeInTheDocument())
    expect(screen.getByText('teardrop massive attack')).toBeInTheDocument()
    expect(screen.getByText(/track 12/)).toBeInTheDocument()
    // Expanding the row reveals the SAME ReviewPanel resolve controls the inbox uses.
    fireEvent.click(screen.getByRole('button', { name: /resolve/i }))
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /accept/i })).toBeInTheDocument(),
    )
  })

  it('resolving a batch review fires the shared onReviewResolved with the member job id', async () => {
    const onReviewResolved = vi.fn()
    render(
      <BatchCard
        playlistId={PID}
        reviews={[REVIEW]}
        onReviewResolved={onReviewResolved}
        onReviewParked={vi.fn()}
      />,
    )
    await waitFor(() => expect(screen.getByText('Needs you')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /resolve/i }))
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /accept/i })).toBeInTheDocument(),
    )
    fireEvent.click(screen.getByRole('button', { name: /accept/i }))
    await waitFor(() => expect(onReviewResolved).toHaveBeenCalledWith('j12'))
  })
})

describe('App wiring — a batch review survives a reload (recovered batch card)', () => {
  const BATCH_REVIEW: ReviewRow = {
    review_id: 'rev-b',
    job_id: 'jb',
    playlist_id: PID,
    position: 12,
    query: 'teardrop massive attack',
    rec: 'low',
    candidates: [{ candidate_id: 'rec-A', title: 'Teardrop', artist: 'Massive Attack', score: 0.44 }],
  }

  it('mounts a batch card from a parked review even with an empty deck (post-reload)', async () => {
    // The reload scenario: `items` starts empty, but the queue has a batch-scoped park.
    // It must NOT vanish — a recovered card mounts and shows it, resolvable, and the
    // top-level inbox does not double it.
    vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      if (url.endsWith('/api/reviews') && method === 'GET') {
        return Promise.resolve(jsonResponse([BATCH_REVIEW]))
      }
      if (/\/api\/playlists\/[^/]+$/.test(url) && method === 'GET') {
        return Promise.resolve(
          jsonResponse(snap({ state: 'waiting_on_you', total: 50, landed: 45, in_review: 1 })),
        )
      }
      if (url.includes('/resolve')) return Promise.resolve(jsonResponse({ ok: true }))
      if (/\/api\/reviews\/[^/]+$/.test(url)) return Promise.resolve(jsonResponse(BATCH_REVIEW))
      throw new Error(`unexpected fetch: ${method} ${url}`)
    })
    render(<App />)
    // The batch card is recovered from the review alone — its header + parked row appear.
    await waitFor(() =>
      expect(screen.getByText('August 2026 — night drives')).toBeInTheDocument(),
    )
    const card = document.querySelector('.batch')!
    expect(within(card as HTMLElement).getByText('teardrop massive attack')).toBeInTheDocument()
    expect(within(card as HTMLElement).getByText('Needs you')).toBeInTheDocument()
    // NOT duplicated into the top-level inbox — one place, not both.
    const inbox = screen.getByRole('region', { name: 'Needs review' })
    expect(within(inbox).queryByText('teardrop massive attack')).not.toBeInTheDocument()
    expect(within(inbox).getByText(/nothing waiting/i)).toBeInTheDocument()
  })
})
