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
  // TODO(tech-catalog): resolve protocol_id → Technology.name via the
  // catalog so the label renders a human string (M7). For now shows the
  // raw UUID if present.
  const protocol = (data as Record<string, unknown>)?.protocol_id as string | undefined
  const flowStep = (data as Record<string, unknown>)?.flowStep as number | null | undefined
  const flowCurrent = (data as Record<string, unknown>)?.flowCurrent as boolean | undefined

  // When a flow is playing, steps in the active branch get a thicker coral
  // stroke; the step being played gets a bright green stroke so the eye
  // lands on "what's happening right now". Selected edges use coral to
  // match the rest of the canvas selection language.
  const stroke = flowCurrent
    ? '#22c55e'
    : flowStep
      ? 'var(--color-coral)'
      : selected
        ? 'var(--color-coral)'
        : 'var(--color-text-4)'
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
            className={[
              'absolute pointer-events-auto nodrag nopan',
              'bg-panel/90 backdrop-blur-sm',
              'border rounded px-1.5 py-0.5',
              'font-mono',
              selected ? 'border-coral text-coral' : 'border-border-base text-text-2',
            ].join(' ')}
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
            {protocol && <span className="text-text-3">[{protocol}]</span>}
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
              background: flowCurrent ? '#22c55e' : 'var(--color-coral)',
              color: 'var(--color-bg)',
              fontSize: 11,
              fontWeight: 700,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              boxShadow: '0 2px 6px rgba(0,0,0,0.4)',
              border: '2px solid var(--color-bg)',
            }}
          >
            {flowStep}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  )
}
