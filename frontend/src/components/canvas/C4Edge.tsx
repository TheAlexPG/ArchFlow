import {
  BaseEdge,
  EdgeLabelRenderer,
  getBezierPath,
  type EdgeProps,
} from '@xyflow/react'

export function C4Edge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  data,
  selected,
  markerEnd,
}: EdgeProps) {
  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
  })

  const label = (data as Record<string, unknown>)?.label as string | undefined
  const protocol = (data as Record<string, unknown>)?.protocol as string | undefined

  return (
    <>
      <BaseEdge
        id={id}
        path={edgePath}
        markerEnd={markerEnd}
        style={{
          stroke: selected ? '#3b82f6' : '#525252',
          strokeWidth: selected ? 2 : 1.5,
        }}
      />
      {(label || protocol) && (
        <EdgeLabelRenderer>
          <div
            className="absolute text-[10px] bg-neutral-900/90 text-neutral-300 px-1.5 py-0.5 rounded border border-neutral-700 pointer-events-all nodrag nopan"
            style={{
              transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
            }}
          >
            {label}
            {label && protocol && ' '}
            {protocol && <span className="text-neutral-500">[{protocol}]</span>}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  )
}
