import { cn } from '../../../utils/cn'

// ─── BudgetWarning ─────────────────────────────────────────────────────────
//
// Soft yellow banner surfaced when the runtime crosses a budget threshold
// (spec §6.8: warnings at >80%). Server payload (§3.7):
//   { used_usd, limit_usd, scope }
//
// `scope` is one of "session" | "agent" | "workspace".

interface BudgetWarningProps {
  used: number
  limit: number
  scope: string
}

export function BudgetWarning({ used, limit, scope }: BudgetWarningProps) {
  const pct = limit > 0 ? Math.min(100, Math.round((used / limit) * 100)) : 0

  return (
    <div
      data-testid="budget-warning"
      data-scope={scope}
      className={cn(
        'flex items-start gap-2 px-3 py-2 rounded-md',
        'bg-amber-500/10 border border-amber-500/30',
        'text-[12px] text-amber-300',
      )}
    >
      <span aria-hidden="true" className="mt-0.5">
        ⚠
      </span>
      <div className="flex-1 leading-snug">
        <div className="font-medium">
          Budget at {pct}% <span className="text-text-3 font-mono text-[11px]">({scope})</span>
        </div>
        <div className="text-text-3 text-[11px] font-mono">
          ${used.toFixed(2)} / ${limit.toFixed(2)}
        </div>
      </div>
    </div>
  )
}
