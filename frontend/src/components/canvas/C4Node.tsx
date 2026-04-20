import { Handle, NodeResizer, Position, useNodeId, type NodeProps } from '@xyflow/react'
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import type { ModelObject } from '../../types/model'
import { useSaveDiagramSize } from '../../hooks/use-api'
import { useCreateDiagram, useDiagrams } from '../../hooks/use-diagrams'
import { Modal } from '../common/Modal'
import { STATUS_COLORS, TYPE_BORDER_COLORS, TYPE_ICONS, stripHtml } from './node-utils'

export type C4NodeData = {
  object: ModelObject
}

// Object types that can have child diagrams drilled into them.
const DRILLABLE_TYPES = new Set(['system', 'app', 'store'])

// Determine what type of child diagram to create for a given object type.
function childDiagramType(objectType: string): 'container' | 'component' {
  return objectType === 'system' ? 'container' : 'component'
}

function defaultChildDiagramName(objectName: string, objectType: string): string {
  return objectType === 'system'
    ? `${objectName} · Containers`
    : `${objectName} · Components`
}

function drillTooltip(objectName: string, objectType: string): string {
  const childType = childDiagramType(objectType)
  return childType === 'container'
    ? `Create container diagram for ${objectName}`
    : `Create component diagram for ${objectName}`
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
  const createDiagram = useCreateDiagram()
  const [drillPickerOpen, setDrillPickerOpen] = useState(false)
  const [createModalOpen, setCreateModalOpen] = useState(false)
  const [newDiagramName, setNewDiagramName] = useState('')
  const [creating, setCreating] = useState(false)

  const canHaveChildren = DRILLABLE_TYPES.has(obj.type)

  const handleDrillDown = (e: React.MouseEvent) => {
    e.stopPropagation()
    if (childDiagrams.length === 0) {
      setNewDiagramName(defaultChildDiagramName(obj.name, obj.type))
      setCreateModalOpen(true)
    } else if (childDiagrams.length === 1) {
      navigate(`/diagram/${childDiagrams[0].id}`)
    } else {
      setDrillPickerOpen((v) => !v)
    }
  }

  const handleCreateDiagram = () => {
    if (!newDiagramName.trim()) return
    setCreating(true)
    createDiagram.mutate(
      {
        name: newDiagramName.trim(),
        type: childDiagramType(obj.type),
        scope_object_id: obj.id,
      },
      {
        onSuccess: (diagram) => {
          setCreating(false)
          setCreateModalOpen(false)
          navigate(`/diagram/${diagram.id}`)
        },
        onError: () => {
          setCreating(false)
        },
      },
    )
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

      {/* Status indicator */}
      <div
        className="absolute -top-1.5 -right-1.5 w-3 h-3 rounded-full border-2 border-neutral-900"
        style={{ backgroundColor: statusColor }}
        title={obj.status}
      />

      {/* Drill-down zoom icon — shown for all drillable types */}
      {canHaveChildren && (
        <div className="absolute -top-2 -left-2">
          <button
            onClick={handleDrillDown}
            onMouseDown={(e) => e.stopPropagation()}
            className="nodrag text-white rounded-full w-5 h-5 flex items-center justify-center text-[10px] font-bold shadow-lg border"
            style={{
              background: childDiagrams.length === 0 ? '#525252' : '#2563eb',
              borderColor: childDiagrams.length === 0 ? '#737373' : '#1d4ed8',
            }}
            title={drillButtonTitle}
          >
            {childDiagrams.length === 0 ? '+' : '\u{1F50D}'}
          </button>
          {drillPickerOpen && (
            <div
              onMouseDown={(e) => e.stopPropagation()}
              onClick={(e) => e.stopPropagation()}
              className="nodrag"
              style={{
                position: 'absolute',
                top: 22,
                left: 0,
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
                  setNewDiagramName(defaultChildDiagramName(obj.name, obj.type))
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

      {/* Create child diagram modal — rendered outside the node via portal-like
          positioning; stopPropagation on the Modal backdrop handles node clicks. */}
      <Modal
        open={createModalOpen}
        onClose={() => !creating && setCreateModalOpen(false)}
        title={`Create ${childDiagramType(obj.type)} diagram`}
        width={400}
        footer={
          <>
            <button
              onClick={() => setCreateModalOpen(false)}
              disabled={creating}
              style={{
                background: 'transparent', border: '1px solid #333', borderRadius: 6,
                color: '#a3a3a3', cursor: 'pointer', fontSize: 13, padding: '6px 14px',
                opacity: creating ? 0.5 : 1,
              }}
            >
              Cancel
            </button>
            <button
              onClick={handleCreateDiagram}
              disabled={creating || !newDiagramName.trim()}
              style={{
                background: '#2563eb', border: '1px solid #1d4ed8', borderRadius: 6,
                color: 'white', cursor: 'pointer', fontSize: 13, padding: '6px 14px',
                opacity: creating || !newDiagramName.trim() ? 0.5 : 1,
              }}
            >
              {creating ? 'Creating...' : 'Create'}
            </button>
          </>
        }
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <label style={{ fontSize: 12, color: '#a3a3a3' }}>
            Diagram name
          </label>
          <input
            value={newDiagramName}
            onChange={(e) => setNewDiagramName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleCreateDiagram()
            }}
            autoFocus
            placeholder="Enter diagram name..."
            style={{
              background: '#0a0a0a', border: '1px solid #333', borderRadius: 6,
              color: '#e5e5e5', fontSize: 13, padding: '8px 10px', outline: 'none',
              width: '100%', boxSizing: 'border-box',
            }}
          />
          <div style={{ fontSize: 11, color: '#525252' }}>
            Scoped to: {obj.name}
          </div>
        </div>
      </Modal>
    </div>
  )
}
