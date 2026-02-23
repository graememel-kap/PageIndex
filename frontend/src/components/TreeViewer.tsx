import { useMemo, useState } from 'react'

import type { JobResult, JobResultNode } from '../types'

type TreeViewerProps = {
  result: JobResult | null
}

function flattenNodes(nodes: JobResultNode[]): JobResultNode[] {
  const all: JobResultNode[] = []
  const walk = (node: JobResultNode) => {
    all.push(node)
    if (node.nodes) {
      node.nodes.forEach(walk)
    }
  }
  nodes.forEach(walk)
  return all
}

function nodeIdentity(node: JobResultNode): string {
  return node.node_id ?? `${node.title}-${node.start_index ?? 'na'}`
}

function renderTree(
  nodes: JobResultNode[],
  activeNodeKey: string | null,
  onSelect: (node: JobResultNode) => void,
): JSX.Element {
  return (
    <ul className="tree-list">
      {nodes.map((node) => {
        const key = nodeIdentity(node)
        return (
          <li key={key}>
            <button
              type="button"
              className={`tree-node ${activeNodeKey === key ? 'active' : ''}`}
              onClick={() => onSelect(node)}
            >
              <span className="tree-title">{node.title}</span>
              <span className="tree-meta">
                {node.node_id ?? 'no-id'}
                {node.start_index !== undefined && node.end_index !== undefined
                  ? ` · p${node.start_index}-${node.end_index}`
                  : ''}
              </span>
            </button>
            {node.nodes && node.nodes.length > 0
              ? renderTree(node.nodes, activeNodeKey, onSelect)
              : null}
          </li>
        )
      })}
    </ul>
  )
}

export function TreeViewer({ result }: TreeViewerProps) {
  const nodes = result?.structure ?? []
  const [selectedNode, setSelectedNode] = useState<JobResultNode | null>(null)

  const flattened = useMemo(() => flattenNodes(nodes), [nodes])

  const selected = selectedNode ?? flattened[0] ?? null
  const activeKey = selected ? nodeIdentity(selected) : null

  return (
    <div className="tree-pane">
      <div className="section-header">
        <h2>Tree Explorer</h2>
        {result ? <span className="doc-pill">{result.doc_name}</span> : null}
      </div>

      {!result ? (
        <p className="muted">
          Completed runs will appear here with an interactive tree and node details.
        </p>
      ) : (
        <div className="tree-content">
          <div className="tree-column">{renderTree(nodes, activeKey, setSelectedNode)}</div>
          <div className="node-detail">
            {selected ? (
              <>
                <h3>{selected.title}</h3>
                <p className="node-id">Node: {selected.node_id ?? 'n/a'}</p>
                {selected.start_index !== undefined && selected.end_index !== undefined ? (
                  <p className="node-id">
                    Page range: {selected.start_index} - {selected.end_index}
                  </p>
                ) : null}
                {selected.summary ? <p>{selected.summary}</p> : null}
                {selected.prefix_summary ? <p>{selected.prefix_summary}</p> : null}
                {!selected.summary && !selected.prefix_summary ? (
                  <p className="muted">This node does not include generated summary text.</p>
                ) : null}
              </>
            ) : (
              <p className="muted">Select a node to inspect details.</p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
