import type { JobDetail, JobStage } from '../types'

const STAGES: JobStage[] = [
  'QUEUED',
  'PARSING_INPUT',
  'TOC_ANALYSIS',
  'INDEX_BUILD',
  'REFINEMENT',
  'SUMMARIZATION',
  'FINALIZING',
  'COMPLETED',
]

type ProgressRailProps = {
  job: JobDetail | null
  onCancel: () => void
  connectionWarning: string | null
}

function stageIndex(stage: JobStage): number {
  return STAGES.indexOf(stage)
}

export function ProgressRail({ job, onCancel, connectionWarning }: ProgressRailProps) {
  const percent = Math.round((job?.progress ?? 0) * 100)
  const lastActivityAt =
    job && job.activity.length > 0
      ? new Date(job.activity[job.activity.length - 1].timestamp).getTime()
      : null
  const staleSeconds =
    job?.status === 'RUNNING' && lastActivityAt
      ? Math.max(0, Math.floor((Date.now() - lastActivityAt) / 1000))
      : 0

  return (
    <div className="progress-pane">
      <div className="section-header sticky-header">
        <h2>Progress</h2>
        {job?.status === 'RUNNING' ? (
          <button className="danger-button" type="button" onClick={onCancel}>
            Cancel Run
          </button>
        ) : null}
      </div>

      {!job ? (
        <p className="muted">Start a run to see live progress and activity.</p>
      ) : (
        <>
          <div className="progress-card">
            <div className="progress-row">
              <span>{job.stage}</span>
              <span>{percent}%</span>
            </div>
            <div className="progress-track">
              <div className="progress-fill" style={{ width: `${percent}%` }} />
            </div>
            {job?.status === 'RUNNING' && staleSeconds >= 90 ? (
              <p className="warning-text">
                No new activity for {staleSeconds}s. The backend may still be waiting on model
                responses.
              </p>
            ) : null}
            {connectionWarning ? <p className="warning-text">{connectionWarning}</p> : null}
            {job.error ? <p className="error-text">{job.error}</p> : null}
          </div>

          <ol className="timeline">
            {STAGES.map((stage) => {
              const current = stageIndex(job.stage)
              const target = stageIndex(stage)
              const status =
                job.status === 'COMPLETED'
                  ? target <= current
                    ? 'done'
                    : 'pending'
                  : target < current
                    ? 'done'
                    : target === current
                      ? 'active'
                      : 'pending'
              return (
                <li key={stage} className={`timeline-item ${status}`}>
                  <span className="timeline-dot" />
                  <span className="timeline-label">{stage.replace('_', ' ')}</span>
                </li>
              )
            })}
          </ol>

          <div className="activity-feed">
            <h3>Activity</h3>
            <div className="activity-list">
              {[...job.activity].reverse().map((entry, idx) => (
                <div className="activity-row" key={`${entry.timestamp}-${idx}`}>
                  <span className="activity-source">{entry.source}</span>
                  <p>{entry.message}</p>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
