import { memo } from 'react'
import type { CursorState } from '../../hooks/use-realtime'

interface Props {
  cursors: Record<string, CursorState>
}

// Deterministic hue from a user_id string (simple djb2-style hash).
function hueFromId(id: string): number {
  let h = 5381
  for (let i = 0; i < id.length; i++) {
    h = ((h << 5) + h) ^ id.charCodeAt(i)
  }
  return Math.abs(h) % 360
}

function CursorPin({ userId, state }: { userId: string; state: CursorState }) {
  const hue = hueFromId(userId)
  const color = `hsl(${hue}, 70%, 60%)`

  return (
    // Positioned in flow-coordinate space by the parent container transform.
    // The parent (ReactFlow) handles the viewport CSS transform, so we only
    // need to set left/top in flow units.
    <div
      style={{
        position: 'absolute',
        left: state.x,
        top: state.y,
        pointerEvents: 'none',
        // Lift above nodes/edges so cursors are always visible.
        zIndex: 1000,
        transform: 'translate(-2px, -2px)',
        willChange: 'transform',
      }}
    >
      {/* SVG pointer arrow */}
      <svg
        width="16"
        height="20"
        viewBox="0 0 16 20"
        fill="none"
        style={{ display: 'block', filter: 'drop-shadow(0 1px 2px rgba(0,0,0,0.6))' }}
      >
        <path
          d="M1 1L14 8L8 10L5 18L1 1Z"
          fill={color}
          stroke="rgba(0,0,0,0.4)"
          strokeWidth="1"
        />
      </svg>
      {/* Name label */}
      <div
        style={{
          marginTop: 2,
          marginLeft: 14,
          background: color,
          color: '#0a0a0a',
          fontSize: 10,
          fontWeight: 600,
          padding: '1px 5px',
          borderRadius: 4,
          whiteSpace: 'nowrap',
          lineHeight: 1.6,
          boxShadow: '0 1px 3px rgba(0,0,0,0.5)',
        }}
      >
        {state.user_name}
      </div>
    </div>
  )
}

// Memoised so React doesn't re-render all pins on every canvas mousemove;
// only the specific cursor entry that changed will cause a re-render.
export const CursorsOverlay = memo(function CursorsOverlay({ cursors }: Props) {
  const entries = Object.entries(cursors)
  if (entries.length === 0) return null

  return (
    <>
      {entries.map(([userId, state]) => (
        <CursorPin key={userId} userId={userId} state={state} />
      ))}
    </>
  )
})
