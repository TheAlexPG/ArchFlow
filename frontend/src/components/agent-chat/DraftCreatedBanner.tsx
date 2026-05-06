import { Link } from 'react-router-dom'
import { useAgentStream } from './hooks/use-agent-stream'
import type { AgentSSEEvent } from './types'

// ─── Payload shapes (narrow subset we need) ──────────────────────────────────

interface ViewChangePayload {
  reason?: string
  to: {
    kind: 'diagram' | string
    id: string
    draft_id?: string
  }
}


// ─── Detection helpers ────────────────────────────────────────────────────────

/**
 * Walk the event list for the *most recent* `view_change` event whose reason
 * is `draft_created` and is followed (or ended) by a `done` event.
 *
 * Returns the relevant payload fields or `null` if the pattern has not been
 * reached yet.
 */
function findCompletedDraftCreation(events: AgentSSEEvent[]): {
  draftId: string
  baseId: string
  name: string
  appliedCount: number
} | null {
  // Find the last done event — banner only shows after the run finished.
  const doneIdx = [...events].map((e, i) => ({ e, i })).reverse().find(({ e }) => e.kind === 'done')
  if (!doneIdx) return null

  // Find the last view_change(draft_created) event before or at done.
  for (let i = doneIdx.i; i >= 0; i--) {
    const evt = events[i]
    if (evt.kind !== 'view_change') continue
    const payload = evt.payload as ViewChangePayload
    if (payload?.reason !== 'draft_created') continue
    const { to } = payload
    if (!to || to.kind !== 'diagram' || !to.draft_id) continue

    // Count applied_change events between this view_change and done.
    const appliedCount = events.slice(i, doneIdx.i + 1).filter(
      (e) => e.kind === 'applied_change',
    ).length

    return {
      draftId: to.draft_id,
      baseId: to.id,
      // We don't have the draft name in view_change payload directly —
      // use a generic label; the compare page will show the real name.
      name: `draft-${to.draft_id.slice(0, 8)}`,
      appliedCount,
    }
  }

  return null
}

// ─── Component ───────────────────────────────────────────────────────────────

/**
 * Banner shown at the bottom of the chat body (above the status bar) when:
 *   1. The agent emitted a `view_change` with `reason=draft_created`.
 *   2. The run ended with `done`.
 *
 * Provides a direct "Review & merge →" link to the compare page.
 */
export function DraftCreatedBanner() {
  const stream = useAgentStream()
  const info = findCompletedDraftCreation(stream.events)

  if (!info) return null

  const compareHref = `/diagram/${info.baseId}?draft=${info.draftId}&compare=1`

  return (
    <div
      data-testid="draft-created-banner"
      className="mx-3 mb-2 rounded-lg border-l-4 border-blue-400 bg-blue-950/40 px-3 py-2 text-[12px] text-blue-200 flex items-center justify-between gap-2 flex-shrink-0"
    >
      <span>
        Draft{' '}
        <span className="font-mono text-blue-300">{info.name}</span>{' '}
        {info.appliedCount > 0
          ? `has ${info.appliedCount} change${info.appliedCount === 1 ? '' : 's'}.`
          : 'created.'}
      </span>
      <Link
        data-testid="draft-created-review-link"
        to={compareHref}
        className="shrink-0 font-medium text-blue-300 hover:text-blue-100 transition-colors underline underline-offset-2"
      >
        Review &amp; merge &rarr;
      </Link>
    </div>
  )
}
