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
import { Pill, SectionLabel } from '../ui'
import { TechnologyPicker } from '../tech'
import { cn } from '../../utils/cn'

// ─── Constants ────────────────────────────────────────────────────────────────

const SHAPES: { value: EdgeShape; label: string; icon: string }[] = [
  { value: 'curved',     label: 'Curved', icon: '∿' },
  { value: 'straight',   label: 'Straight', icon: '─' },
  { value: 'step',       label: 'Step', icon: '⌐' },
  { value: 'smoothstep', label: 'Smooth', icon: '⌒' },
]

const DIRECTIONS: { value: ConnectionDirection; label: string; icon: string }[] = [
  { value: 'unidirectional', label: 'Outgoing', icon: '→' },
  { value: 'bidirectional',  label: 'Bidirect', icon: '⇄' },
  { value: 'undirected',     label: 'Undirected', icon: '—' },
]

// ─── Types ────────────────────────────────────────────────────────────────────

interface EdgeSidebarProps {
  diagramId?: string
}

// ─── Main component ───────────────────────────────────────────────────────────

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
  const labelTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (conn) {
      setLabel(conn.label || '')
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

  // Slider gradient fill
  const sliderPct = ((conn.label_size - 8) / (20 - 8)) * 100
  const sliderBg = `linear-gradient(to right, #FF6B35 0%, #FF6B35 ${sliderPct}%, #26262c ${sliderPct}%, #26262c 100%)`

  return (
    <div className="w-80 bg-panel border-l border-border-base flex flex-col h-full overflow-hidden">

      {/* ── Header ── */}
      <div className="px-4 py-3 border-b border-border-base">
        {/* Top row: label + SELECTED pill + close */}
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <span className="font-mono text-[10px] uppercase tracking-[0.08em] text-text-3">Connection</span>
            <Pill variant="draft" className="text-[9.5px] py-[2px]">SELECTED</Pill>
          </div>
          <button
            onClick={() => selectEdge(null)}
            className="text-text-4 hover:text-text-2 text-lg leading-none transition-colors ml-2"
            aria-label="Close connection inspector"
          >
            ×
          </button>
        </div>

        {/* Connection display label */}
        <div className="text-[15px] font-semibold text-text-base truncate">
          {label || 'Untitled'}
        </div>
      </div>

      {/* ── Body ── */}
      <div className="flex-1 overflow-y-auto p-4 space-y-5">

        {/* Sender */}
        <div>
          <SectionLabel className="mb-1">Sender</SectionLabel>
          <span className="text-[13px] text-text-base">{source?.name || '—'}</span>
        </div>

        {/* Receiver */}
        <div>
          <SectionLabel className="mb-1">Receiver</SectionLabel>
          <span className="text-[13px] text-text-base">{target?.name || '—'}</span>
        </div>

        {/* Direction */}
        <div>
          <SectionLabel className="mb-1.5">Direction</SectionLabel>
          <div className="inline-flex gap-1 p-[2px] bg-surface border border-border-base rounded-md w-full">
            {DIRECTIONS.map((d) => (
              <button
                key={d.value}
                onClick={() => handleUpdate({ direction: d.value })}
                className={cn(
                  'flex-1 flex flex-col items-center px-2 py-1 rounded text-[11px] transition-colors',
                  conn.direction === d.value
                    ? 'bg-coral text-bg font-medium'
                    : 'text-text-3 hover:text-text-2',
                )}
              >
                <span className="text-base leading-tight">{d.icon}</span>
                <span className="text-[9.5px] mt-0.5 leading-none">{d.label}</span>
              </button>
            ))}
          </div>
        </div>

        {/* Swap sender / receiver — only for unidirectional */}
        {conn.direction === 'unidirectional' && (
          <button
            onClick={handleFlip}
            className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-md text-[12px] font-mono bg-surface border border-border-base text-text-2 hover:text-text-base hover:border-border-hi transition-colors"
          >
            <span className="text-base">⇄</span>
            <span>Swap sender / receiver</span>
          </button>
        )}

        {/* Shape */}
        <div>
          <SectionLabel className="mb-1.5">Shape</SectionLabel>
          <div className="inline-flex gap-1 p-[2px] bg-surface border border-border-base rounded-md w-full">
            {SHAPES.map((s) => (
              <button
                key={s.value}
                onClick={() => handleUpdate({ shape: s.value })}
                className={cn(
                  'flex-1 flex flex-col items-center px-2 py-1 rounded text-[11px] transition-colors',
                  conn.shape === s.value
                    ? 'bg-coral text-bg font-medium'
                    : 'text-text-3 hover:text-text-2',
                )}
              >
                <span className="text-base leading-tight">{s.icon}</span>
                <span className="text-[9.5px] mt-0.5 leading-none">{s.label}</span>
              </button>
            ))}
          </div>
        </div>

        {/* Label */}
        <div>
          <SectionLabel className="mb-1.5">Label</SectionLabel>
          <textarea
            value={label}
            onChange={(e) => handleLabelChange(e.target.value)}
            rows={2}
            className="w-full bg-surface border border-border-base rounded-md px-2.5 py-2 text-[12.5px] text-text-2 min-h-[56px] resize-none placeholder:text-text-4 focus:outline-none focus:border-border-hi transition-colors"
            placeholder="Edge label..."
          />
        </div>

        {/* Label size */}
        <div>
          <SectionLabel className="mb-1.5">
            Label size: {conn.label_size.toFixed(0)}px
          </SectionLabel>
          <div className="relative w-full">
            <input
              type="range"
              min={8}
              max={20}
              step={1}
              value={conn.label_size}
              onChange={(e) => handleUpdate({ label_size: parseFloat(e.target.value) })}
              style={{ background: sliderBg }}
              className={[
                'w-full h-1.5 rounded-full appearance-none cursor-pointer outline-none',
                'focus-visible:ring-2 focus-visible:ring-coral/40 focus-visible:ring-offset-2 focus-visible:ring-offset-panel',
                // Runnable-track – webkit
                '[&::-webkit-slider-runnable-track]:h-1.5 [&::-webkit-slider-runnable-track]:rounded-full',
                '[&::-webkit-slider-runnable-track]:bg-transparent',
                // Runnable-track – moz
                '[&::-moz-range-track]:h-1.5 [&::-moz-range-track]:rounded-full',
                '[&::-moz-range-track]:bg-transparent',
                // Thumb – webkit
                '[&::-webkit-slider-thumb]:appearance-none',
                '[&::-webkit-slider-thumb]:w-[14px] [&::-webkit-slider-thumb]:h-[14px]',
                '[&::-webkit-slider-thumb]:-mt-[4px]',
                '[&::-webkit-slider-thumb]:rounded-full',
                '[&::-webkit-slider-thumb]:bg-coral',
                '[&::-webkit-slider-thumb]:border-2 [&::-webkit-slider-thumb]:border-panel',
                '[&::-webkit-slider-thumb]:shadow-[0_0_0_2px_rgba(255,107,53,0.35),0_2px_6px_rgba(0,0,0,0.5)]',
                '[&::-webkit-slider-thumb]:transition-transform [&::-webkit-slider-thumb]:hover:scale-110',
                // Thumb – moz
                '[&::-moz-range-thumb]:w-[14px] [&::-moz-range-thumb]:h-[14px]',
                '[&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:border-2',
                '[&::-moz-range-thumb]:bg-coral [&::-moz-range-thumb]:border-panel',
                '[&::-moz-range-thumb]:cursor-pointer',
              ].join(' ')}
            />
          </div>
        </div>

        {/* Protocols — multi-select because real edges often carry more
            than one (HTTP over TLS, gRPC over HTTP/2, Kafka over TCP…).
            Default filter is `category=protocol` but the picker can widen
            scope when a tool-tagged row (Envoy, Traefik) is needed. */}
        <div>
          <SectionLabel className="mb-1.5">Protocols</SectionLabel>
          <TechnologyPicker
            mode={{
              multi: true,
              value: conn.protocol_ids ?? [],
              onChange: (ids) => handleUpdate({ protocol_ids: ids }),
            }}
            restrictCategory="protocol"
            placeholder="Search HTTP, gRPC, Kafka…"
          />
        </div>

        {/* Via (pass-through objects) */}
        <div>
          <SectionLabel className="mb-1.5">Via (pass-through)</SectionLabel>
          <ViaSelector
            selected={conn.via_object_ids || []}
            sourceId={conn.source_id}
            targetId={conn.target_id}
            allObjects={objects}
            onChange={(ids) => handleUpdate({ via_object_ids: ids })}
          />
        </div>

      </div>

      {/* ── Delete footer ── */}
      <div className="p-4 border-t border-border-base">
        <button
          onClick={handleDelete}
          className="w-full px-3 py-2 rounded-md text-[12.5px] font-mono border border-accent-pink/40 text-accent-pink hover:bg-accent-pink-glow transition-colors"
        >
          Delete connection
        </button>
      </div>
    </div>
  )
}

// ─── ViaSelector ──────────────────────────────────────────────────────────────

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
      {/* Selected chips */}
      {selectedObjects.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-2">
          {selectedObjects.map((obj) => (
            <span
              key={obj.id}
              className="inline-flex items-center gap-1 px-2 py-[3px] border border-border-hi rounded-md font-mono text-[10.5px] text-text-base bg-surface"
            >
              {obj.name}
              <button
                onClick={() => onChange(selected.filter((id) => id !== obj.id))}
                className="text-text-4 hover:text-text-2 leading-none transition-colors"
                aria-label={`Remove ${obj.name}`}
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}

      {/* Picker toggle */}
      <button
        onClick={() => setShowPicker(!showPicker)}
        className={cn(
          'inline-flex items-center gap-1.5 px-2.5 py-1 border rounded-md font-mono text-[10.5px] transition-colors',
          showPicker
            ? 'border-border-hi text-text-2 bg-surface-hi'
            : 'border-dashed border-border-hi text-text-3 hover:border-coral hover:text-coral',
        )}
      >
        {showPicker ? 'Cancel' : '+ Select objects'}
      </button>

      {/* Picker dropdown */}
      {showPicker && (
        <div className="mt-2 bg-panel border border-border-base rounded-md shadow-popup p-2 max-h-48 overflow-auto">
          {available.length === 0 ? (
            <div className="text-[11.5px] text-text-4 p-1">No available objects</div>
          ) : (
            available.map((obj) => (
              <button
                key={obj.id}
                onClick={() => {
                  onChange([...selected, obj.id])
                  setShowPicker(false)
                }}
                className="block w-full text-left text-[12px] px-2 py-1.5 rounded text-text-2 hover:bg-surface-hi hover:text-text-base transition-colors"
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
