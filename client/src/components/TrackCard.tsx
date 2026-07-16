import { useState } from 'react'
import './TrackCard.css'

/**
 * The stages a track moves through (spec §4 / SSE event names in §6). The shell
 * (T-015) only ever renders `queued`; the full set is declared here so T-016
 * can drive the card off the live stream without redefining the model.
 */
export type Stage =
  | 'queued'
  | 'downloading'
  | 'transcoding'
  | 'identifying'
  | 'review_required'
  | 'tagging'
  | 'done'
  | 'error'

const STAGE_LABEL: Record<Stage, string> = {
  queued: 'Queued',
  downloading: 'Downloading',
  transcoding: 'Transcoding',
  identifying: 'Identifying',
  review_required: 'Needs review',
  tagging: 'Tagging',
  done: 'Done',
  error: 'Error',
}

interface TrackCardProps {
  jobId: string
  url: string
}

/**
 * One track's live card, keyed by job id.
 *
 * T-015 SCOPE: this is the empty placeholder — it shows the job id, the source
 * URL, and a "Queued" state, nothing more.
 *
 * T-016 SEAM: this component owns the `stage` state below. The next ticket adds
 * a `useEffect` here that opens `new EventSource(`/api/jobs/${jobId}/events`)`,
 * maps each SSE event name to a `Stage` (STAGE_LABEL already covers them), calls
 * `setStage(...)`, and closes the stream on `done`/`error` + on unmount. No
 * other file needs to change for that: props and the stage model are the seam.
 */
export function TrackCard({ jobId, url }: TrackCardProps) {
  const [stage] = useState<Stage>('queued')

  return (
    <article className="track-card" data-stage={stage}>
      <div className="track-card__head">
        <span className="track-card__status">{STAGE_LABEL[stage]}</span>
        <span className="track-card__job" title={`Job ${jobId}`}>
          {jobId}
        </span>
      </div>
      <p className="track-card__url" title={url}>
        {url}
      </p>
    </article>
  )
}
