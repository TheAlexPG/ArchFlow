import { useEffect, useRef, useState } from 'react'
import {
  useConnection,
  useDeleteConnection,
  useObjects,
  useUpdateConnection,
} from '../../hooks/use-api'
import { useCanvasStore } from '../../stores/canvas-store'
import type { EdgeShape } from '../../types/model'

const SHAPES: { value: EdgeShape; label: string; icon: string }[] = [
  { value: 'curved', label: 'Curved', icon: '∿' },
  { value: 'straight', label: 'Straight', icon: '─' },
  { value: 'step', label: 'Step', icon: '⌐' },
  { value: 'smoothstep', label: 'Smooth', icon: '⌒' },
]

export function EdgeSidebar() {
  const { selectedEdgeId, selectEdge } = useCanvasStore()
  const { data: conn } = useConnection(selectedEdgeId)
  const { data: objects = [] } = useObjects()
  const updateConn = useUpdateConnection()
  const deleteConn = useDeleteConnection()

  const [label, setLabel] = useState('')
  const [protocol, setProtocol] = useState('')
  const labelTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (conn) {
      setLabel(conn.label || '')
      setProtocol(conn.protocol || '')
    }
  }, [conn])

  if (!selectedEdgeId || !conn) return null

  const source = objects.find((o) => o.id === conn.source_id)
  const target = objects.find((o) => o.id === conn.target_id)

  const handleUpdate = (data: Partial<{ [k: string]: unknown }>) => {
    updateConn.mutate({ id: conn.id, ...data })
  }

  const handleLabelChange = (value: string) => {
    setLabel(value)
    labelTimerRef.current && clearTimeout(labelTimerRef.current)
    labelTimerRef.current = setTimeout(() => {
      handleUpdate({ label: value || null })
    }, 400)
  }

  const handleFlip = () => {
    updateConn.mutate({
      id: conn.id,
      // swap by updating with new source_id/target_id — need separate endpoint,
      // for now toggle direction
      direction: conn.direction === 'unidirectional' ? 'bidirectional' : 'unidirectional',
    })
  }

  const handleDelete = () => {
    if (confirm('Delete this connection?')) {
      deleteConn.mutate(conn.id)
      selectEdge(null)
    }
  }

  return (
    <div className="w-80 bg-neutral-900 border-l border-neutral-800 flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-neutral-800">
        <div className="flex-1 min-w-0">
          <div className="text-xs text-neutral-500">Connection</div>
          <div className="text-sm font-medium text-neutral-200 truncate">
            {label || 'Untitled'}
          </div>
        </div>
        <button
          onClick={() => selectEdge(null)}
          className="text-neutral-500 hover:text-neutral-300 text-lg ml-2"
        >
          ×
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* Sender/Receiver */}
        <Field label="Sender">
          <span className="text-sm text-neutral-300">{source?.name || '—'}</span>
        </Field>
        <Field label="Receiver">
          <span className="text-sm text-neutral-300">{target?.name || '—'}</span>
        </Field>

        {/* Direction */}
        <Field label="Direction">
          <div className="flex items-center gap-2">
            <select
              value={conn.direction}
              onChange={(e) => handleUpdate({ direction: e.target.value })}
              className="bg-neutral-800 text-neutral-200 text-sm rounded px-2 py-1 flex-1 border border-neutral-700"
            >
              <option value="unidirectional">Outgoing →</option>
              <option value="bidirectional">Bidirectional ⇄</option>
            </select>
            <button
              onClick={handleFlip}
              className="text-xs text-blue-400 hover:text-blue-300 px-2 py-1 rounded border border-neutral-700 hover:border-neutral-600"
              title="Flip source/target"
            >
              ⇄ Flip
            </button>
          </div>
        </Field>

        {/* Shape */}
        <Field label="Shape">
          <div className="flex gap-1">
            {SHAPES.map((s) => (
              <button
                key={s.value}
                onClick={() => handleUpdate({ shape: s.value })}
                className={`flex-1 px-2 py-1 rounded text-xs border transition-colors ${
                  conn.shape === s.value
                    ? 'bg-neutral-700 border-neutral-600 text-neutral-100'
                    : 'bg-neutral-800 border-neutral-700 text-neutral-400 hover:text-neutral-200'
                }`}
              >
                <span className="text-base">{s.icon}</span>
                <div className="text-[10px] mt-0.5">{s.label}</div>
              </button>
            ))}
          </div>
        </Field>

        {/* Label */}
        <Field label="Label">
          <textarea
            value={label}
            onChange={(e) => handleLabelChange(e.target.value)}
            rows={2}
            className="bg-neutral-800 text-neutral-200 text-xs rounded px-2 py-1.5 w-full border border-neutral-700 resize-none"
            placeholder="Edge label..."
          />
        </Field>

        {/* Label size */}
        <Field label={`Label size: ${conn.label_size.toFixed(0)}px`}>
          <input
            type="range"
            min={8}
            max={20}
            step={1}
            value={conn.label_size}
            onChange={(e) => handleUpdate({ label_size: parseFloat(e.target.value) })}
            className="w-full accent-blue-500"
          />
        </Field>

        {/* Protocol */}
        <Field label="Protocol">
          <input
            value={protocol}
            onChange={(e) => setProtocol(e.target.value)}
            onBlur={() => handleUpdate({ protocol: protocol || null })}
            placeholder="REST, gRPC, WebSocket..."
            className="bg-neutral-800 text-neutral-200 text-sm rounded px-2 py-1 w-full border border-neutral-700"
          />
        </Field>

        {/* Delete */}
        <button
          onClick={handleDelete}
          className="w-full mt-4 px-3 py-2 rounded text-sm text-red-400 border border-red-900/50 hover:bg-red-900/20 transition-colors"
        >
          Delete connection
        </button>
      </div>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-xs text-neutral-500 mb-1">{label}</div>
      {children}
    </div>
  )
}

