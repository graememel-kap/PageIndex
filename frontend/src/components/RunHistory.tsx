import type { JobSummary } from '../types'

type RunHistoryProps = {
  jobs: JobSummary[]
  selectedJobId: string | null
  onSelect: (jobId: string) => void
}

function formatDate(value: string): string {
  const date = new Date(value)
  return date.toLocaleString()
}

export function RunHistory({ jobs, selectedJobId, onSelect }: RunHistoryProps) {
  return (
    <div className="history-pane">
      <div className="section-header">
        <h2>Run History</h2>
      </div>
      <div className="history-list">
        {jobs.length === 0 ? (
          <p className="muted">No jobs yet.</p>
        ) : (
          jobs.map((job) => {
            const selected = selectedJobId === job.id
            return (
              <button
                key={job.id}
                className={`history-card ${selected ? 'selected' : ''}`}
                onClick={() => onSelect(job.id)}
                type="button"
              >
                <div className="history-main">
                  <span className="history-file" title={job.filename}>
                    {job.filename}
                  </span>
                  <span className={`status-badge status-${job.status.toLowerCase()}`}>
                    {job.status}
                  </span>
                </div>
                <div className="history-meta">
                  <span>{job.input_type.toUpperCase()}</span>
                  <span>{Math.round(job.progress * 100)}%</span>
                  <span>{formatDate(job.updated_at)}</span>
                </div>
              </button>
            )
          })
        )}
      </div>
    </div>
  )
}
