import { Handle, NodeResizer, Position, useNodeId, type NodeProps } from '@xyflow/react'
import { useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import type { C4NodeData } from './C4Node'
import { useSaveDiagramSize, useUpdateObject } from '../../hooks/use-api'
import { stripHtml } from './node-utils'

export function GroupNode({ data, selected }: NodeProps) {
  const obj = (data as C4NodeData).object
  const params = useParams<{ diagramId?: string }>()
  const nodeId = useNodeId()
  const saveSize = useSaveDiagramSize()
  const updateObject = useUpdateObject()

  const [editing, setEditing] = useState(false)
  const [editValue, setEditValue] = useState(obj.name)
  const inputRef = useRef<HTMLInputElement>(null)

  const handleDoubleClick = () => {
    setEditValue(obj.name)
    setEditing(true)
    // Focus in next tick so the input is mounted
    setTimeout(() => inputRef.current?.focus(), 0)
  }

  const commitEdit = () => {
    const trimmed = editValue.trim()
    if (trimmed && trimmed !== obj.name) {
      updateObject.mutate({ id: obj.id, name: trimmed })
    }
    setEditing(false)
  }

  const cancelEdit = () => {
    setEditValue(obj.name)
    setEditing(false)
  }

  return (
    <div
      style={{
        width: '100%',
        height: '100%',
        minWidth: 300,
        minHeight: 200,
        border: `2px ${selected ? 'solid' : 'dashed'} ${selected ? '#3b82f6' : '#404040'}`,
        borderRadius: 12,
        background: 'rgba(38, 38, 38, 0.5)',
        boxSizing: 'border-box',
        display: 'flex',
        flexDirection: 'column',
        position: 'relative',
      }}
    >
      <NodeResizer
        color="#3b82f6"
        isVisible
        minWidth={200}
        minHeight={120}
        onResizeEnd={(_e, p) => {
          if (params.diagramId && nodeId) {
            saveSize.mutate({
              diagramId: params.diagramId,
              objectId: nodeId,
              width: p.width,
              height: p.height,
            })
          }
        }}
      />
      <Handle type="source" position={Position.Top} id="top" className="archflow-handle !bg-neutral-500 !w-2 !h-2" />
      <Handle type="source" position={Position.Bottom} id="bottom" className="archflow-handle !bg-neutral-500 !w-2 !h-2" />
      <Handle type="source" position={Position.Left} id="left" className="archflow-handle !bg-neutral-500 !w-2 !h-2" />
      <Handle type="source" position={Position.Right} id="right" className="archflow-handle !bg-neutral-500 !w-2 !h-2" />

      {/* Title area */}
      <div style={{ padding: '12px 14px 4px', flex: 1 }}>
        {editing ? (
          <input
            ref={inputRef}
            className="nodrag"
            value={editValue}
            onChange={(e) => setEditValue(e.target.value)}
            onBlur={commitEdit}
            onKeyDown={(e) => {
              if (e.key === 'Enter') commitEdit()
              if (e.key === 'Escape') cancelEdit()
            }}
            style={{
              fontSize: 14,
              fontWeight: 600,
              color: '#e5e5e5',
              background: 'rgba(59,130,246,0.1)',
              border: '1px solid #3b82f6',
              borderRadius: 4,
              outline: 'none',
              padding: '1px 4px',
              width: '100%',
              boxSizing: 'border-box',
            }}
          />
        ) : (
          <div
            style={{ fontSize: 14, fontWeight: 600, color: '#e5e5e5', cursor: 'text' }}
            onDoubleClick={handleDoubleClick}
            title="Double-click to rename"
          >
            {obj.name}
          </div>
        )}
        {obj.description && stripHtml(obj.description) && (
          <div
            className="node-desc-html"
            style={{ fontSize: 11, color: '#737373', marginTop: 4 }}
            dangerouslySetInnerHTML={{ __html: obj.description }}
          />
        )}
      </div>

      {/* Footer label — IcePanel-style, centered at the bottom */}
      <div
        style={{
          textAlign: 'center',
          padding: '4px 0 8px',
          fontSize: 10,
          color: '#525252',
          textTransform: 'uppercase',
          letterSpacing: '0.08em',
          userSelect: 'none',
        }}
      >
        Group
      </div>
    </div>
  )
}
