import { Handle, NodeResizer, Position, useNodeId, type NodeProps } from '@xyflow/react'
import { useParams } from 'react-router-dom'
import type { C4NodeData } from './C4Node'
import { useSaveDiagramSize } from '../../hooks/use-api'
import { stripHtml } from './node-utils'

export function GroupNode({ data, selected }: NodeProps) {
  const obj = (data as C4NodeData).object
  const params = useParams<{ diagramId?: string }>()
  const nodeId = useNodeId()
  const saveSize = useSaveDiagramSize()

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

      <div style={{
        fontSize: 11, color: '#737373', fontWeight: 500, textTransform: 'uppercase',
        letterSpacing: '0.05em', marginBottom: 4,
      }}>
        Group
      </div>
      <div style={{ fontSize: 14, fontWeight: 600, color: '#e5e5e5' }}>
        {obj.name}
      </div>
      {obj.description && stripHtml(obj.description) && (
        <div
          className="node-desc-html"
          style={{ fontSize: 11, color: '#737373', marginTop: 4 }}
          dangerouslySetInnerHTML={{ __html: obj.description }}
        />
      )}
    </div>
  )
}
