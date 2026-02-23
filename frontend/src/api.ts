import type { ActivityItem, JobDetail, JobResult, JobSummary } from './types'

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8000'

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init)
  if (!response.ok) {
    let detail = response.statusText
    try {
      const body = await response.json()
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body)
    } catch {
      // ignore JSON parse failure
    }
    throw new Error(detail)
  }
  return (await response.json()) as T
}

export function listJobs() {
  return apiFetch<JobSummary[]>('/api/jobs')
}

export function getJob(jobId: string) {
  return apiFetch<JobDetail>(`/api/jobs/${jobId}`)
}

export function createJob(formData: FormData) {
  return apiFetch<JobSummary>('/api/jobs', {
    method: 'POST',
    body: formData,
  })
}

export function cancelJob(jobId: string) {
  return apiFetch<JobDetail>(`/api/jobs/${jobId}/cancel`, {
    method: 'POST',
  })
}

export function getJobResult(jobId: string) {
  return apiFetch<JobResult>(`/api/jobs/${jobId}/result`)
}

type EventHandlers = {
  onUpdate: (job: JobDetail) => void
  onActivity: (activity: ActivityItem) => void
  onError: (error: string) => void
  onCompleted: (jobId: string) => void
  onConnectionError: () => void
}

export function openJobEvents(jobId: string, handlers: EventHandlers): EventSource {
  const stream = new EventSource(`${API_BASE}/api/jobs/${jobId}/events`)

  stream.addEventListener('job.update', (event) => {
    const payload = JSON.parse((event as MessageEvent).data) as { job: JobDetail }
    handlers.onUpdate(payload.job)
  })

  stream.addEventListener('job.activity', (event) => {
    const payload = JSON.parse((event as MessageEvent).data) as {
      job_id: string
      activity: ActivityItem
    }
    handlers.onActivity(payload.activity)
  })

  stream.addEventListener('job.error', (event) => {
    const payload = JSON.parse((event as MessageEvent).data) as { error: string }
    handlers.onError(payload.error)
  })

  stream.addEventListener('job.completed', (event) => {
    const payload = JSON.parse((event as MessageEvent).data) as { job_id: string }
    handlers.onCompleted(payload.job_id)
  })

  stream.onerror = () => {
    handlers.onConnectionError()
  }

  return stream
}
