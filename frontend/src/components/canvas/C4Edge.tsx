import {
  BaseEdge,
  EdgeLabelRenderer,
  getBezierPath,
  getSmoothStepPath,
  getStraightPath,
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
  markerStart,
}: EdgeProps) {
  const shape = ((data as Record<string, unknown>)?.shape as string) || 'curved'
  const labelSize = ((data as Record<string, unknown>)?.labelSize as number) || 11

  let edgePath: string
  let labelX: number
  let labelY: number

  if (shape === 'straight') {
    ;[edgePath, labelX, labelY] = getStraightPath({
      sourceX, sourceY, targetX, targetY,
    })
  } else if (shape === 'step') {
    ;[edgePath, labelX, labelY] = getSmoothStepPath({
      sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition,
      borderRadius: 0,
    })
  } else if (shape === 'smoothstep') {
    ;[edgePath, labelX, labelY] = getSmoothStepPath({
      sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition,
      borderRadius: 16,
    })
  } else {
    ;[edgePath, labelX, labelY] = getBezierPath({
      sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition,
    })
  }

  const label = (data as Record<string, unknown>)?.label as string | undefined
  const protocol = (data as Record<string, unknown>)?.protocol as string | undefined
  const flowStep = (data as Record<string, unknown>)?.flowStep as number | null | undefined
  const flowCurrent = (data as Record<string, unknown>)?.flowCurrent as boolean | undefined

  // When a flow is playing, steps in the active branch get a thicker blue
  // stroke; the step being played gets a bright green stroke so the eye
  // lands on "what's happening right now".
  const stroke = flowCurrent
    ? '#22c55e'
    : flowStep
      ? '#3b82f6'
      : selected
        ? '#3b82f6'
        : '#525252'
  const strokeWidth = flowCurrent ? 3 : flowStep ? 2.2 : selected ? 2 : 1.5

  return (
    <>
      <BaseEdge
        id={id}
        path={edgePath}
        markerEnd={markerEnd}
        markerStart={markerStart}
        style={{ stroke, strokeWidth }}
      />
      {(label || protocol) && (
        <EdgeLabelRenderer>
          <div
            className="absolute bg-neutral-900/90 text-neutral-300 px-2 py-1 rounded border border-neutral-700 pointer-events-auto nodrag nopan"
            style={{
              transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
              fontSize: `${labelSize}px`,
              lineHeight: '1.3',
              maxWidth: 220,
              whiteSpace: 'pre-wrap',
              textAlign: 'center',
            }}
          >
            {label}
            {label && protocol && <br />}
            {protocol && <span className="text-neutral-500">[{protocol}]</span>}
          </div>
        </EdgeLabelRenderer>
      )}
      {flowStep && (
        <EdgeLabelRenderer>
          <div
            className="absolute pointer-events-none nodrag nopan"
            style={{
              transform: `translate(-50%, -50%) translate(${labelX}px,${labelY - 22}px)`,
              width: 22,
              height: 22,
              borderRadius: '50%',
              background: flowCurrent ? '#22c55e' : '#3b82f6',
              color: 'white',
              fontSize: 11,
              fontWeight: 700,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              boxShadow: '0 2px 6px rgba(0,0,0,0.4)',
              border: '2px solid #0a0a0a',
            }}
          >
            {flowStep}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  )
}
