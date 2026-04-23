import { Handle, Position, useNodeId, type NodeProps } from '@xyflow/react'
import { useCanvasStore } from '../../stores/canvas-store'
import { Pill, PillDot } from '../ui'
import type { C4NodeData } from './C4Node'
import { STATUS_COLORS, stripHtml } from './node-utils'

export function ExternalSystemNode({ data, selected }: NodeProps) {
  const obj = (data as C4NodeData).object
  const statusColor = STATUS_COLORS[obj.status]
  const nodeId = useNodeId()
  const remoteEditors = useCanvasStore(
    (s) => (nodeId ? s.remoteNodeEditors[nodeId] : undefined),
  )

  const metaParts = obj.technology && obj.technology.length > 0 ? obj.technology : []

  return (
    <div
      className={[
        'relative min-w-[160px] max-w-[240px] px-4 py-3 bg-surface',
        'rounded-2xl border',
        'transition-all duration-150 ease-[ease]',
        selected
          ? 'border-coral border-solid shadow-node-selected'
          : 'border-dashed border-text-3 hover:border-border-hi',
      ].join(' ')}
    >
      <Handle type="source" position={Position.Top} id="top" className="archflow-handle !bg-neutral-500 !w-2 !h-2" />
      <Handle type="source" position={Position.Bottom} id="bottom" className="archflow-handle !bg-neutral-500 !w-2 !h-2" />
      <Handle type="source" position={Position.Left} id="left" className="archflow-handle !bg-neutral-500 !w-2 !h-2" />
      <Handle type="source" position={Position.Right} id="right" className="archflow-handle !bg-neutral-500 !w-2 !h-2" />

      {/* Status */}
      <div
        className="absolute -top-1.5 -right-1.5 w-3 h-3 rounded-full border-2 border-bg"
        style={{ backgroundColor: statusColor }}
        title={obj.status}
      />

      <div className="flex items-center justify-between mb-1.5 gap-2">
        <Pill variant="neutral" className="!py-[2px] !px-[6px] !text-[9.5px]">
          <PillDot color="var(--color-text-3)" />
          EXTERNAL
        </Pill>
        <span className="text-base shrink-0 opacity-50 leading-none">☁</span>
      </div>

      <div className="text-[14px] font-semibold tracking-tight text-text-base truncate">
        {obj.name}
      </div>

      {obj.description && stripHtml(obj.description) && (
        <div
          className="node-desc-html text-[11px] text-text-2 mt-0.5 leading-relaxed"
          dangerouslySetInnerHTML={{ __html: obj.description }}
        />
      )}

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
    </div>
  )
}
