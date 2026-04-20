import { memo } from 'react'
import type { CursorState, SelectionState } from '../../hooks/use-realtime'

interface Props {
  cursors: Record<string, CursorState>
  selections?: Record<string, SelectionState>
}

// Deterministic hue from a user_id string (simple djb2-style hash).
export function hueFromId(id: string): number {
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

/**
 * Paints a thin colored outline on every node another user has selected.
 * Lives on top of the React Flow node layer, reads the node rect each
 * render from the DOM (via `.react-flow__node[data-id="..."]`) so we
 * don't have to plumb node positions through props.
 */
export const RemoteSelectionsOverlay = memo(function RemoteSelectionsOverlay({
  selections,
}: {
  selections: Record<string, SelectionState>
}) {
  const entries = Object.entries(selections)
  if (entries.length === 0) return null

  return (
    <>
      {entries.flatMap(([userId, state]) =>
        state.ids.map((nodeId) => (
          <RemoteSelectionRing key={`${userId}:${nodeId}`} userId={userId} nodeId={nodeId} />
        )),
      )}
    </>
  )
})

function RemoteSelectionRing({ userId, nodeId }: { userId: string; nodeId: string }) {
  const hue = hueFromId(userId)
  // CSS-only: absolute-positioned against the ReactFlow pane root, targets
  // the node by attribute selector via ::before? No — we rely on ReactFlow
  // rendering each node into an absolutely-positioned wrapper. We use a
  // neighbour selector + a fixed outline. Simplest: render a ring that
  // sits inside the node-wrapper via React portal... but getting the DOM
  // node requires a ref. For the MVP we just push a CSS rule that draws
  // a thin ring around the targeted node via a style injection; resilient
  // enough and renders no extra DOM in the flow layer.
  const selector = `.react-flow__node[data-id="${cssEscape(nodeId)}"]`
  const css = `${selector} { box-shadow: 0 0 0 2px hsl(${hue}, 70%, 60%) !important; border-radius: 6px; }`
  return <style>{css}</style>
}

function cssEscape(s: string): string {
  // Node ids are UUIDs → safe. Guard anyway in case a caller passes a
  // synthetic id with a quote.
  return s.replace(/["\\]/g, '\\$&')
}
