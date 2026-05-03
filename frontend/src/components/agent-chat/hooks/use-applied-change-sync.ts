import { useEffect, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useAgentStream } from './use-agent-stream'

// ─── useAppliedChangeSync ───────────────────────────────────────────────────
//
// Listens to the agent SSE stream for `applied_change` events and invalidates
// the React Query caches of the affected workspace entities so the live
// canvas refreshes without the user having to reload the page.
//
// Backend emits one `applied_change` per mutating tool call. Payload shape
// (per AppliedChangePill):
//   { action, target_type, target_id, name?, diagram_id? }
// where action is e.g. "object.created" / "connection.created" /
// "diagram.updated" — the prefix of `action` gives us the entity kind.
//
// Wired in ChatBubble alongside useViewChange (must be inside both
// AgentStreamProvider and BrowserRouter trees).

export function useAppliedChangeSync() {
  const stream = useAgentStream()
  const qc = useQueryClient()
  const handledIdRef = useRef<number>(-1)

  useEffect(() => {
    if (stream.events.length === 0) return
    // Walk every new applied_change since last tick (a single ReAct loop
    // can emit several in quick succession). We track the highest id we've
    // processed so we never invalidate twice for the same event.
    const newEvents = stream.events.filter(
      (e) => e.id > handledIdRef.current && e.kind === 'applied_change',
    )
    if (newEvents.length === 0) return
    handledIdRef.current = Math.max(...newEvents.map((e) => e.id))

    // Broad invalidation across the four canvas-relevant query families.
    // React Query auto-skips refetches on queries with no observers, so
    // this is cheap when the user is on an unrelated page. Doing it per
    // event family lets us refresh the live canvas without having to know
    // which exact diagram_id the agent touched (connection.* events
    // usually omit it).
    qc.invalidateQueries({ queryKey: ['diagrams'] })
    qc.invalidateQueries({ queryKey: ['diagram-objects'] })
    qc.invalidateQueries({ queryKey: ['objects'] })
    qc.invalidateQueries({ queryKey: ['connections'] })
  }, [stream.events, qc])
}
