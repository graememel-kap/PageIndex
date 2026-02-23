import type {
  ActivityItem,
  ChatAnswerCompleted,
  ChatAnswerDelta,
  ChatMessageCreateResponse,
  ChatRetrievalCompleted,
  ChatRunCompleted,
  ChatRunFailed,
  ChatRunStarted,
  ChatSessionsClearResponse,
  ChatSessionDetail,
  ChatSessionSummary,
  JobDetail,
  JobResult,
  JobSummary,
} from './types'

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8088'

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

export function createChatSession(jobId: string) {
  return apiFetch<ChatSessionSummary>(`/api/jobs/${jobId}/chat/sessions`, {
    method: 'POST',
  })
}

export function listChatSessions(jobId: string) {
  return apiFetch<ChatSessionSummary[]>(`/api/jobs/${jobId}/chat/sessions`)
}

export function getChatSession(sessionId: string) {
  return apiFetch<ChatSessionDetail>(`/api/chat/sessions/${sessionId}`)
}

export function sendChatMessage(sessionId: string, content: string) {
  return apiFetch<ChatMessageCreateResponse>(`/api/chat/sessions/${sessionId}/messages`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ content }),
  })
}

export function clearChatSessions(jobId: string) {
  return apiFetch<ChatSessionsClearResponse>(`/api/jobs/${jobId}/chat/sessions`, {
    method: 'DELETE',
  })
}

export function deleteChatSession(sessionId: string) {
  return apiFetch<ChatSessionsClearResponse>(`/api/chat/sessions/${sessionId}`, {
    method: 'DELETE',
  })
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

type ChatEventHandlers = {
  onRunStarted: (payload: ChatRunStarted) => void
  onRetrievalCompleted: (payload: ChatRetrievalCompleted) => void
  onAnswerDelta: (payload: ChatAnswerDelta) => void
  onAnswerCompleted: (payload: ChatAnswerCompleted) => void
  onRunCompleted: (payload: ChatRunCompleted) => void
  onRunFailed: (payload: ChatRunFailed) => void
  onConnectionError: () => void
}

export function openChatEvents(
  sessionId: string,
  runId: string,
  handlers: ChatEventHandlers,
): EventSource {
  const stream = new EventSource(
    `${API_BASE}/api/chat/sessions/${sessionId}/events?run_id=${encodeURIComponent(runId)}`,
  )

  stream.addEventListener('chat.run.started', (event) => {
    handlers.onRunStarted(JSON.parse((event as MessageEvent).data) as ChatRunStarted)
  })

  stream.addEventListener('chat.retrieval.completed', (event) => {
    handlers.onRetrievalCompleted(
      JSON.parse((event as MessageEvent).data) as ChatRetrievalCompleted,
    )
  })

  stream.addEventListener('chat.answer.delta', (event) => {
    handlers.onAnswerDelta(JSON.parse((event as MessageEvent).data) as ChatAnswerDelta)
  })

  stream.addEventListener('chat.answer.completed', (event) => {
    handlers.onAnswerCompleted(
      JSON.parse((event as MessageEvent).data) as ChatAnswerCompleted,
    )
  })

  stream.addEventListener('chat.run.completed', (event) => {
    handlers.onRunCompleted(JSON.parse((event as MessageEvent).data) as ChatRunCompleted)
  })

  stream.addEventListener('chat.run.failed', (event) => {
    handlers.onRunFailed(JSON.parse((event as MessageEvent).data) as ChatRunFailed)
  })

  stream.onerror = () => {
    handlers.onConnectionError()
  }

  return stream
}
