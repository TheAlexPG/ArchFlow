import { useEffect, useMemo, useState } from 'react'
import { useAgentStream } from './hooks/use-agent-stream'

// ─── Payload shapes (narrowed from unknown) ─────────────────────────────────

interface UsagePayload {
  tokens_in?: number
  tokens_out?: number
  cost_usd?: number
}

interface BudgetPayload {
  used?: number
  limit?: number
}

interface CompactionPayload {
  stage?: number
  strategy?: string
}

// ─── Stat derivation ─────────────────────────────────────────────────────────
//
// All stats are computed by walking the events array in a single pass so we
// never need a separate accumulator hook. Memoised on `events` identity.

interface StreamStats {
  turnsUsed: number
  tokensIn: number
  tokensOut: number
  costUsd: number | null
  budgetUsed: number | null
  budgetLimit: number | null
  compactionStage: number
  compactionStrategy: string
  forcedFinalize: boolean
}

function deriveStats(events: ReturnType<typeof useAgentStream>['events']): StreamStats {
  let turnsUsed = 0
  let tokensIn = 0
  let tokensOut = 0
  let costUsd: number | null = null
  let budgetUsed: number | null = null
  let budgetLimit: number | null = null
  let compactionStage = 0
  let compactionStrategy = ''
  let forcedFinalize = false

  for (const evt of events) {
    switch (evt.kind) {
      case 'node':
        turnsUsed += 1
        break

      case 'usage': {
        const p = evt.payload as UsagePayload | null
        if (p) {
          if (p.tokens_in !== undefined) tokensIn = p.tokens_in
          if (p.tokens_out !== undefined) tokensOut = p.tokens_out
          if (p.cost_usd !== undefined) costUsd = p.cost_usd
        }
        break
      }

      case 'budget_warning':
      case 'budget_exhausted': {
        const p = evt.payload as BudgetPayload | null
        if (p) {
          if (p.used !== undefined) budgetUsed = p.used
          if (p.limit !== undefined) budgetLimit = p.limit
        }
        break
      }

      case 'compaction_applied': {
        const p = evt.payload as CompactionPayload | null
        if (p) {
          const stage = p.stage ?? 1
          if (stage > compactionStage) {
            compactionStage = stage
            compactionStrategy = p.strategy ?? ''
          }
        }
        break
      }

      case 'cancelled':
      case 'error':
        forcedFinalize = true
        break

      default:
        break
    }
  }

  return {
    turnsUsed,
    tokensIn,
    tokensOut,
    costUsd,
    budgetUsed,
    budgetLimit,
    compactionStage,
    compactionStrategy,
    forcedFinalize,
  }
}

// ─── Post-done summary display ───────────────────────────────────────────────
//
// After streaming ends show a 5s expanded summary then collapse to mini line.

type SummaryPhase = 'hidden' | 'expanded' | 'mini'

function useSummaryPhase(isStreaming: boolean, hasEvents: boolean): SummaryPhase {
  const [phase, setPhase] = useState<SummaryPhase>('hidden')

  useEffect(() => {
    // Defer all setState calls out of the synchronous effect body so the
    // react-hooks/set-state-in-effect rule is satisfied.
    if (!isStreaming && hasEvents) {
      // Enter expanded immediately (next microtask), then collapse after 5s.
      const enter = setTimeout(() => setPhase('expanded'), 0)
      const collapse = setTimeout(() => setPhase('mini'), 5000)
      return () => {
        clearTimeout(enter)
        clearTimeout(collapse)
      }
    }
    if (isStreaming) {
      const reset = setTimeout(() => setPhase('hidden'), 0)
      return () => clearTimeout(reset)
    }
  }, [isStreaming, hasEvents])

  return phase
}

// ─── ChatStatusBar ────────────────────────────────────────────────────────────

export function ChatStatusBar() {
  const stream = useAgentStream()

  const stats = useMemo(() => deriveStats(stream.events), [stream.events])

  const summaryPhase = useSummaryPhase(stream.isStreaming, stream.events.length > 0)

  // Hide entirely when idle with no history.
  if (!stream.isStreaming && stream.events.length === 0) return null

  const {
    turnsUsed,
    tokensIn,
    tokensOut,
    costUsd,
    budgetUsed,
    budgetLimit,
    compactionStage,
    compactionStrategy,
  } = stats

  const totalTokens = tokensIn + tokensOut
  const budgetWarning =
    budgetUsed !== null && budgetLimit !== null && budgetLimit > 0
      ? budgetUsed > 0.85 * budgetLimit
      : false

  // ── Post-done: mini line ─────────────────────────────────────────────────
  if (!stream.isStreaming && summaryPhase === 'mini') {
    return (
      <div
        data-testid="chat-status-bar"
        className="border-t flex items-center px-3 py-1 text-xs text-text-lo gap-2"
      >
        <span data-testid="status-mini">
          {(totalTokens / 1000).toFixed(1)}k / ${(costUsd ?? 0).toFixed(3)} /{' '}
          {turnsUsed} turns
        </span>
      </div>
    )
  }

  // ── Post-done: expanded summary (5s) ─────────────────────────────────────
  if (!stream.isStreaming && summaryPhase === 'expanded') {
    return (
      <div
        data-testid="chat-status-bar"
        className="border-t flex items-center px-3 py-1 text-xs text-text-lo gap-2"
      >
        <span data-testid="status-summary">
          {(totalTokens / 1000).toFixed(1)}k tokens, ${(costUsd ?? 0).toFixed(3)}, {turnsUsed} turns
        </span>
      </div>
    )
  }

  // ── Active / streaming ────────────────────────────────────────────────────
  return (
    <div
      data-testid="chat-status-bar"
      className="border-t flex items-center justify-between px-3 py-1 text-xs"
    >
      <div className="flex items-center gap-3">
        <span data-testid="status-turns">Turns: {turnsUsed}/200</span>
        <span data-testid="status-cost">${(costUsd ?? 0).toFixed(3)}/$1.00</span>

        {compactionStage > 0 && (
          <button
            data-testid="status-compaction"
            title={`Compacted via ${compactionStrategy}`}
            className="cursor-default"
          >
            Compacted ({compactionStage}/4)
          </button>
        )}

        {budgetWarning && (
          <span data-testid="status-budget-warning" className="text-orange-500">
            ⚠ budget
          </span>
        )}
      </div>

      <div className="flex items-center gap-2">
        {stream.isStreaming && (
          <button
            data-testid="status-cancel"
            onClick={() => void stream.cancel()}
            title="Cancel"
            className="text-red-500"
          >
            ▢ Cancel
          </button>
        )}
      </div>
    </div>
  )
}
