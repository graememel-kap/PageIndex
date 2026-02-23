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
