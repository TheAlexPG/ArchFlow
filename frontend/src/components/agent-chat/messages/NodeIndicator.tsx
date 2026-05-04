import { cn } from '../../../utils/cn'

// ─── NodeIndicator ──────────────────────────────────────────────────────────
//
// Animated pill marking a graph-node entry — surfaced while an agent /
// sub-agent is running so the user sees "something is happening" between
// tool calls. Maps the raw LangGraph node name to a human label + emoji.
// Unknown nodes fall through to a neutral badge.
//
// Activity animation: a coral pulse around the badge plus three dots
// running through ``animate-pulse`` with staggered delays — same idiom
// as the in-flight tool card.

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
  return (
    <div className="flex items-center" data-testid="node-indicator">
      <div
        className={cn(
          'relative inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full',
          'bg-surface border border-coral/40',
          'text-[11px] text-text-2 font-mono',
          'shadow-[0_0_0_1px_var(--color-coral-glow)]',
        )}
      >
        {/* Pulsing ring around the badge — passive activity hint. */}
        <span
          aria-hidden
          className="absolute inset-0 rounded-full ring-1 ring-coral/30 animate-ping pointer-events-none"
        />
        <span aria-hidden="true" className="relative">
          {meta.emoji}
        </span>
        <span className="relative">{meta.label}</span>
        <span className="relative inline-flex items-center gap-0.5 ml-0.5" aria-hidden>
          <span className="w-1 h-1 rounded-full bg-coral animate-pulse" />
          <span className="w-1 h-1 rounded-full bg-coral animate-pulse [animation-delay:120ms]" />
          <span className="w-1 h-1 rounded-full bg-coral animate-pulse [animation-delay:240ms]" />
        </span>
      </div>
    </div>
  )
}
