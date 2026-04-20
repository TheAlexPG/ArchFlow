import { Handle, Position, type NodeProps } from '@xyflow/react'
import type { C4NodeData } from './C4Node'
import { STATUS_COLORS } from './node-utils'

export function ActorNode({ data, selected }: NodeProps) {
  const obj = (data as C4NodeData).object
  const statusColor = STATUS_COLORS[obj.status]

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: 4,
        minWidth: 100,
        padding: 8,
        borderRadius: 8,
        border: `1px solid ${selected ? '#3b82f6' : 'transparent'}`,
        position: 'relative',
      }}
    >
      <Handle type="source" position={Position.Top} id="top" className="archflow-handle !bg-neutral-500 !w-2 !h-2" />
      <Handle type="source" position={Position.Bottom} id="bottom" className="archflow-handle !bg-neutral-500 !w-2 !h-2" />
      <Handle type="source" position={Position.Left} id="left" className="archflow-handle !bg-neutral-500 !w-2 !h-2" />
      <Handle type="source" position={Position.Right} id="right" className="archflow-handle !bg-neutral-500 !w-2 !h-2" />

      {/* Status dot */}
      <div
        style={{
          position: 'absolute', top: 2, right: 2, width: 8, height: 8,
          borderRadius: 4, backgroundColor: statusColor,
        }}
        title={obj.status}
      />

      {/* Circle with person icon */}
      <div style={{
        width: 56, height: 56, borderRadius: '50%',
        background: '#1f2937', border: `2px solid #8b5cf6`,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontSize: 28,
      }}>
        👤
      </div>

      {/* Name */}
      <div style={{
        fontSize: 12, fontWeight: 600, color: '#e5e5e5',
        textAlign: 'center', maxWidth: 120,
      }}>
        {obj.name}
      </div>

      {/* Type label */}
      <div style={{ fontSize: 10, color: '#737373', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
        Actor
      </div>
    </div>
  )
}
