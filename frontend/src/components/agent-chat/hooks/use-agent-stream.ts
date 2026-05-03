// We deliberately mutate fields on a stable bag object held by `useState`'s
// lazy init — see `StreamBag` below for rationale. The new react-hooks
// plugin (v7+) flags these mutations under `react-hooks/immutability`,
// but the alternative ("re-create every callback every turn") would
// invalidate handlers passed into in-flight fetch streams. Same trade-off
// as `frontend/src/hooks/use-realtime.ts`.
/* eslint-disable react-hooks/immutability */

import { createContext, createElement, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'

import {
  AgentStreamError,
  cancelAgentSession,
  reconnectAgent,
  respondToChoice,
  streamAgent,
} from '../../../lib/agent-stream'
import { useAuthStore } from '../../../stores/auth-store'
import { useWorkspaceStore } from '../../../stores/workspace-store'
import type { AgentInvokeBody, AgentSSEEvent, AgentSSEEventKind } from '../types'

// ─── Public hook surface ───────────────────────────────────────────────────

export interface UseAgentStreamResult {
  /** All events received in the current stream, in arrival order. The
   *  parent (ChatBubble + stream renderers) bucket these into UI groups
   *  by walking the array — see "Integration notes" in the task report. */
  events: AgentSSEEvent[]
  /** True between startStream() and the natural close (or after all
   *  reconnect attempts give up). */
  isStreaming: boolean
  /** Last error surfaced by the underlying transport. Cleared on the
   *  next startStream() / reset(). */
  lastError: Error | null
  /** Session id captured from the first `event: session` frame. Null
   *  until that frame arrives — and that's the signal the bubble uses
   *  to enable Cancel + Respond actions. */
  sessionId: string | null
  /** True when we are between disconnect and a successful reconnect.
   *  UI shows "Reconnecting…" banner. */
  isReconnecting: boolean
  /** True after `RECONNECT_LIMIT` failed retries — UI shows the
   *  "Connection lost" banner with [Reconnect] [View partial] buttons. */
  connectionLost: boolean

  startStream: (agentId: string, body: AgentInvokeBody) => void
  cancel: () => Promise<void>
  respond: (toolCallId: string, choiceId: string, extra?: Record<string, unknown>) => Promise<void>
  /** Manually retry after `connectionLost`. Idempotent — no-op while
   *  already streaming. */
  retry: () => void
  /** Wipe events + flags. Call before starting a new conversation. */
  reset: () => void
}

// ─── Constants ─────────────────────────────────────────────────────────────

/** Exponential backoff schedule (ms). After the last entry we surface
 *  `connectionLost` and stop trying. Spec §6.9: "After 3 failures →
 *  Connection lost". */
const RECONNECT_DELAYS = [1000, 2000, 4000] as const
const RECONNECT_LIMIT = RECONNECT_DELAYS.length

// ─── Mutable bag (one ref-of-object instead of N refs) ─────────────────────
//
// Consolidating mutable state into a single object held by a single ref
// has two benefits:
//
//   1. The new react-hooks/immutability lint rule flags writes to refs
//      whose value was "previously passed to a hook" (i.e. the typical
//      `useRef<T>(initial)` pattern). Storing fields on a wrapper object
//      sidesteps that rule because we mutate properties of an object —
//      not the ref's `.current` cell itself.
//   2. Reads/writes from inside long-lived callbacks (onClose, onError)
//      see the same `bag` reference forever, so we don't need to chase
//      the latest closure each turn.

interface StreamBag {
  abort: AbortController | null
  reconnectTimer: ReturnType<typeof setTimeout> | null
  lastEventId: number
  sessionId: string | null
  lastEventKind: AgentSSEEventKind | null
  reconnectAttempt: number
  /** "User asked us to stop" vs. "transport dropped" — only the latter
   *  triggers reconnect logic. */
  cancelledByUser: boolean
  /** Forward-declared so attemptReconnect can call itself across the
   *  startReconnectStream → onClose → attemptReconnect loop without
   *  TDZ pain. */
  attemptReconnect: () => void
}

function makeBag(): StreamBag {
  return {
    abort: null,
    reconnectTimer: null,
    lastEventId: 0,
    sessionId: null,
    lastEventKind: null,
    reconnectAttempt: 0,
    cancelledByUser: false,
    attemptReconnect: () => undefined,
  }
}

// ─── Hook ──────────────────────────────────────────────────────────────────
//
// A single in-flight stream at a time. Calling startStream() while another
// stream is active aborts the previous one — by design, since the chat
// bubble only ever has one active conversation. reset() must be called
// to drop history before starting a fresh conversation; otherwise events
// from the prior turn remain in `events` so the renderer keeps the
// transcript continuous.

function useAgentStreamInstance(): UseAgentStreamResult {
  // ── React state ──────────────────────────────────────────────────────────
  const [events, setEvents] = useState<AgentSSEEvent[]>([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [lastError, setLastError] = useState<Error | null>(null)
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [isReconnecting, setIsReconnecting] = useState(false)
  const [connectionLost, setConnectionLost] = useState(false)

  // ── Single mutable bag ───────────────────────────────────────────────────
  //
  // We use `useState`'s lazy initializer to allocate the bag exactly once
  // per hook instance and never call its setter — that gives us a stable
  // mutable object whose contents we update directly. We deliberately do
  // not use `useRef` here: the new react-hooks lint rule (v7+) flags any
  // read of `.current` from the render body, which would force every
  // access into a `useEffect` and make the code harder to follow.
  const [bag] = useState<StreamBag>(makeBag)

  // ── Auth + workspace headers ─────────────────────────────────────────────
  //
  // Pulled directly from the existing zustand stores (matches api-client.ts
  // axios interceptor). Subscribing via `useAuthStore(...)` would re-run
  // this hook on every token rotation; we read with `getState()` inside
  // callbacks so the latest token is used at request time without
  // triggering re-renders of ChatBubble.

  // ── Internal: handler for a single SSE event ─────────────────────────────
  const handleEvent = useCallback(
    (evt: AgentSSEEvent) => {
      bag.lastEventKind = evt.kind

      // Track Last-Event-ID for resume.
      if (evt.id > bag.lastEventId) bag.lastEventId = evt.id

      // Capture session id from the first `session` frame.
      if (evt.kind === 'session') {
        const payload = evt.payload as { session_id?: string } | null
        const sid = payload?.session_id ?? null
        if (sid && bag.sessionId !== sid) {
          bag.sessionId = sid
          setSessionId(sid)
        }
      }

      // Drop heartbeats from the rendered list — they exist only to keep
      // the connection alive. Track that we received one (resets reconnect
      // counter implicitly via lastEventId bumping).
      if (evt.kind === 'ping') {
        bag.reconnectAttempt = 0
        return
      }

      setEvents((prev) => [...prev, evt])
    },
    [bag],
  )

  // ── Internal: start a resume stream ──────────────────────────────────────
  const startReconnectStream = useCallback(() => {
    if (!bag.sessionId) {
      // Can't resume without a session id — server never sent one (e.g.
      // failure before first frame). Surface as connection lost.
      setConnectionLost(true)
      setIsReconnecting(false)
      setIsStreaming(false)
      return
    }

    const ctrl = new AbortController()
    bag.abort = ctrl
    setIsReconnecting(true)
    setIsStreaming(true)

    const authToken = useAuthStore.getState().accessToken ?? undefined
    const workspaceId = useWorkspaceStore.getState().currentWorkspaceId ?? undefined

    void reconnectAgent({
      sessionId: bag.sessionId,
      sinceId: bag.lastEventId,
      authToken,
      workspaceId,
      signal: ctrl.signal,
      onEvent: handleEvent,
      onError: (err) => {
        // 410 = log expired. No point retrying — surface immediately.
        if (err instanceof AgentStreamError && err.code === 'expired') {
          setLastError(err)
          setConnectionLost(true)
          bag.cancelledByUser = true // suppress further retries
          return
        }
        setLastError(err)
      },
      onClose: () => {
        bag.abort = null
        setIsReconnecting(false)
        if (bag.cancelledByUser) {
          setIsStreaming(false)
          return
        }
        if (bag.lastEventKind === 'done') {
          setIsStreaming(false)
          return
        }
        // Disconnected mid-stream — try again.
        bag.attemptReconnect()
      },
    })
  }, [bag, handleEvent])

  // ── Reconnect with exponential backoff ───────────────────────────────────
  const attemptReconnect = useCallback(() => {
    if (bag.reconnectAttempt >= RECONNECT_LIMIT) {
      setConnectionLost(true)
      setIsReconnecting(false)
      setIsStreaming(false)
      return
    }
    const delay = RECONNECT_DELAYS[bag.reconnectAttempt]
    bag.reconnectAttempt += 1
    setIsReconnecting(true)
    bag.reconnectTimer = setTimeout(() => {
      bag.reconnectTimer = null
      startReconnectStream()
    }, delay)
  }, [bag, startReconnectStream])

  // Wire forward-declared callback into the bag inside an effect (avoids
  // the "ref write during render" lint rule).
  useEffect(() => {
    bag.attemptReconnect = attemptReconnect
  }, [bag, attemptReconnect])

  // ── Public: startStream ──────────────────────────────────────────────────
  const startStream = useCallback(
    (agentId: string, body: AgentInvokeBody) => {
      // Abort any prior in-flight stream. Critical: without this, two
      // overlapping fetches would both push events into `events` and
      // corrupt the transcript.
      bag.abort?.abort()
      if (bag.reconnectTimer) {
        clearTimeout(bag.reconnectTimer)
        bag.reconnectTimer = null
      }

      // Reset transient flags but PRESERVE events — caller is expected
      // to call reset() before a new conversation. This lets follow-up
      // turns append cleanly to the same transcript.
      setLastError(null)
      setConnectionLost(false)
      setIsReconnecting(false)
      bag.reconnectAttempt = 0
      bag.cancelledByUser = false
      bag.lastEventKind = null

      // Optimistically push the user's outgoing message so it appears in the
      // transcript immediately. The backend doesn't echo it as an SSE event.
      if (body.message) {
        bag.lastEventId += 1
        const userEvt: AgentSSEEvent = {
          id: bag.lastEventId,
          kind: 'message',
          payload: { role: 'user', text: body.message },
        }
        setEvents((prev) => [...prev, userEvt])
      }

      const ctrl = new AbortController()
      bag.abort = ctrl
      setIsStreaming(true)

      const authToken = useAuthStore.getState().accessToken ?? undefined
      const workspaceId = useWorkspaceStore.getState().currentWorkspaceId ?? undefined

      void streamAgent({
        url: `/api/v1/agents/${encodeURIComponent(agentId)}/chat`,
        body,
        authToken,
        workspaceId,
        signal: ctrl.signal,
        onEvent: handleEvent,
        onError: (err) => {
          setLastError(err)
        },
        onClose: () => {
          bag.abort = null
          if (bag.cancelledByUser) {
            setIsStreaming(false)
            return
          }
          if (bag.lastEventKind === 'done') {
            setIsStreaming(false)
            return
          }
          // Stream dropped before 'done' — try resuming.
          bag.attemptReconnect()
        },
      })
    },
    [bag, handleEvent],
  )

  // ── Public: cancel ───────────────────────────────────────────────────────
  //
  // Sends POST /cancel; the still-open stream will receive `cancelled` +
  // `done` events from the server. We do NOT abort the local fetch here —
  // we want those terminal events to land. abort() is reserved for hard
  // teardown via reset().
  const cancel = useCallback(async () => {
    const sid = bag.sessionId
    if (!sid) return
    bag.cancelledByUser = true
    const authToken = useAuthStore.getState().accessToken ?? undefined
    const workspaceId = useWorkspaceStore.getState().currentWorkspaceId ?? undefined
    try {
      await cancelAgentSession(sid, authToken, workspaceId)
    } catch (err) {
      setLastError(err as Error)
    }
  }, [bag])

  // ── Public: respond (HITL) ───────────────────────────────────────────────
  const respond = useCallback(
    async (toolCallId: string, choiceId: string, extra?: Record<string, unknown>) => {
      const sid = bag.sessionId
      if (!sid) {
        throw new Error('No active session — cannot respond')
      }
      const authToken = useAuthStore.getState().accessToken ?? undefined
      const workspaceId = useWorkspaceStore.getState().currentWorkspaceId ?? undefined
      await respondToChoice(
        sid,
        { tool_call_id: toolCallId, choice_id: choiceId, extra },
        authToken,
        workspaceId,
      )
    },
    [bag],
  )

  // ── Public: retry (manual) ───────────────────────────────────────────────
  const retry = useCallback(() => {
    if (isStreaming) return
    setConnectionLost(false)
    bag.reconnectAttempt = 0
    bag.cancelledByUser = false
    startReconnectStream()
  }, [bag, isStreaming, startReconnectStream])

  // ── Public: reset ────────────────────────────────────────────────────────
  const reset = useCallback(() => {
    bag.abort?.abort()
    bag.abort = null
    if (bag.reconnectTimer) {
      clearTimeout(bag.reconnectTimer)
      bag.reconnectTimer = null
    }
    bag.cancelledByUser = true
    bag.sessionId = null
    bag.lastEventId = 0
    bag.lastEventKind = null
    bag.reconnectAttempt = 0
    setEvents([])
    setSessionId(null)
    setIsStreaming(false)
    setIsReconnecting(false)
    setConnectionLost(false)
    setLastError(null)
  }, [bag])

  // ── Cleanup on unmount ───────────────────────────────────────────────────
  //
  // We deliberately do NOT abort the in-flight SSE on unmount. The chat
  // bubble unmounts when the user closes the panel (bubbleState='closed'),
  // and we want the backend agent to finish the run regardless — its
  // final_message gets persisted to the chat session row and the user
  // sees it the next time they open the bubble or browse the session
  // history. Cancelling the request mid-flight on unmount caused the
  // backend to surface forced_finalize='cancelled' with an empty reply.
  //
  // The reconnect timer is still safe to clear — it's a no-op on a torn-
  // down component.
  useEffect(() => {
    return () => {
      if (bag.reconnectTimer) clearTimeout(bag.reconnectTimer)
    }
  }, [bag])

  return {
    events,
    isStreaming,
    lastError,
    sessionId,
    isReconnecting,
    connectionLost,
    startStream,
    cancel,
    respond,
    retry,
    reset,
  }
}

// ─── Shared context ────────────────────────────────────────────────────────
//
// Each call to useAgentStreamInstance() produces an independent state bag, so
// without sharing every chat sub-component would have its own (empty) events
// list. ChatBubble creates one instance and publishes it via this context so
// ChatHistory, ChatComposer, ChatStatusBar, etc. all see the same events.

const AgentStreamContext = createContext<UseAgentStreamResult | null>(null)

export function AgentStreamProvider({ children }: { children: ReactNode }) {
  const stream = useAgentStreamInstance()
  return createElement(AgentStreamContext.Provider, { value: stream }, children)
}

export function useAgentStream(): UseAgentStreamResult {
  const ctx = useContext(AgentStreamContext)
  if (ctx === null) {
    throw new Error(
      'useAgentStream must be called inside <AgentStreamProvider>',
    )
  }
  return ctx
}
