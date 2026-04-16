import { Handle, Position, type NodeProps } from '@xyflow/react'
import type { ModelObject } from '../../types/model'
import { STATUS_COLORS, TYPE_BORDER_COLORS, TYPE_ICONS } from './node-utils'

export type C4NodeData = {
  object: ModelObject
}

export function C4Node({ data, selected }: NodeProps) {
  const obj = (data as C4NodeData).object
  const borderColor = TYPE_BORDER_COLORS[obj.type]
  const statusColor = STATUS_COLORS[obj.status]

  return (
    <div
      className={`
        relative rounded-lg border-2 bg-neutral-900 px-4 py-3 min-w-[160px] max-w-[240px]
        shadow-lg transition-shadow
        ${selected ? 'shadow-blue-500/30 ring-1 ring-blue-500' : 'shadow-black/30'}
      `}
      style={{ borderColor }}
    >
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

      {/* Type icon + Name */}
      <div className="flex items-start gap-2">
        <span className="text-lg shrink-0 mt-0.5 opacity-60">{TYPE_ICONS[obj.type]}</span>
        <div className="min-w-0">
          <div className="font-semibold text-sm text-neutral-100 truncate">{obj.name}</div>
          {obj.description && (
            <div className="text-xs text-neutral-400 mt-0.5 line-clamp-2">{obj.description}</div>
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
    </div>
  )
}
