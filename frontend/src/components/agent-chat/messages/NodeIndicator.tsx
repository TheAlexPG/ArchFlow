import { cn } from '../../../utils/cn'

// ─── NodeIndicator ──────────────────────────────────────────────────────────
//
// Small inline pill marking a graph-node entry (e.g. "🧠 Planning…",
// "🛠 Acting…", "📦 Compacting…"). Maps the raw LangGraph node name to a
// human label + emoji. Unknown nodes fall through to a neutral badge.

const NODE_LABELS: Record<string, { emoji: string; label: string }> = {
  planner: { emoji: '🧠', label: 'Planning' },
  plan: { emoji: '🧠', label: 'Planning' },
  reason: { emoji: '🧠', label: 'Reasoning' },
  act: { emoji: '🛠', label: 'Acting' },
  tool: { emoji: '🛠', label: 'Calling tool' },
  observe: { emoji: '👁', label: 'Observing' },
  research: { emoji: '🔍', label: 'Researching' },
  researcher: { emoji: '🔍', label: 'Researching' },
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
          'inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full',
          'bg-surface border border-border-base',
          'text-[11px] text-text-3 font-mono',
        )}
      >
        <span aria-hidden="true">{meta.emoji}</span>
        <span>{meta.label}…</span>
      </div>
    </div>
  )
}
