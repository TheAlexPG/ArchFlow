import { Handle, Position, useNodeId, type NodeProps } from '@xyflow/react'
import { useCanvasStore } from '../../stores/canvas-store'
import type { C4NodeData } from './C4Node'
import { STATUS_COLORS } from './node-utils'

export function ActorNode({ data, selected }: NodeProps) {
  const obj = (data as C4NodeData).object
  const statusColor = STATUS_COLORS[obj.status]
  const nodeId = useNodeId()
  const remoteEditors = useCanvasStore(
    (s) => (nodeId ? s.remoteNodeEditors[nodeId] : undefined),
  )

  // Selected swaps the purple border/glow for the coral double-glow used
  // across the canvas. Preserve DOM structure so React Flow selection state
  // continues to flow through `selected`.
  const circleStyle = selected
    ? {
        background:
          'radial-gradient(circle at 30% 30%, #2a2a32, var(--color-panel))',
        border: '1.5px solid var(--color-coral)',
        boxShadow: 'var(--shadow-node-selected)',
      }
    : {
        background:
          'radial-gradient(circle at 30% 30%, #2a2a32, var(--color-panel))',
        border: '1.5px solid var(--color-accent-purple)',
        boxShadow: '0 0 24px var(--color-accent-purple-glow)',
      }

  return (
    <div className="flex flex-col items-center gap-1 p-2 relative min-w-[100px]">
      <Handle type="source" position={Position.Top} id="top" className="archflow-handle !bg-neutral-500 !w-2 !h-2" />
      <Handle type="source" position={Position.Bottom} id="bottom" className="archflow-handle !bg-neutral-500 !w-2 !h-2" />
      <Handle type="source" position={Position.Left} id="left" className="archflow-handle !bg-neutral-500 !w-2 !h-2" />
      <Handle type="source" position={Position.Right} id="right" className="archflow-handle !bg-neutral-500 !w-2 !h-2" />

      {/* Status dot */}
      <div
        className="absolute top-0.5 right-0.5 w-2 h-2 rounded-full"
        style={{ backgroundColor: statusColor }}
        title={obj.status}
      />

      {/* Circle with person icon — purple glow signals "human / actor". */}
      <div
        className="w-14 h-14 rounded-full flex items-center justify-center transition-all duration-150 ease-[ease]"
        style={circleStyle}
      >
        <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke={selected ? 'var(--color-coral)' : 'var(--color-accent-purple)'} strokeWidth="1.6">
          <circle cx="12" cy="7" r="4" />
          <path d="M5.5 21c.83-4 4-6 6.5-6s5.67 2 6.5 6" />
        </svg>
      </div>

      {/* Name */}
      <div className="text-[13px] font-medium text-text-base text-center max-w-[120px] truncate">
        {obj.name}
      </div>

      {/* Type label */}
      <div className="font-mono text-[10px] text-text-3 uppercase tracking-[0.05em]">
        Actor
      </div>

      {/* Live-edit presence */}
      {remoteEditors && remoteEditors.length > 0 && (
        <div
          className="flex items-center gap-1 font-mono text-[10px] text-coral"
          title={`${remoteEditors.join(', ')} editing`}
        >
          <span className="inline-block w-1.5 h-1.5 rounded-full bg-coral" />
          editing
        </div>
      )}
    </div>
  )
}
