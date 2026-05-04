import { useEffect, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useAgentStream } from './use-agent-stream'

// ─── useAppliedChangeSync ───────────────────────────────────────────────────
//
// Listens to the agent SSE stream and reconciles the React Query caches of
// the affected workspace entities so the live canvas matches server state
// when the agent run finishes.
//
// IMPORTANT: invalidation is deferred to the `done` frame, NOT fired on
// every `applied_change`. Why: the SSE generator and every tool inside it
// share ONE long-lived DB session that only commits when the generator
// closes (see backend/app/core/database.py get_db). An invalidate fired
// mid-run kicks off a refetch in a SEPARATE DB session that cannot see the
// agent's still-uncommitted writes — the refetch returns the OLD state and
// overwrites the WS-merged cache with stale data, which is exactly the
// "node only appears at the end" bug the user reported.
//
// During the run the WS layer (useDiagramSocket / useWorkspaceSocket) is
// authoritative: it merges the full entity payload broadcast by each
// mutating tool (publish_object_event, publish_placement_event, etc.) into
// the cache so the canvas updates the instant the tool returns. The
// post-`done` invalidation is a safety net that catches anything WS missed
// (e.g. draft mutations, cross-tab edits during the run, or events whose
// payloads couldn't be serialized).
//
// Wired in ChatBubble alongside useViewChange (must be inside both
// AgentStreamProvider and BrowserRouter trees).

export function useAppliedChangeSync() {
  const stream = useAgentStream()
  const qc = useQueryClient()
  const handledDoneIdRef = useRef<number>(-1)
  const sawAppliedChangeRef = useRef<boolean>(false)

  useEffect(() => {
    if (stream.events.length === 0) return

    // Track whether this run produced any applied_change events at all.
    // If it didn't, there's nothing to reconcile and we skip the
    // post-`done` invalidate to avoid pointless refetches on read-only
    // agent calls.
    if (
      !sawAppliedChangeRef.current &&
      stream.events.some((e) => e.kind === 'applied_change')
    ) {
      sawAppliedChangeRef.current = true
    }

    // Reconcile only on `done` (transaction is committed by the time the
    // generator closes — see comment block above).
    const newDoneEvents = stream.events.filter(
      (e) => e.id > handledDoneIdRef.current && e.kind === 'done',
    )
    if (newDoneEvents.length === 0) return
    handledDoneIdRef.current = Math.max(...newDoneEvents.map((e) => e.id))

    if (!sawAppliedChangeRef.current) return
    sawAppliedChangeRef.current = false

    // Broad invalidation across the four canvas-relevant query families.
    // React Query auto-skips refetches on queries with no observers, so
    // this is cheap when the user is on an unrelated page.
    qc.invalidateQueries({ queryKey: ['diagrams'] })
    qc.invalidateQueries({ queryKey: ['diagram-objects'] })
    qc.invalidateQueries({ queryKey: ['objects'] })
    qc.invalidateQueries({ queryKey: ['connections'] })
  }, [stream.events, qc])
}
