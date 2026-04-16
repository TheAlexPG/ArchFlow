import { Handle, NodeResizer, Position, type NodeProps } from '@xyflow/react'
import type { C4NodeData } from './C4Node'

export function GroupNode({ data, selected }: NodeProps) {
  const obj = (data as C4NodeData).object

  return (
    <div
      style={{
        width: '100%',
        height: '100%',
        minWidth: 300,
        minHeight: 200,
        border: `2px dashed ${selected ? '#3b82f6' : '#404040'}`,
        borderRadius: 12,
        background: 'rgba(38, 38, 38, 0.5)',
        padding: 12,
        boxSizing: 'border-box',
      }}
    >
      <NodeResizer
        color="#3b82f6"
        isVisible={selected}
        minWidth={200}
        minHeight={120}
      />
      <Handle type="source" position={Position.Top} id="top" className="!bg-neutral-500 !w-2 !h-2" />
      <Handle type="source" position={Position.Bottom} id="bottom" className="!bg-neutral-500 !w-2 !h-2" />
      <Handle type="source" position={Position.Left} id="left" className="!bg-neutral-500 !w-2 !h-2" />
      <Handle type="source" position={Position.Right} id="right" className="!bg-neutral-500 !w-2 !h-2" />

      <div style={{
        fontSize: 11, color: '#737373', fontWeight: 500, textTransform: 'uppercase',
        letterSpacing: '0.05em', marginBottom: 4,
      }}>
        Group
      </div>
      <div style={{ fontSize: 14, fontWeight: 600, color: '#e5e5e5' }}>
        {obj.name}
      </div>
      {obj.description && (
        <div style={{ fontSize: 11, color: '#737373', marginTop: 4 }}>
          {obj.description}
        </div>
      )}
    </div>
  )
}
