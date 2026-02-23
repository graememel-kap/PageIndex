import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import {
  cancelJob,
  clearChatSessions,
  createChatSession,
  createJob,
  getChatSession,
  getJob,
  getJobResult,
  listChatSessions,
  listJobs,
  openChatEvents,
  openJobEvents,
  sendChatMessage,
} from '../api'
import { ChatPanel } from '../components/ChatPanel'
import { ProgressRail } from '../components/ProgressRail'
import { RunHistory } from '../components/RunHistory'
import { TreeViewer } from '../components/TreeViewer'
import type {
  ChatMessage,
  ChatSessionDetail,
  InputType,
  JobDetail,
  JobResult,
  JobSummary,
} from '../types'

function toYesNo(value: boolean): 'yes' | 'no' {
  return value ? 'yes' : 'no'
}

function mergeSummary(list: JobSummary[], detail: JobDetail): JobSummary[] {
  const summary: JobSummary = {
    id: detail.id,
    filename: detail.filename,
    input_type: detail.input_type,
    status: detail.status,
    stage: detail.stage,
    progress: detail.progress,
    created_at: detail.created_at,
    updated_at: detail.updated_at,
  }

  const without = list.filter((item) => item.id !== detail.id)
  return [summary, ...without].sort((a, b) => (a.created_at < b.created_at ? 1 : -1))
}

export function WorkbenchPage() {
  const [jobs, setJobs] = useState<JobSummary[]>([])
  const [selectedJob, setSelectedJob] = useState<JobDetail | null>(null)
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null)
  const [result, setResult] = useState<JobResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [connectionWarning, setConnectionWarning] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  const [chatSession, setChatSession] = useState<ChatSessionDetail | null>(null)
  const [chatError, setChatError] = useState<string | null>(null)
  const [chatLoading, setChatLoading] = useState(false)
  const [chatRunning, setChatRunning] = useState(false)
  const [chatRetrievalNote, setChatRetrievalNote] = useState<string | null>(null)
  const [focusNodeId, setFocusNodeId] = useState<string | null>(null)

  const jobStreamRef = useRef<EventSource | null>(null)
  const jobRetryRef = useRef<number | null>(null)
  const chatStreamRef = useRef<EventSource | null>(null)

  const [file, setFile] = useState<File | null>(null)
  const [inputType, setInputType] = useState<InputType>('pdf')
  const [model, setModel] = useState('gpt-4.1')
  const [tocCheckPages, setTocCheckPages] = useState(20)
  const [maxPagesPerNode, setMaxPagesPerNode] = useState(10)
  const [maxTokensPerNode, setMaxTokensPerNode] = useState(20000)
  const [ifAddNodeId, setIfAddNodeId] = useState(true)
  const [ifAddNodeSummary, setIfAddNodeSummary] = useState(true)
  const [ifAddDocDescription, setIfAddDocDescription] = useState(false)
  const [ifAddNodeText, setIfAddNodeText] = useState(false)
  const [ifThinning, setIfThinning] = useState(false)
  const [thinningThreshold, setThinningThreshold] = useState(5000)
  const [summaryTokenThreshold, setSummaryTokenThreshold] = useState(200)

  const activeRunningJobId = useMemo(
    () => jobs.find((item) => item.status === 'RUNNING')?.id ?? null,
    [jobs],
  )

  const closeJobStream = useCallback(() => {
    if (jobStreamRef.current) {
      jobStreamRef.current.close()
      jobStreamRef.current = null
    }
    if (jobRetryRef.current !== null) {
      window.clearTimeout(jobRetryRef.current)
      jobRetryRef.current = null
    }
  }, [])

  const closeChatStream = useCallback(() => {
    if (chatStreamRef.current) {
      chatStreamRef.current.close()
      chatStreamRef.current = null
    }
  }, [])

  const loadResult = useCallback(async (jobId: string) => {
    try {
      const payload = await getJobResult(jobId)
      setResult(payload)
    } catch {
      setResult(null)
    }
  }, [])

  const loadOrCreateChatSession = useCallback(async (jobId: string) => {
    setChatLoading(true)
    setChatError(null)
    setChatRetrievalNote(null)
    try {
      const list = await listChatSessions(jobId)
      const selected =
        list.length > 0 ? list[0] : await createChatSession(jobId)
      const detail = await getChatSession(selected.id)
      setChatSession(detail)
      setChatRunning(detail.active_run_status === 'RUNNING')
    } catch (err) {
      setChatSession(null)
      setChatRunning(false)
      setChatError(err instanceof Error ? err.message : 'Failed to load chat session')
    } finally {
      setChatLoading(false)
    }
  }, [])

  const loadJob = useCallback(
    async (jobId: string) => {
      try {
        closeChatStream()
        setFocusNodeId(null)
        const detail = await getJob(jobId)
        setSelectedJob(detail)
        setSelectedJobId(jobId)
        setJobs((prev) => mergeSummary(prev, detail))

        if (detail.status === 'COMPLETED') {
          await loadResult(jobId)
          await loadOrCreateChatSession(jobId)
        } else {
          setResult(null)
          setChatSession(null)
          setChatRunning(false)
          setChatError(null)
          setChatRetrievalNote(null)
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load job')
      }
    },
    [closeChatStream, loadOrCreateChatSession, loadResult],
  )

  const subscribeToJob = useCallback(
    (jobId: string) => {
      closeJobStream()
      setConnectionWarning(null)

      const stream = openJobEvents(jobId, {
        onUpdate: (job) => {
          setSelectedJob((prev) => (prev?.id === job.id || job.id === jobId ? job : prev))
          setJobs((prev) => mergeSummary(prev, job))
          if (job.status === 'COMPLETED') {
            void loadResult(job.id)
            if (job.id === selectedJobId) {
              void loadOrCreateChatSession(job.id)
            }
          }
          if (job.status === 'FAILED' || job.status === 'CANCELLED' || job.status === 'COMPLETED') {
            setConnectionWarning(null)
          }
        },
        onActivity: () => {
          // Activity arrives through `job.update` snapshots; no separate state needed.
        },
        onError: (message) => {
          setError(message)
        },
        onCompleted: (completedJobId) => {
          void loadResult(completedJobId)
        },
        onConnectionError: () => {
          setConnectionWarning('Live stream interrupted. Reconnecting...')
          if (jobRetryRef.current === null) {
            jobRetryRef.current = window.setTimeout(() => {
              jobRetryRef.current = null
              subscribeToJob(jobId)
            }, 2000)
          }
        },
      })
      jobStreamRef.current = stream
    },
    [closeJobStream, loadOrCreateChatSession, loadResult, selectedJobId],
  )

  const loadJobs = useCallback(async () => {
    try {
      const list = await listJobs()
      setJobs(list)
      if (list.length > 0 && !selectedJobId) {
        await loadJob(list[0].id)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load jobs')
    }
  }, [loadJob, selectedJobId])

  useEffect(() => {
    void loadJobs()
    return () => {
      closeJobStream()
      closeChatStream()
    }
  }, [closeChatStream, closeJobStream, loadJobs])

  useEffect(() => {
    const target = activeRunningJobId ?? selectedJobId
    if (target) {
      subscribeToJob(target)
    }
  }, [activeRunningJobId, selectedJobId, subscribeToJob])

  const onStart = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!file) {
      setError('Choose a PDF or Markdown file first.')
      return
    }

    setIsSubmitting(true)
    setError(null)

    try {
      const formData = new FormData()
      formData.append('file', file)
      formData.append('input_type', inputType)
      formData.append('model', model)
      formData.append('if_add_node_id', toYesNo(ifAddNodeId))
      formData.append('if_add_node_summary', toYesNo(ifAddNodeSummary))
      formData.append('if_add_doc_description', toYesNo(ifAddDocDescription))
      formData.append('if_add_node_text', toYesNo(ifAddNodeText))

      if (inputType === 'pdf') {
        formData.append('toc_check_pages', String(tocCheckPages))
        formData.append('max_pages_per_node', String(maxPagesPerNode))
        formData.append('max_tokens_per_node', String(maxTokensPerNode))
      }

      if (inputType === 'md') {
        formData.append('if_thinning', toYesNo(ifThinning))
        formData.append('thinning_threshold', String(thinningThreshold))
        formData.append('summary_token_threshold', String(summaryTokenThreshold))
      }

      const created = await createJob(formData)
      setJobs((prev) => [created, ...prev.filter((item) => item.id !== created.id)])
      await loadJob(created.id)
      subscribeToJob(created.id)
      setResult(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create job')
    } finally {
      setIsSubmitting(false)
    }
  }

  const onCancel = async () => {
    if (!selectedJob) {
      return
    }
    try {
      const updated = await cancelJob(selectedJob.id)
      setSelectedJob(updated)
      setJobs((prev) => mergeSummary(prev, updated))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to cancel job')
    }
  }

  const applyChatDelta = useCallback((assistantMessageId: string, delta: string) => {
    setChatSession((prev) => {
      if (!prev) {
        return prev
      }
      const nextMessages: ChatMessage[] = prev.messages.map((message) => {
        if (message.id !== assistantMessageId) {
          return message
        }
        return { ...message, content: `${message.content}${delta}` }
      })
      return { ...prev, messages: nextMessages }
    })
  }, [])

  const onSendChat = useCallback(
    async (content: string) => {
      if (!chatSession || !selectedJobId) {
        return
      }
      setChatError(null)
      setChatRetrievalNote(null)
      setFocusNodeId(null)
      setChatRunning(true)

      try {
        const started = await sendChatMessage(chatSession.id, content)
        const refreshed = await getChatSession(chatSession.id)
        setChatSession(refreshed)

        closeChatStream()
        const stream = openChatEvents(chatSession.id, started.run_id, {
          onRunStarted: () => {
            setChatRunning(true)
          },
          onRetrievalCompleted: (payload) => {
            if (payload.node_ids.length === 0) {
              setChatRetrievalNote('No matching sections were selected by retrieval.')
            } else {
              setChatRetrievalNote(
                `Retrieved ${payload.node_ids.length} candidate section(s): ${payload.node_ids.join(', ')}`,
              )
            }
            if (payload.node_ids.length > 0) {
              setFocusNodeId(payload.node_ids[0])
            }
          },
          onAnswerDelta: (payload) => {
            applyChatDelta(payload.assistant_message_id, payload.delta)
          },
          onAnswerCompleted: async (payload) => {
            setChatSession((prev) => {
              if (!prev) {
                return prev
              }
              const nextMessages = prev.messages.map((message) => {
                if (message.id !== payload.assistant_message_id) {
                  return message
                }
                return { ...message, citations: payload.citations }
              })
              return { ...prev, messages: nextMessages }
            })
          },
          onRunCompleted: async () => {
            setChatRunning(false)
            closeChatStream()
            const detail = await getChatSession(chatSession.id)
            setChatSession(detail)
          },
          onRunFailed: async (payload) => {
            setChatRunning(false)
            setChatError(payload.error)
            closeChatStream()
            const detail = await getChatSession(chatSession.id)
            setChatSession(detail)
          },
          onConnectionError: () => {
            setChatError('Chat stream interrupted.')
          },
        })
        chatStreamRef.current = stream
      } catch (err) {
        setChatRunning(false)
        setChatError(err instanceof Error ? err.message : 'Failed to send message')
      }
    },
    [applyChatDelta, chatSession, closeChatStream, selectedJobId],
  )

  const onClearPastSessions = useCallback(async () => {
    if (!selectedJobId || chatRunning) {
      return
    }
    setChatLoading(true)
    setChatError(null)
    setChatRetrievalNote(null)
    setFocusNodeId(null)
    closeChatStream()
    try {
      await clearChatSessions(selectedJobId)
      const created = await createChatSession(selectedJobId)
      const detail = await getChatSession(created.id)
      setChatSession(detail)
      setChatRunning(false)
    } catch (err) {
      setChatError(err instanceof Error ? err.message : 'Failed to clear chat sessions')
    } finally {
      setChatLoading(false)
    }
  }, [chatRunning, closeChatStream, selectedJobId])

  return (
    <div className="app-shell">
      <header className="app-header">
        <p className="eyebrow">PageIndex</p>
        <h1>Indexer Workbench</h1>
        <p className="lead">
          Upload a document, run indexing, watch live progress, and inspect the generated
          structure.
        </p>
      </header>

      {error ? <div className="error-banner">{error}</div> : null}

      <main className="workspace-grid">
        <section className="pane controls-pane">
          <div className="section-header">
            <h2>New Run</h2>
          </div>

          <form className="workbench-form" onSubmit={onStart}>
            <label>
              Input Type
              <select
                value={inputType}
                onChange={(e) => {
                  setInputType(e.target.value as InputType)
                  setFile(null)
                }}
              >
                <option value="pdf">PDF</option>
                <option value="md">Markdown</option>
              </select>
            </label>

            <label>
              File
              <input
                type="file"
                accept={inputType === 'pdf' ? '.pdf' : '.md,.markdown'}
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
            </label>

            <label>
              Model
              <input value={model} onChange={(e) => setModel(e.target.value)} />
            </label>

            {inputType === 'pdf' ? (
              <>
                <label>
                  TOC Check Pages
                  <input
                    type="number"
                    value={tocCheckPages}
                    onChange={(e) => setTocCheckPages(Number(e.target.value))}
                  />
                </label>
                <label>
                  Max Pages Per Node
                  <input
                    type="number"
                    value={maxPagesPerNode}
                    onChange={(e) => setMaxPagesPerNode(Number(e.target.value))}
                  />
                </label>
                <label>
                  Max Tokens Per Node
                  <input
                    type="number"
                    value={maxTokensPerNode}
                    onChange={(e) => setMaxTokensPerNode(Number(e.target.value))}
                  />
                </label>
              </>
            ) : (
              <>
                <label>
                  <input
                    type="checkbox"
                    checked={ifThinning}
                    onChange={(e) => setIfThinning(e.target.checked)}
                  />
                  Enable Thinning
                </label>
                <label>
                  Thinning Threshold
                  <input
                    type="number"
                    value={thinningThreshold}
                    onChange={(e) => setThinningThreshold(Number(e.target.value))}
                  />
                </label>
                <label>
                  Summary Token Threshold
                  <input
                    type="number"
                    value={summaryTokenThreshold}
                    onChange={(e) => setSummaryTokenThreshold(Number(e.target.value))}
                  />
                </label>
              </>
            )}

            <label>
              <input
                type="checkbox"
                checked={ifAddNodeId}
                onChange={(e) => setIfAddNodeId(e.target.checked)}
              />
              Add Node IDs
            </label>
            <label>
              <input
                type="checkbox"
                checked={ifAddNodeSummary}
                onChange={(e) => setIfAddNodeSummary(e.target.checked)}
              />
              Add Node Summaries
            </label>
            <label>
              <input
                type="checkbox"
                checked={ifAddDocDescription}
                onChange={(e) => setIfAddDocDescription(e.target.checked)}
              />
              Add Document Description
            </label>
            <label>
              <input
                type="checkbox"
                checked={ifAddNodeText}
                onChange={(e) => setIfAddNodeText(e.target.checked)}
              />
              Include Node Text
            </label>

            <button className="primary-button" type="submit" disabled={isSubmitting}>
              {isSubmitting ? 'Starting...' : 'Start Indexing'}
            </button>
          </form>

          <RunHistory
            jobs={jobs}
            selectedJobId={selectedJobId}
            onSelect={(jobId) => {
              setError(null)
              void loadJob(jobId)
            }}
          />
        </section>

        <div className="workspace-main">
          <section className="pane">
            <ProgressRail
              job={selectedJob}
              onCancel={onCancel}
              connectionWarning={connectionWarning}
            />
          </section>

          <section className="pane">
            <TreeViewer result={result} focusNodeId={focusNodeId} />
          </section>

          <section className="pane pane-chat">
            <ChatPanel
              session={chatSession}
              isLoading={chatLoading}
              isRunning={chatRunning}
              error={chatError}
            retrievalNote={chatRetrievalNote}
            enabled={Boolean(selectedJob && selectedJob.status === 'COMPLETED')}
            onSend={onSendChat}
            onClearSessions={onClearPastSessions}
            onSelectCitation={(nodeId) => setFocusNodeId(nodeId)}
          />
        </section>
        </div>
      </main>
    </div>
  )
}
