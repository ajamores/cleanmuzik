// Thin client for the CleanMuzik backend (spec §6). Same-origin: the Vite dev
// server proxies /api -> http://localhost:8000 (see vite.config.ts).

/** The acquire-intent the dial sends (ADR-029). `single`/`playlist` are wired; `multi`
 *  is reserved geometry the backend refuses, so the dial never actually submits it. */
export type AcquireIntent = 'single' | 'playlist'

/** `POST /api/jobs` answers one of two shapes: a single-song job (the R1 shape,
 *  byte-for-byte) or an expanded batch. The caller discriminates on the key present —
 *  `job_id` vs `playlist_id` — which is why they're a union, not one optional-laden type. */
export type CreateJobResponse =
  | { job_id: string }
  | { playlist_id: string; job_ids: string[] }

/** Narrow the union at the call site without leaking the shape check everywhere. */
export function isBatchResponse(
  r: CreateJobResponse,
): r is { playlist_id: string; job_ids: string[] } {
  return 'playlist_id' in r
}

/** An HTTP error carrying the server's status and a human-readable message. */
export class ApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

/**
 * POST /api/jobs — create a job for one YouTube song URL.
 *
 * On a non-2xx response we surface the server's own `detail` string when there
 * is one (FastAPI's error shape). The 422 playlist rejection and the
 * missing-url 422 both arrive this way, so the caller can show the real copy
 * rather than inventing its own.
 */
export async function createJob(
  url: string,
  intent?: AcquireIntent,
): Promise<CreateJobResponse> {
  // Intent rides only when set — an absent `intent` leaves the backend on its R1 shape
  // inference (a bare song still lands single), so the dial adds nothing to the wire for
  // the default path. `single`/`playlist` are the only values the dial submits; `multi`
  // is an inert stop that never reaches here (the backend would 422 it anyway).
  return postJson<CreateJobResponse>('/api/jobs', intent ? { url, intent } : { url })
}

/**
 * `GET /api/playlists/{playlist_id}` — a batch's durable reconnect snapshot (T-312).
 *
 * The aggregate tally + terminal state rebuilt purely from SQLite, with the playlist's
 * durable identity alongside. The batch card reads this on cold load / after a restart
 * (when the SSE replay buffer is empty), then re-subscribes to the batch stream for
 * anything still in flight. Aggregate-only by decision (ADR-027 seam 5): no per-track
 * rows — those come live off the stream, and the parked ones from the review inbox.
 */
export async function getPlaylistState(playlistId: string): Promise<PlaylistSnapshot> {
  return request<PlaylistSnapshot>(`/api/playlists/${encodeURIComponent(playlistId)}`)
}

/** The derived batch state carried on both `batch.progress` and the snapshot (T-305/T-312).
 *  `never_started` (T-310): a crash between the row-upsert and the enqueue left `total===0`;
 *  the card renders it as "never got off the ground", never a green "done". */
export type BatchState = 'running' | 'waiting_on_you' | 'done' | 'never_started'

/** The aggregate tally shared by the `batch.progress` event and the reconnect snapshot.
 *  Every count is durable (recomputed from SQLite each emit), so it is correct after a
 *  restart — unlike the per-track rows, which the card accumulates live off the stream. */
export interface BatchProgress {
  playlist_id: string
  landed: number
  in_review: number
  failed: number
  skipped: number
  queued: number
  total: number
  state: BatchState
}

/** `GET /api/playlists/{id}` — the progress tally plus the playlist's durable identity.
 *  `title` lets the card render its header on a cold load, when the live `batch.queued`
 *  event (which also carries it) has no replay buffer to arrive from. */
export interface PlaylistSnapshot extends BatchProgress {
  title: string
  youtube_playlist_id: string
  jellyfin_playlist_id: string | null
  created_at: string
}

/** `GET /api/jobs/{id}` — the job status snapshot (spec §6). */
export interface JobSnapshot {
  job_id: string
  url: string
  status: string
  created_at?: string
  /** Live only: absent once the job leaves the worker's registry / after a restart. */
  stage?: string
  review_id?: string
  error?: string
  // No landing path/tags: the landing detail rides the terminal SSE event, not this
  // snapshot (ADR-015). The card recovers it from the replayed `track.done` / `track.error`.
}

/**
 * GET /api/jobs/{job_id} — spec §6's "reconnect / SSE fallback" snapshot.
 *
 * Used *once*, when the SSE stream dies without a terminal event — never on a
 * timer. Progress is SSE, not polling (ADR); this only answers the question SSE
 * structurally can't: an EventSource cannot read a status code, so a 404, a dead
 * backend, and a job that finished with no event (the duplicate skip) all look
 * identical from the stream. The snapshot tells them apart.
 */
export async function getJob(jobId: string): Promise<JobSnapshot> {
  return request<JobSnapshot>(`/api/jobs/${encodeURIComponent(jobId)}`)
}

// --- reviews (spec §6, T-017) -----------------------------------------------

/**
 * A weak-match candidate. **No album/year/art** — a candidate is a MusicBrainz
 * *recording* and those are release properties (ADR-010), so they aren't in the
 * contract. `score` is beets' tag distance against this download — the
 * discriminator the owner picks on, `null` only for a pre-T-028 row.
 */
export interface ReviewCandidate {
  candidate_id: string | null
  title: string | null
  artist: string | null
  score: number | null
}

/** A copy already in the library, in a duplicate review (read off the beets item). */
export interface DuplicateExisting {
  path: string | null
  bitrate: number
  title: string | null
  artist: string | null
  album: string | null
}

/** The just-downloaded copy. `exists: false` is real, not an error: a temp-dir
 *  sweep can take the staging file while the row survives (the landing branches
 *  will 409, so the owner must see it). */
export interface DuplicateIncoming {
  exists: boolean
  bitrate: number
  title: string | null
  artist: string | null
}

export interface DuplicateDetail {
  existing: DuplicateExisting[]
  incoming: DuplicateIncoming
}

/**
 * What the machine *searched with*, for the re-search form to pre-fill (T-103).
 *
 * `title` is the normalized query the park actually used; `artist` is the staging
 * file's embedded artist tag (yt-dlp's `--embed-metadata`). **Neither is a claim of
 * correctness** — showing the owner what was searched is how the mistake becomes
 * visible (ADR-020). On the real fixtures `artist` has been the uploader's channel
 * name and `title` has held both fields in one string, so the form must let the owner
 * edit freely rather than trust these.
 *
 * Null on a duplicate row, which asks a different question.
 */
export interface ReviewGuess {
  artist: string | null
  title: string | null
}

/** One row of `GET /api/reviews`. `rec === "duplicate"` selects the keep-which
 *  branch and carries `duplicate`; every other `rec` is a weak match with
 *  `candidates`. */
export interface ReviewRow {
  review_id: string
  job_id: string
  /** The batch this park belongs to, and the track's index in it (T-310). `null` on a
   *  single-song R1 park — the switch App partitions on: a null-`playlist_id` review is a
   *  top-level inbox row, a non-null one belongs to its batch card's "needs you" bucket
   *  (same review, same resolve seam, contextual place). `position` labels the row. */
  playlist_id?: string | null
  position?: number | null
  query: string
  rec: string
  candidates: ReviewCandidate[]
  duplicate?: DuplicateDetail
  guess?: ReviewGuess | null
  /** Why the last resolve attempt re-parked this row (T-029), or null on a first
   *  park. Persisted server-side so it survives the reconnect/reload this endpoint
   *  recovers from — the live SSE `message` is gone by then. */
  last_error?: string | null
  /** The reconcile Verdict's one-line "why it parked" (T-206/T-207). `null` on the
   *  R1/degrade park (no adjudicator ran) — the card shows no park story then. */
  reason?: string | null
  /** The senses that disagreed, one terse note each — `"fp: absent"`,
   *  `"yt: Frank Ocean ≠ Coldplay"` (T-206). Non-empty ⇒ a Verdict ranked the
   *  candidates; `[]` on the R1/degrade park or an adjudication that named none. The
   *  server sends `[]` not null, but the type mirrors `reason`'s nullability and the
   *  consumers guard for it (`?? []`) so a null can never render as a broken row. */
  contradictions?: string[] | null
}

/**
 * `GET /api/reviews` — the whole parked queue.
 *
 * T-017 hits this **only for a duplicate** review, to get the existing-vs-incoming
 * detail the SSE event can't carry (it needs a library read). A weak match renders
 * straight from the `track.review_required` payload, so it never pays this route's
 * rate-limited per-candidate MusicBrainz re-hydration.
 */
export async function listReviews(): Promise<ReviewRow[]> {
  return request<ReviewRow[]>('/api/reviews')
}

/**
 * `GET /api/reviews/{id}` — one hydrated review, or a 404 `ApiError` if it is gone
 * or already resolved.
 *
 * The narrow read the card falls back to when it has lost the live payload — a
 * stream drop, or a process restart that wiped the SSE channel the candidates rode
 * in on. Unlike {@link listReviews} it costs only this row's hydration, not the
 * whole queue's.
 */
export async function getReview(reviewId: string): Promise<ReviewRow> {
  return request<ReviewRow>(`/api/reviews/${encodeURIComponent(reviewId)}`)
}

/** What `POST /api/reviews/{id}/search` answers with. The terms are echoed back
 *  **trimmed** — the exact strings that went to MusicBrainz, not the raw field values —
 *  so the card's "searched again for" line reports what was really asked rather than
 *  what was typed. (It does not survive a reload; a reload unmounts the panel and the
 *  results reset to the parked list.) An empty `candidates` is a real answer —
 *  "MusicBrainz doesn't have this" — and the card renders exits from it, never a dead
 *  panel (ADR-020). */
export interface ReviewSearchResult {
  artist: string
  title: string
  candidates: ReviewCandidate[]
}

/**
 * `POST /api/reviews/{id}/search` — re-query MusicBrainz with the owner's corrected
 * terms (ADR-020 exit 1).
 *
 * A **read**: it stores nothing and leaves the row `pending`, so it can be repeated as
 * many times as it takes. The recording the owner then picks goes back through
 * {@link resolveReview}, which since ADR-020 accepts a recording that was never in the
 * parked candidate list — that relaxation is what makes this endpoint useful.
 */
export async function searchReview(
  reviewId: string,
  terms: { artist: string; title: string },
): Promise<ReviewSearchResult> {
  return postJson<ReviewSearchResult>(
    `/api/reviews/${encodeURIComponent(reviewId)}/search`,
    terms,
  )
}

/** The three resolve body shapes (spec §6), keyed by the review's `rec`. A weak
 *  match sends a candidate_id, `"reject"`, or `"keep_untagged"` (ADR-020 exit 2);
 *  a duplicate sends one of the three keep-which choices. */
export type ResolveBody =
  | { choice: string }
  | { choice: 'keep_existing' }
  | { choice: 'replace' }
  | { choice: 'keep_both'; suffix: string }
  | { choice: 'keep_untagged'; artist: string; title: string; album?: string; year?: number }

/**
 * `POST /api/reviews/{id}/resolve` — apply the owner's decision and resume the
 * import. Returns as soon as the work is handed to the worker; by then the job's
 * SSE channel is reopened, so the caller can open a fresh EventSource immediately.
 */
export async function resolveReview(
  reviewId: string,
  body: ResolveBody,
): Promise<{ ok: boolean }> {
  return postJson<{ ok: boolean }>(
    `/api/reviews/${encodeURIComponent(reviewId)}/resolve`,
    body,
  )
}

/** The request contract every POST shares. `request` owns the ERROR contract; this
 *  owns the shape of the call, so the JSON content-type is stated once rather than at
 *  each call site (where a typo surfaces as a puzzling FastAPI 422 at runtime). */
async function postJson<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

/** Fetch + the error contract every route shares: an ApiError with the server's
 *  own `detail` when there is one, a reachability hint when there isn't. */
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(path, init)
  } catch {
    // fetch REJECTS (not resolves non-ok) when no response is reached at all —
    // backend down, no dev proxy, DNS. readErrorDetail needs a Response, so the
    // friendly guidance has to be raised here rather than from the !ok branch.
    throw new ApiError('Could not reach the backend. Is it running?', 0)
  }

  if (!res.ok) {
    throw new ApiError(await readErrorDetail(res), res.status)
  }

  try {
    return (await res.json()) as T
  } catch {
    // These routes always return JSON, so a 2xx with an empty/non-JSON body
    // shouldn't happen — but guard it to a clean message rather than let a raw
    // "Unexpected end of JSON input" reach the user.
    throw new ApiError('Unexpected response from the backend.', res.status)
  }
}

/** Pull a readable message out of an error response, falling back gracefully. */
async function readErrorDetail(res: Response): Promise<string> {
  try {
    const body: unknown = await res.json()
    if (
      body &&
      typeof body === 'object' &&
      'detail' in body &&
      typeof (body as { detail: unknown }).detail === 'string'
    ) {
      return (body as { detail: string }).detail
    }
  } catch {
    // Non-JSON body (e.g. a proxy/500 HTML page) — fall through.
  }
  return `Request failed (${res.status}). Is the backend running?`
}
