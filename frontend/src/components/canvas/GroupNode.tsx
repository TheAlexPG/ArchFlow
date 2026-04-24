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
      className={[
        'w-full h-full flex flex-col relative box-border',
        'rounded-xl transition-all duration-150 ease-[ease]',
        'bg-surface/40',
        selected
          ? 'border-2 border-solid border-coral shadow-node-selected'
          : 'border-2 border-dashed border-border-hi',
      ].join(' ')}
      style={{
        minWidth: 300,
        minHeight: 200,
      }}
    >
      <NodeResizer
        color="var(--color-coral)"
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
      <div className="flex-1 px-3.5 pt-3 pb-1">
        {editing ? (
          <input
            ref={inputRef}
            className="nodrag w-full box-border font-mono uppercase tracking-[0.04em] text-[11px] text-text-base bg-surface-hi border border-coral rounded px-1.5 py-0.5 outline-none"
            value={editValue}
            onChange={(e) => setEditValue(e.target.value)}
            onBlur={commitEdit}
            onKeyDown={(e) => {
              if (e.key === 'Enter') commitEdit()
              if (e.key === 'Escape') cancelEdit()
            }}
          />
        ) : (
          <div
            className="font-mono text-[11px] uppercase tracking-[0.04em] text-text-3 cursor-text select-none"
            onDoubleClick={handleDoubleClick}
            title="Double-click to rename"
          >
            {obj.name}
          </div>
        )}
        {obj.description && stripHtml(obj.description) && (
          <div
            className="node-desc-html text-[11px] text-text-3 mt-1 leading-relaxed"
            dangerouslySetInnerHTML={{ __html: obj.description }}
          />
        )}
      </div>

      {/* Footer label — IcePanel-style, centered at the bottom */}
      <div className="text-center py-2 font-mono text-[10px] text-text-4 uppercase tracking-[0.08em] select-none">
        Group
      </div>
    </div>
  )
}
