// Thin client for the CleanMuzik backend (spec §6). Same-origin: the Vite dev
// server proxies /api -> http://localhost:8000 (see vite.config.ts).

export interface CreateJobResponse {
  job_id: string
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
export async function createJob(url: string): Promise<CreateJobResponse> {
  let res: Response
  try {
    res = await fetch('/api/jobs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    })
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
    return (await res.json()) as CreateJobResponse
  } catch {
    // The route always returns {job_id}, so a 2xx with an empty/non-JSON body
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
