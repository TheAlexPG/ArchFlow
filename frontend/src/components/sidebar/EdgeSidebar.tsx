import { useEffect, useRef, useState } from 'react'
import {
  useConnection,
  useDeleteConnection,
  useFlipConnection,
  useObjects,
  useUpdateConnection,
} from '../../hooks/use-api'
import { useDiagram } from '../../hooks/use-diagrams'
import { useCanvasStore } from '../../stores/canvas-store'
import type { ConnectionDirection, EdgeShape } from '../../types/model'

const SHAPES: { value: EdgeShape; label: string; icon: string }[] = [
  { value: 'curved', label: 'Curved', icon: '∿' },
  { value: 'straight', label: 'Straight', icon: '─' },
  { value: 'step', label: 'Step', icon: '⌐' },
  { value: 'smoothstep', label: 'Smooth', icon: '⌒' },
]

const DIRECTIONS: { value: ConnectionDirection; label: string; icon: string }[] = [
  { value: 'unidirectional', label: 'Outgoing', icon: '→' },
  { value: 'bidirectional', label: 'Bidirectional', icon: '⇄' },
  { value: 'undirected', label: 'Undirected', icon: '—' },
]

interface EdgeSidebarProps {
  diagramId?: string
}

export function EdgeSidebar({ diagramId }: EdgeSidebarProps) {
  const { selectedEdgeId, selectEdge } = useCanvasStore()
  const { data: conn } = useConnection(selectedEdgeId)
  const { data: diagram } = useDiagram(diagramId)
  const draftId = diagram?.draft_id ?? null
  const { data: objects = [] } = useObjects(draftId)
  const updateConn = useUpdateConnection()
  const flipConn = useFlipConnection()
  const deleteConn = useDeleteConnection()

  const [label, setLabel] = useState('')
  const [protocol, setProtocol] = useState('')
  const labelTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (conn) {
      setLabel(conn.label || '')
      // TODO(tech-catalog): swap this free-text input for TechnologyPicker
      // (M7). For now the input shows the raw protocol UUID if any.
      setProtocol(conn.protocol_id || '')
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
    flipConn.mutate({ id: conn.id })
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
        {/* Sender */}
        <Field label="Sender">
          <span className="text-sm text-neutral-300">{source?.name || '—'}</span>
        </Field>

        {/* Receiver */}
        <Field label="Receiver">
          <span className="text-sm text-neutral-300">{target?.name || '—'}</span>
        </Field>

        {/* Direction */}
        <Field label="Direction">
          <div className="flex gap-1">
            {DIRECTIONS.map((d) => (
              <button
                key={d.value}
                onClick={() => handleUpdate({ direction: d.value })}
                className={`flex-1 px-2 py-1 rounded text-xs border transition-colors ${
                  conn.direction === d.value
                    ? 'bg-neutral-700 border-neutral-600 text-neutral-100'
                    : 'bg-neutral-800 border-neutral-700 text-neutral-400 hover:text-neutral-200'
                }`}
              >
                <span className="text-base">{d.icon}</span>
                <div className="text-[10px] mt-0.5">{d.label}</div>
              </button>
            ))}
          </div>
        </Field>

        {/* Swap sender / receiver — only meaningful for a one-way arrow. */}
        {conn.direction === 'unidirectional' && (
          <button
            onClick={handleFlip}
            className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded text-xs bg-neutral-800 border border-neutral-700 text-neutral-300 hover:text-neutral-100 hover:border-neutral-500 transition-colors"
          >
            <span className="text-base">⇄</span>
            <span>Swap sender / receiver</span>
          </button>
        )}

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
          <div className="relative w-full">
            <input
              type="range"
              min={8}
              max={20}
              step={1}
              value={conn.label_size}
              onChange={(e) => handleUpdate({ label_size: parseFloat(e.target.value) })}
              style={{
                // filled-track trick: gradient from accent to track bg
                background: `linear-gradient(to right, #f97316 0%, #f97316 ${((conn.label_size - 8) / (20 - 8)) * 100}%, #404040 ${((conn.label_size - 8) / (20 - 8)) * 100}%, #404040 100%)`,
              }}
              className={[
                'w-full h-1.5 rounded-full appearance-none cursor-pointer outline-none',
                'focus-visible:ring-2 focus-visible:ring-orange-500 focus-visible:ring-offset-2 focus-visible:ring-offset-neutral-900',
                // Runnable-track – webkit: transparent so the input's gradient shows through
                '[&::-webkit-slider-runnable-track]:h-1.5 [&::-webkit-slider-runnable-track]:rounded-full',
                '[&::-webkit-slider-runnable-track]:bg-transparent',
                // Runnable-track – moz: transparent so the input's gradient shows through
                '[&::-moz-range-track]:h-1.5 [&::-moz-range-track]:rounded-full',
                '[&::-moz-range-track]:bg-transparent',
                // Thumb – webkit
                '[&::-webkit-slider-thumb]:appearance-none',
                '[&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:h-4',
                '[&::-webkit-slider-thumb]:-mt-[5px]',
                '[&::-webkit-slider-thumb]:rounded-full',
                '[&::-webkit-slider-thumb]:bg-orange-500',
                '[&::-webkit-slider-thumb]:border-2 [&::-webkit-slider-thumb]:border-neutral-900',
                '[&::-webkit-slider-thumb]:shadow-[0_0_0_1px_rgba(249,115,22,0.4),0_2px_6px_rgba(0,0,0,0.5)]',
                '[&::-webkit-slider-thumb]:transition-transform [&::-webkit-slider-thumb]:hover:scale-110',
                // Thumb – moz
                '[&::-moz-range-thumb]:w-4 [&::-moz-range-thumb]:h-4',
                '[&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:border-2',
                '[&::-moz-range-thumb]:bg-orange-500 [&::-moz-range-thumb]:border-neutral-900',
                '[&::-moz-range-thumb]:cursor-pointer',
              ].join(' ')}
            />
          </div>
        </Field>

        {/* Protocol */}
        <Field label="Protocol">
          <input
            value={protocol}
            onChange={(e) => setProtocol(e.target.value)}
            onBlur={() => handleUpdate({ protocol_id: protocol || null })}
            placeholder="REST, gRPC, WebSocket..."
            className="bg-neutral-800 text-neutral-200 text-sm rounded px-2 py-1 w-full border border-neutral-700"
          />
        </Field>

        {/* Via (pass-through objects) */}
        <Field label="Via (pass-through)">
          <ViaSelector
            selected={conn.via_object_ids || []}
            sourceId={conn.source_id}
            targetId={conn.target_id}
            allObjects={objects}
            onChange={(ids) => handleUpdate({ via_object_ids: ids })}
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

function ViaSelector({
  selected,
  sourceId,
  targetId,
  allObjects,
  onChange,
}: {
  selected: string[]
  sourceId: string
  targetId: string
  allObjects: { id: string; name: string }[]
  onChange: (ids: string[]) => void
}) {
  const [showPicker, setShowPicker] = useState(false)
  const available = allObjects.filter(
    (o) => o.id !== sourceId && o.id !== targetId && !selected.includes(o.id),
  )

  const selectedObjects = selected
    .map((id) => allObjects.find((o) => o.id === id))
    .filter((o): o is { id: string; name: string } => !!o)

  return (
    <div>
      <div className="flex flex-wrap gap-1 mb-1">
        {selectedObjects.map((obj) => (
          <span
            key={obj.id}
            className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-neutral-800 text-neutral-300 text-xs border border-neutral-700"
          >
            {obj.name}
            <button
              onClick={() => onChange(selected.filter((id) => id !== obj.id))}
              className="text-neutral-500 hover:text-neutral-300"
            >
              ×
            </button>
          </span>
        ))}
      </div>
      <button
        onClick={() => setShowPicker(!showPicker)}
        className="text-xs text-blue-400 hover:text-blue-300"
      >
        {showPicker ? 'Cancel' : '+ Select objects'}
      </button>
      {showPicker && (
        <div className="mt-1 max-h-32 overflow-y-auto bg-neutral-800 border border-neutral-700 rounded">
          {available.length === 0 ? (
            <div className="text-xs text-neutral-600 p-2">No available objects</div>
          ) : (
            available.map((obj) => (
              <button
                key={obj.id}
                onClick={() => {
                  onChange([...selected, obj.id])
                  setShowPicker(false)
                }}
                className="block w-full text-left text-xs px-2 py-1 text-neutral-300 hover:bg-neutral-700"
              >
                {obj.name}
              </button>
            ))
          )}
        </div>
      )}
    </div>
  )
}

