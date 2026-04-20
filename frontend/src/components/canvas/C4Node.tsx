import { Handle, NodeResizer, Position, useNodeId, type NodeProps } from '@xyflow/react'
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import type { ModelObject } from '../../types/model'
import { useSaveDiagramSize } from '../../hooks/use-api'
import { useDiagrams } from '../../hooks/use-diagrams'
import {
  CreateChildDiagramModal,
  DRILLABLE_TYPES,
  defaultChildDiagramName,
} from '../drafts/CreateChildDiagramModal'
import { STATUS_COLORS, TYPE_BORDER_COLORS, TYPE_ICONS, stripHtml } from './node-utils'

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

export function C4Node({ data, selected }: NodeProps) {
  const obj = (data as C4NodeData).object
  const borderColor = TYPE_BORDER_COLORS[obj.type]
  const statusColor = STATUS_COLORS[obj.status]
  const navigate = useNavigate()
  const params = useParams<{ diagramId?: string }>()
  const nodeId = useNodeId()
  const saveSize = useSaveDiagramSize()
  const { data: childDiagrams = [] } = useDiagrams(obj.id)
  const [drillPickerOpen, setDrillPickerOpen] = useState(false)
  const [createModalOpen, setCreateModalOpen] = useState(false)

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

  return (
    <div
      className="relative rounded-lg border-2 px-4 py-3 shadow-lg"
      style={{
        background: '#171717',
        borderColor: selected ? '#3b82f6' : borderColor,
        width: '100%',
        height: '100%',
        minWidth: 160,
        minHeight: 60,
        boxSizing: 'border-box',
      }}
      onDoubleClick={handleDoubleClick}
    >
      {/* Always rendered so DOM is stable on select/deselect — controls are
          hidden via CSS when the node isn't selected (see index.css). */}
      <NodeResizer
        color="#3b82f6"
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
      <Handle type="source" position={Position.Top} id="top" className="!bg-neutral-500 !w-2 !h-2" />
      <Handle type="source" position={Position.Bottom} id="bottom" className="!bg-neutral-500 !w-2 !h-2" />
      <Handle type="source" position={Position.Left} id="left" className="!bg-neutral-500 !w-2 !h-2" />
      <Handle type="source" position={Position.Right} id="right" className="!bg-neutral-500 !w-2 !h-2" />

      {/* Status indicator — top-right */}
      <div
        className="absolute -top-1.5 -right-1.5 w-3 h-3 rounded-full border-2 border-neutral-900"
        style={{ backgroundColor: statusColor }}
        title={obj.status}
      />

      {/* Drill-down button — bottom-right corner */}
      {canHaveChildren && (
        <div className="absolute -bottom-2 -right-2">
          <button
            onClick={handleDrillDown}
            onMouseDown={(e) => e.stopPropagation()}
            className="nodrag rounded-full w-6 h-6 flex items-center justify-center shadow-lg border transition-colors"
            style={{
              background: '#1e3a5f',
              borderColor: '#3b82f6',
              color: '#93c5fd',
              boxShadow: '0 2px 6px rgba(0,0,0,0.4)',
            }}
            onMouseEnter={(e) => {
              ;(e.currentTarget as HTMLButtonElement).style.background = '#2563eb'
              ;(e.currentTarget as HTMLButtonElement).style.color = '#fff'
            }}
            onMouseLeave={(e) => {
              ;(e.currentTarget as HTMLButtonElement).style.background = '#1e3a5f'
              ;(e.currentTarget as HTMLButtonElement).style.color = '#93c5fd'
            }}
            title={drillButtonTitle}
          >
            {childDiagrams.length === 0 ? <PlusIcon /> : <ZoomIcon />}
          </button>
          {drillPickerOpen && (
            <div
              onMouseDown={(e) => e.stopPropagation()}
              onClick={(e) => e.stopPropagation()}
              className="nodrag"
              style={{
                position: 'absolute',
                bottom: 28,
                right: 0,
                minWidth: 180,
                background: '#1a1a1a',
                border: '1px solid #333',
                borderRadius: 6,
                boxShadow: '0 8px 24px rgba(0,0,0,0.5)',
                padding: 4,
                zIndex: 100,
              }}
            >
              <div style={{ fontSize: 10, color: '#737373', padding: '4px 8px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                Open diagram
              </div>
              {/* Option to create a new child diagram */}
              <button
                onClick={() => {
                  setDrillPickerOpen(false)
                  setCreateModalOpen(true)
                }}
                style={{
                  display: 'block',
                  width: '100%',
                  textAlign: 'left',
                  padding: '6px 10px',
                  background: 'transparent',
                  border: 'none',
                  borderRadius: 4,
                  color: '#60a5fa',
                  fontSize: 12,
                  cursor: 'pointer',
                  borderBottom: '1px solid #262626',
                  marginBottom: 2,
                }}
                onMouseEnter={(e) => (e.currentTarget.style.background = '#1e3a5f')}
                onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
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
                  style={{
                    display: 'block',
                    width: '100%',
                    textAlign: 'left',
                    padding: '6px 10px',
                    background: 'transparent',
                    border: 'none',
                    borderRadius: 4,
                    color: '#d4d4d4',
                    fontSize: 12,
                    cursor: 'pointer',
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = '#262626')}
                  onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                >
                  {d.name}
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Type icon + Name */}
      <div className="flex items-start gap-2">
        <span className="text-lg shrink-0 mt-0.5 opacity-60">{TYPE_ICONS[obj.type]}</span>
        <div className="min-w-0">
          <div className="font-semibold text-sm text-neutral-100 truncate">{obj.name}</div>
          {obj.description && stripHtml(obj.description) && (
            <div
              className="node-desc-html text-xs text-neutral-400 mt-0.5"
              dangerouslySetInnerHTML={{ __html: obj.description }}
            />
          )}
        </div>
      </div>

      {/* Technology tags */}
      {obj.technology && obj.technology.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-2">
          {obj.technology.map((tech) => (
            <span
              key={tech}
              className="text-[10px] px-1.5 py-0.5 rounded bg-neutral-800 text-neutral-400"
            >
              {tech}
            </span>
          ))}
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
