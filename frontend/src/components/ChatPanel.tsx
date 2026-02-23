import { FormEvent, useEffect, useMemo, useRef, useState } from 'react'

import type { ChatSessionDetail, NodeCitation } from '../types'

type ChatPanelProps = {
  session: ChatSessionDetail | null
  isLoading: boolean
  isRunning: boolean
  error: string | null
  retrievalNote: string | null
  enabled: boolean
  onSend: (content: string) => void
  onClearSessions: () => void
  onSelectCitation: (nodeId: string) => void
}

function citationLabel(citation: NodeCitation): string {
  if (citation.start_index !== undefined && citation.start_index !== null) {
    const end = citation.end_index ?? citation.start_index
    return `${citation.node_id} · p${citation.start_index}-${end}`
  }
  if (citation.line_num !== undefined && citation.line_num !== null) {
    return `${citation.node_id} · l${citation.line_num}`
  }
  return citation.node_id
}

export function ChatPanel({
  session,
  isLoading,
  isRunning,
  error,
  retrievalNote,
  enabled,
  onSend,
  onClearSessions,
  onSelectCitation,
}: ChatPanelProps) {
  const [draft, setDraft] = useState('')
  const listRef = useRef<HTMLDivElement | null>(null)

  const messages = useMemo(() => session?.messages ?? [], [session?.messages])

  useEffect(() => {
    if (!listRef.current) {
      return
    }
    listRef.current.scrollTop = listRef.current.scrollHeight
  }, [messages, isRunning])

  const onSubmit = (event: FormEvent) => {
    event.preventDefault()
    const content = draft.trim()
    if (!content || !enabled || isRunning) {
      return
    }
    onSend(content)
    setDraft('')
  }

  return (
    <div className="chat-pane">
      <div className="section-header">
        <h2>Chat</h2>
        {enabled ? (
          <button
            type="button"
            className="secondary-button"
            onClick={onClearSessions}
            disabled={isLoading || isRunning}
          >
            Clear Past Sessions
          </button>
        ) : null}
      </div>

      {!enabled ? (
        <p className="muted">Chat is available after indexing completes.</p>
      ) : (
        <>
          <div className="chat-messages" ref={listRef}>
            {isLoading ? <p className="muted">Loading chat...</p> : null}
            {messages.length === 0 && !isLoading ? (
              <p className="muted">Ask a question about this indexed document.</p>
            ) : null}
            {messages.map((message) => (
              <div key={message.id} className={`chat-message ${message.role}`}>
                <div className="chat-role">{message.role}</div>
                <p>{message.content || (message.role === 'assistant' && isRunning ? '...' : '')}</p>
                {message.citations.length > 0 ? (
                  <div className="chat-citations">
                    {message.citations.map((citation, idx) => (
                      <button
                        type="button"
                        className="citation-chip"
                        key={`${citation.node_id}-${idx}`}
                        onClick={() => onSelectCitation(citation.node_id)}
                      >
                        {citationLabel(citation)}
                      </button>
                    ))}
                  </div>
                ) : null}
              </div>
            ))}
          </div>

          {retrievalNote ? <p className="chat-note">{retrievalNote}</p> : null}
          {error ? <p className="error-text">{error}</p> : null}

          <form className="chat-composer" onSubmit={onSubmit}>
            <textarea
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder="Ask about this document..."
              rows={3}
              disabled={!enabled || isRunning}
            />
            <button className="primary-button" type="submit" disabled={!enabled || isRunning}>
              {isRunning ? 'Thinking...' : 'Send'}
            </button>
          </form>
        </>
      )}
    </div>
  )
}
