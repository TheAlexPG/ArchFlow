import { Handle, Position, type NodeProps } from '@xyflow/react'
import type { C4NodeData } from './C4Node'
import { STATUS_COLORS, stripHtml } from './node-utils'

export function ExternalSystemNode({ data, selected }: NodeProps) {
  const obj = (data as C4NodeData).object
  const statusColor = STATUS_COLORS[obj.status]

  return (
    <div
      style={{
        position: 'relative',
        minWidth: 160,
        maxWidth: 240,
        padding: '12px 16px',
        borderRadius: 20,
        background: '#1f2937',
        border: `2px dashed ${selected ? '#3b82f6' : '#6b7280'}`,
      }}
    >
      <Handle type="source" position={Position.Top} id="top" className="archflow-handle !bg-neutral-500 !w-2 !h-2" />
      <Handle type="source" position={Position.Bottom} id="bottom" className="archflow-handle !bg-neutral-500 !w-2 !h-2" />
      <Handle type="source" position={Position.Left} id="left" className="archflow-handle !bg-neutral-500 !w-2 !h-2" />
      <Handle type="source" position={Position.Right} id="right" className="archflow-handle !bg-neutral-500 !w-2 !h-2" />

      {/* Status */}
      <div
        style={{
          position: 'absolute', top: -6, right: -6, width: 12, height: 12,
          borderRadius: '50%', backgroundColor: statusColor,
          border: '2px solid #0a0a0a',
        }}
        title={obj.status}
      />

      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontSize: 16, opacity: 0.6 }}>☁</span>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: '#e5e5e5' }}>
            {obj.name}
          </div>
          <div style={{ fontSize: 10, color: '#737373' }}>External System</div>
        </div>
      </div>

      {obj.description && stripHtml(obj.description) && (
        <div
          className="node-desc-html"
          style={{ fontSize: 11, color: '#737373', marginTop: 6 }}
          dangerouslySetInnerHTML={{ __html: obj.description }}
        />
      )}

      {/* TODO(tech-catalog): replace UUID list with TechBadge row (M7). */}
      {obj.technology_ids && obj.technology_ids.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 8 }}>
          {obj.technology_ids.map((tech) => (
            <span
              key={tech}
              style={{
                fontSize: 10, padding: '1px 6px', borderRadius: 3,
                background: '#262626', color: '#a3a3a3',
              }}
            >
              {tech}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
