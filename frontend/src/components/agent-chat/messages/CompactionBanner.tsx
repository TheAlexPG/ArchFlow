import { useState } from 'react'
import { cn } from '../../../utils/cn'

// ─── CompactionBanner ──────────────────────────────────────────────────────
//
// Surfaced when the runtime applies a context compaction step (spec §2.13).
// Dismissable: clicking ✕ hides it locally; we don't send anything to the
// server. The event remains in the stream history so a re-render (e.g.
// resume) will show it again.

interface CompactionBannerProps {
  stage: number | string
  strategy: string
  tokens_before?: number
  tokens_after?: number
}

export function CompactionBanner({
  stage,
  strategy,
  tokens_before,
  tokens_after,
}: CompactionBannerProps) {
  const [dismissed, setDismissed] = useState(false)
  if (dismissed) return null

  const ratio =
    tokens_before && tokens_after && tokens_before > 0
      ? Math.round(((tokens_before - tokens_after) / tokens_before) * 100)
      : null

  return (
    <div
      data-testid="compaction-banner"
      className={cn(
        'flex items-start gap-2 px-3 py-2 rounded-md',
        'bg-blue-500/10 border border-blue-500/30',
        'text-[12px] text-blue-300',
      )}
    >
      <span aria-hidden="true" className="mt-0.5">
        📦
      </span>
      <div className="flex-1 leading-snug">
        <div className="font-medium">
          Context compacted{' '}
          <span className="text-text-3 font-mono text-[11px]">
            (stage {stage}, {strategy})
          </span>
        </div>
        {ratio !== null && (
          <div className="text-text-3 text-[11px]">
            {tokens_before?.toLocaleString()} → {tokens_after?.toLocaleString()} tokens (
            {ratio}% saved)
          </div>
        )}
      </div>
      <button
        type="button"
        onClick={() => setDismissed(true)}
        data-testid="compaction-banner-dismiss"
        aria-label="Dismiss"
        className="text-text-3 hover:text-text-base text-[12px]"
      >
        ✕
      </button>
    </div>
  )
}
