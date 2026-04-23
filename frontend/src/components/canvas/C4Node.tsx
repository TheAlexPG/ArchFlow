import { Handle, NodeResizer, Position, useNodeId, type NodeProps } from '@xyflow/react'
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import type { ModelObject } from '../../types/model'
import { useSaveDiagramSize } from '../../hooks/use-api'
import { useDiagrams } from '../../hooks/use-diagrams'
import { useCanvasStore } from '../../stores/canvas-store'
import { Pill, PillDot } from '../ui'
import {
  CreateChildDiagramModal,
  DRILLABLE_TYPES,
  defaultChildDiagramName,
} from '../drafts/CreateChildDiagramModal'
import { STATUS_COLORS, TYPE_ICONS, stripHtml } from './node-utils'

export type C4NodeData = {
  object: ModelObject
}

function drillTooltip(objectName: string, objectType: string): string {
  return objectType === 'system'
    ? `Create container diagram for ${objectName}`
    : `Create component diagram for ${objectName}`
}

// Crisp plus SVG icon for the drill button.
function PlusIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 13 13" fill="none" xmlns="http://www.w3.org/2000/svg">
      <line x1="6.5" y1="1" x2="6.5" y2="12" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      <line x1="1" y1="6.5" x2="12" y2="6.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  )
}

// Crisp magnifying-glass SVG icon for the drill button.
function ZoomIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 13 13" fill="none" xmlns="http://www.w3.org/2000/svg">
      <circle cx="5.5" cy="5.5" r="3.5" stroke="currentColor" strokeWidth="1.6" />
      <line x1="8.5" y1="8.5" x2="12" y2="12" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  )
}

// Per-C4-type color dot on the top pill. Keeps a compact visual taxonomy:
// SYSTEM → purple, CONTAINER-like (app/store) → coral, COMPONENT → blue.
// var(--color-*) is resolved against the Tailwind v4 theme tokens.
const TYPE_DOT_COLOR: Record<string, string> = {
  system: 'var(--color-accent-purple)',
  app: 'var(--color-coral)',
  store: 'var(--color-coral)',
  component: 'var(--color-accent-blue)',
  group: 'var(--color-text-3)',
  actor: 'var(--color-accent-purple)',
  external_system: 'var(--color-text-3)',
}

const TYPE_PILL_LABEL: Record<string, string> = {
  system: 'SYSTEM',
  app: 'CONTAINER',
  store: 'CONTAINER',
  component: 'COMPONENT',
  group: 'GROUP',
  actor: 'ACTOR',
  external_system: 'EXTERNAL',
}

export function C4Node({ data, selected }: NodeProps) {
  const obj = (data as C4NodeData).object
  const statusColor = STATUS_COLORS[obj.status]
  const navigate = useNavigate()
  const params = useParams<{ diagramId?: string }>()
  const nodeId = useNodeId()
  const saveSize = useSaveDiagramSize()
  const { data: childDiagrams = [] } = useDiagrams(obj.id)
  const [drillPickerOpen, setDrillPickerOpen] = useState(false)
  const [createModalOpen, setCreateModalOpen] = useState(false)
  // Per-node remote editors — shown as "● editing" in the footer when
  // another user has this node in their selection broadcast.
  const remoteEditors = useCanvasStore(
    (s) => (nodeId ? s.remoteNodeEditors[nodeId] : undefined),
  )

  const canHaveChildren = DRILLABLE_TYPES.has(obj.type)

  const handleDrillDown = (e: React.MouseEvent) => {
    e.stopPropagation()
    if (childDiagrams.length === 0) {
      setCreateModalOpen(true)
    } else if (childDiagrams.length === 1) {
      navigate(`/diagram/${childDiagrams[0].id}`)
    } else {
      setDrillPickerOpen((v) => !v)
    }
  }

  // Double-click the node body → drill into existing child (if any).
  const handleDoubleClick = (e: React.MouseEvent) => {
    if (!canHaveChildren || childDiagrams.length === 0) return
    e.stopPropagation()
    navigate(`/diagram/${childDiagrams[0].id}`)
  }

  const drillButtonTitle =
    childDiagrams.length === 0
      ? drillTooltip(obj.name, obj.type)
      : `Zoom into (${childDiagrams.length} diagram${childDiagrams.length > 1 ? 's' : ''})`

  const typeDotColor = TYPE_DOT_COLOR[obj.type] ?? 'var(--color-text-3)'
  const typeLabel = TYPE_PILL_LABEL[obj.type] ?? obj.type.toUpperCase()
  const metaParts = obj.technology && obj.technology.length > 0 ? obj.technology : []

  return (
    <div
      className={[
        'relative rounded-lg border px-4 py-3 bg-surface',
        'transition-all duration-150 ease-[ease]',
        'w-full h-full box-border',
        selected
          ? 'border-coral shadow-node-selected'
          : 'border-border-base hover:border-border-hi',
      ].join(' ')}
      style={{
        minWidth: 160,
        minHeight: 60,
      }}
      onDoubleClick={handleDoubleClick}
      title={
        canHaveChildren && childDiagrams.length >= 1
          ? `Double-click to open ${childDiagrams[0].name}`
          : undefined
      }
    >
      {/* Always rendered so DOM is stable on select/deselect — controls are
          hidden via CSS when the node isn't selected (see index.css). */}
      <NodeResizer
        color="var(--color-coral)"
        isVisible
        minWidth={160}
        minHeight={60}
        onResizeEnd={(_e, params_) => {
          if (params.diagramId && nodeId) {
            saveSize.mutate({
              diagramId: params.diagramId,
              objectId: nodeId,
              width: params_.width,
              height: params_.height,
            })
          }
        }}
      />
      {/* With connectionMode="loose" these work as both source and target */}
      <Handle type="source" position={Position.Top} id="top" className="archflow-handle !bg-neutral-500 !w-2 !h-2" />
      <Handle type="source" position={Position.Bottom} id="bottom" className="archflow-handle !bg-neutral-500 !w-2 !h-2" />
      <Handle type="source" position={Position.Left} id="left" className="archflow-handle !bg-neutral-500 !w-2 !h-2" />
      <Handle type="source" position={Position.Right} id="right" className="archflow-handle !bg-neutral-500 !w-2 !h-2" />

      {/* Status indicator — top-right */}
      <div
        className="absolute -top-1.5 -right-1.5 w-3 h-3 rounded-full border-2 border-bg"
        style={{ backgroundColor: statusColor }}
        title={obj.status}
      />

      {/* Drill-down button — bottom-right corner */}
      {canHaveChildren && (
        <div className="absolute -bottom-2 -right-2">
          <button
            onClick={handleDrillDown}
            onMouseDown={(e) => e.stopPropagation()}
            className="nodrag rounded-full w-6 h-6 flex items-center justify-center shadow-lg border border-border-base bg-panel text-text-2 hover:bg-surface-hi hover:text-text-base hover:border-coral transition-colors"
            title={drillButtonTitle}
          >
            {childDiagrams.length === 0 ? <PlusIcon /> : <ZoomIcon />}
          </button>
          {drillPickerOpen && (
            <div
              onMouseDown={(e) => e.stopPropagation()}
              onClick={(e) => e.stopPropagation()}
              className="nodrag absolute right-0 min-w-[180px] bg-panel border border-border-base rounded-md shadow-popup p-1 z-[100]"
              style={{ bottom: 28 }}
            >
              <div className="font-mono text-[10px] text-text-3 px-2 py-1 uppercase tracking-[0.05em]">
                Open diagram
              </div>
              {/* Option to create a new child diagram */}
              <button
                onClick={() => {
                  setDrillPickerOpen(false)
                  setCreateModalOpen(true)
                }}
                className="block w-full text-left px-2.5 py-1.5 rounded text-[12px] text-coral hover:bg-surface-hi border-b border-border-base mb-0.5"
              >
                + New child diagram
              </button>
              {childDiagrams.map((d) => (
                <button
                  key={d.id}
                  onClick={() => {
                    setDrillPickerOpen(false)
                    navigate(`/diagram/${d.id}`)
                  }}
                  className="block w-full text-left px-2.5 py-1.5 rounded text-[12px] text-text-2 hover:bg-surface-hi hover:text-text-base"
                >
                  {d.name}
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Top row: type pill + icon */}
      <div className="flex items-center justify-between mb-1.5 gap-2">
        <Pill variant="neutral" className="!py-[2px] !px-[6px] !text-[9.5px]">
          <PillDot color={typeDotColor} />
          {typeLabel}
        </Pill>
        <span className="text-base shrink-0 opacity-50 leading-none">{TYPE_ICONS[obj.type]}</span>
      </div>

      {/* Name */}
      <div className="text-[14px] font-semibold tracking-tight text-text-base truncate">
        {obj.name}
      </div>

      {/* Description (TipTap HTML preview) */}
      {obj.description && stripHtml(obj.description) && (
        <div
          className="node-desc-html text-[11px] text-text-2 mt-0.5 leading-relaxed"
          dangerouslySetInnerHTML={{ __html: obj.description }}
        />
      )}

      {/* Metadata row — tech stack joined with · and optional editing indicator */}
      {(metaParts.length > 0 || (remoteEditors && remoteEditors.length > 0)) && (
        <div className="flex items-center justify-between gap-2 mt-2 font-mono text-[10px] text-text-3">
          <span className="truncate">{metaParts.join(' · ')}</span>
          {remoteEditors && remoteEditors.length > 0 && (
            <span
              className="flex items-center gap-1 text-coral shrink-0"
              title={`${remoteEditors.join(', ')} editing`}
            >
              <span className="inline-block w-1.5 h-1.5 rounded-full bg-coral" />
              editing
            </span>
          )}
        </div>
      )}

      {/* Create child diagram modal */}
      <CreateChildDiagramModal
        object={obj}
        open={createModalOpen}
        onClose={() => setCreateModalOpen(false)}
      />
    </div>
  )
}

// Re-export defaultChildDiagramName so existing callers still compile.
export { defaultChildDiagramName }
