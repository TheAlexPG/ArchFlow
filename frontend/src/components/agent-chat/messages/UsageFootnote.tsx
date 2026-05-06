import { cn } from '../../../utils/cn'

// ─── UsageFootnote ─────────────────────────────────────────────────────────
//
// Small grey footer appended after `usage` SSE event (spec §3.7):
//   { tokens_in, tokens_out, cost_usd } (+ duration_ms surfaced by runtime)
//
// Shown once per turn, at the very end. Not rendered as a bubble — just
// inline text styled subdued.

interface UsageFootnoteProps {
  tokens_in?: number
  tokens_out?: number
  cost_usd?: number
  duration_ms?: number
}

export function UsageFootnote({ tokens_in, tokens_out, cost_usd, duration_ms }: UsageFootnoteProps) {
  const parts: string[] = []
  if (tokens_in != null || tokens_out != null) {
    const inS = (tokens_in ?? 0).toLocaleString()
    const outS = (tokens_out ?? 0).toLocaleString()
    parts.push(`${inS} in / ${outS} out`)
  }
  if (cost_usd != null) parts.push(`$${cost_usd.toFixed(4)}`)
  if (duration_ms != null) parts.push(`${(duration_ms / 1000).toFixed(2)}s`)

  return (
    <div
      data-testid="usage-footnote"
      className={cn(
        'text-[10px] font-mono text-text-4 px-1 pt-1',
        'flex items-center gap-1.5',
      )}
    >
      <span aria-hidden="true">●</span>
      <span>{parts.join(' • ')}</span>
    </div>
  )
}
