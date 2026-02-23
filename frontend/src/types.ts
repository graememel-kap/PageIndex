export type JobStatus = 'QUEUED' | 'RUNNING' | 'COMPLETED' | 'FAILED' | 'CANCELLED'

export type JobStage =
  | 'QUEUED'
  | 'PARSING_INPUT'
  | 'TOC_ANALYSIS'
  | 'INDEX_BUILD'
  | 'REFINEMENT'
  | 'SUMMARIZATION'
  | 'FINALIZING'
  | 'COMPLETED'

export type InputType = 'pdf' | 'md'

export interface ActivityItem {
  timestamp: string
  source: 'stdout' | 'stderr' | 'log' | 'system'
  message: string
}

export interface JobSummary {
  id: string
  filename: string
  input_type: InputType
  status: JobStatus
  stage: JobStage
  progress: number
  created_at: string
  updated_at: string
}

export interface JobDetail extends JobSummary {
  options: Record<string, unknown>
  input_path: string
  log_file?: string | null
  result_file?: string | null
  error?: string | null
  stdout_tail: string[]
  activity: ActivityItem[]
  pid?: number | null
}

export interface JobResultNode {
  title: string
  node_id?: string
  summary?: string
  prefix_summary?: string
  start_index?: number
  end_index?: number
  text?: string
  line_num?: number
  nodes?: JobResultNode[]
}

export interface JobResult {
  doc_name: string
  doc_description?: string
  structure: JobResultNode[]
}

export type ChatRole = 'user' | 'assistant' | 'system'
export type ChatRunStatus = 'RUNNING' | 'COMPLETED' | 'FAILED'

export interface NodeCitation {
  node_id: string
  title?: string | null
  start_index?: number | null
  end_index?: number | null
  line_num?: number | null
}

export interface ChatMessage {
  id: string
  role: ChatRole
  content: string
  created_at: string
  citations: NodeCitation[]
}

export interface ChatRun {
  id: string
  status: ChatRunStatus
  user_message_id: string
  assistant_message_id: string
  created_at: string
  updated_at: string
  retrieval_thinking?: string | null
  selected_node_ids: string[]
  error?: string | null
}

export interface ChatSessionSummary {
  id: string
  job_id: string
  title: string
  created_at: string
  updated_at: string
  message_count: number
  last_message_preview?: string | null
  active_run_id?: string | null
  active_run_status?: ChatRunStatus | null
}

export interface ChatSessionDetail extends ChatSessionSummary {
  messages: ChatMessage[]
  runs: ChatRun[]
}

export interface ChatMessageCreateResponse {
  run_id: string
  user_message_id: string
  assistant_message_id: string
}

export interface ChatSessionsClearResponse {
  deleted_count: number
}

export interface ChatRunStarted {
  session_id: string
  run_id: string
  user_message_id: string
  assistant_message_id: string
  timestamp: string
}

export interface ChatRetrievalCompleted {
  session_id: string
  run_id: string
  thinking: string
  node_ids: string[]
  citations: NodeCitation[]
  timestamp: string
}

export interface ChatAnswerDelta {
  session_id: string
  run_id: string
  assistant_message_id: string
  delta: string
  timestamp: string
}

export interface ChatAnswerCompleted {
  session_id: string
  run_id: string
  assistant_message_id: string
  citations: NodeCitation[]
  timestamp: string
}

export interface ChatRunCompleted {
  session_id: string
  run_id: string
  timestamp: string
}

export interface ChatRunFailed {
  session_id: string
  run_id: string
  error: string
  timestamp: string
}
