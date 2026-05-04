import { useEffect, useState } from 'react'
import { cn } from '../../../utils/cn'

// ─── NodeIndicator ──────────────────────────────────────────────────────────
//
// Animated pill marking a graph-node entry — surfaced while an agent /
// sub-agent is running so the user sees "something is happening" between
// tool calls. Maps the raw LangGraph node name to a human label + emoji.
// Unknown nodes fall through to a neutral badge.
//
// Motion budget: one focal element. We previously stacked an
// animate-ping ring, an outer coral-glow shadow, and three pulsing dots
// — three competing motions that read as noise. The badge now uses a
// single ~1.6s coral-glow heartbeat plus a single coral status dot that
// breathes in lockstep. After ~2.4s without remount we drop the
// heartbeat to a calm steady glow so a stale node indicator doesn't
// keep nagging while the agent is busy elsewhere.

const NODE_LABELS: Record<string, { emoji: string; label: string }> = {
  supervisor: { emoji: '🧭', label: 'Orchestrating' },
  planner: { emoji: '🧠', label: 'Planning' },
  plan: { emoji: '🧠', label: 'Planning' },
  reason: { emoji: '🧠', label: 'Reasoning' },
  act: { emoji: '🛠', label: 'Acting' },
  tool: { emoji: '🛠', label: 'Calling tool' },
  observe: { emoji: '👁', label: 'Observing' },
  research: { emoji: '🔍', label: 'Researching' },
  researcher: { emoji: '🔍', label: 'Researching' },
  diagram: { emoji: '🗺', label: 'Editing diagram' },
  critic: { emoji: '🧐', label: 'Reviewing' },
  explain: { emoji: '💬', label: 'Explaining' },
  explainer: { emoji: '💬', label: 'Explaining' },
  compact: { emoji: '📦', label: 'Compacting' },
  finalize: { emoji: '✓', label: 'Finalizing' },
}

interface NodeIndicatorProps {
  node: string
}

export function NodeIndicator({ node }: NodeIndicatorProps) {
  const meta = NODE_LABELS[node.toLowerCase()] ?? { emoji: '•', label: node }

  // Calm down after ~2.4s — assume the agent has moved on to another
  // node or a tool call by then, so a static glow is plenty.
  const [calmed, setCalmed] = useState(false)
  useEffect(() => {
    const t = window.setTimeout(() => setCalmed(true), 2400)
    return () => window.clearTimeout(t)
  }, [node])

  return (
    <div className="flex items-center" data-testid="node-indicator" data-calmed={calmed ? 'true' : 'false'}>
      <div
        className={cn(
          'relative inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full',
          'bg-surface border border-coral/40',
          'text-[11px] text-text-1 font-mono',
        )}
        style={{
          animation: calmed
            ? undefined
            : 'archflow-node-glow 1.6s cubic-bezier(0.16, 1, 0.3, 1) infinite',
          boxShadow: calmed ? '0 0 0 1px var(--color-coral-glow)' : undefined,
        }}
      >
        <span
          aria-hidden
          className={cn(
            'inline-block w-1.5 h-1.5 rounded-full bg-coral',
            !calmed && 'shadow-[0_0_6px_var(--color-coral)]',
          )}
          style={
            calmed
              ? undefined
              : { animation: 'archflow-heartbeat 1.6s cubic-bezier(0.16, 1, 0.3, 1) infinite' }
          }
        />
        <span aria-hidden="true">{meta.emoji}</span>
        <span>{meta.label}</span>
      </div>
    </div>
  )
}
