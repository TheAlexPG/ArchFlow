// We deliberately mutate fields on a stable bag object held by `useState`'s
// lazy init — see `StreamBag` below for rationale. The new react-hooks
// plugin (v7+) flags these mutations under `react-hooks/immutability`,
// but the alternative ("re-create every callback every turn") would
// invalidate handlers passed into in-flight fetch streams. Same trade-off
// as `frontend/src/hooks/use-realtime.ts`.
/* eslint-disable react-hooks/immutability */

import { createContext, createElement, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'

import {
  AgentStreamError,
  cancelAgentSession,
  reconnectAgent,
  respondToChoice,
  streamAgent,
} from '../../../lib/agent-stream'
import { refreshAccessToken } from '../../../lib/api-client'
import { maybeTitleSession } from './use-agent-sessions'
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
  /** Replace ``events`` with synthetic ``message`` frames so the chat
   *  history shows a previously-persisted conversation. Pairs with
   *  the agent-sessions detail endpoint at the panel level. */
  loadHistory: (
    messages: Array<{ role: 'user' | 'assistant'; content: string }>,
    sessionId: string,
  ) => void
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
  /** Set after we've asked the backend to LLM-name this session.
   *  Prevents firing the auto-title call on reconnects, on follow-up
   *  turns within the same session, and on resumed history. */
  titleRequested: boolean
  /** Set by onError when the server returned 401 (token expired). The
   *  matching onClose checks this and runs a refresh-then-retry once
   *  before falling into the normal reconnect loop. Cleared after the
   *  refresh attempt so a follow-up 401 doesn't loop forever. */
  pendingAuthRefresh: boolean
  /** True once we've burned the one-shot refresh+replay attempt for the
   *  current logical request — any further 401 means refresh is dead and
   *  we should surface connectionLost instead of looping. */
  authRefreshTried: boolean
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
    titleRequested: false,
    pendingAuthRefresh: false,
    authRefreshTried: false,
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

  // React Query client — captured at hook init so the SSE event handler
  // (a stable ``useCallback``) can invalidate the sessions list when the
  // backend's auto-title call lands.
  const queryClient = useQueryClient()

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

      // Fire auto-title on `done` rather than on the first `session` frame.
      // Two reasons:
      //   1. Race: when the session row is brand-new the SSE generator has
      //      only `db.flush()`-ed it; the actual commit happens when the
      //      generator finishes. A POST /auto-title issued at session-frame
      //      time opens its own DB session and 404s on the uncommitted row.
      //      By `done` the parent transaction has committed.
      //   2. Semantics: at `done` there is real assistant output to title
      //      from, not just an empty placeholder.
      // Resumed sessions short-circuit via `loadHistory` setting
      // `titleRequested = true`. Cancellation sets `cancelledByUser` so we
      // skip the call. Errors never emit `done`, so failed turns aren't
      // titled either.
      if (evt.kind === 'done' && !bag.titleRequested && !bag.cancelledByUser) {
        const sid = bag.sessionId
        if (sid) {
          bag.titleRequested = true
          maybeTitleSession(sid, () => {
            queryClient.invalidateQueries({ queryKey: ['agent-sessions'] })
            queryClient.invalidateQueries({ queryKey: ['agent-session', sid] })
          })
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
    [bag, queryClient],
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
        // 401 = token expired. Mark for refresh-and-retry in onClose.
        // Without this we'd burn through the reconnect budget firing the
        // same stale Bearer token at the server until connectionLost.
        if (
          err instanceof AgentStreamError &&
          err.code === 'http' &&
          err.status === 401 &&
          !bag.authRefreshTried
        ) {
          bag.pendingAuthRefresh = true
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
        // Refresh-then-retry once on a fresh 401 before falling into the
        // exponential reconnect loop. If refresh fails we surface
        // connectionLost; if it succeeds we replay the resume request.
        if (bag.pendingAuthRefresh && !bag.authRefreshTried) {
          bag.pendingAuthRefresh = false
          bag.authRefreshTried = true
          void refreshAccessToken().then((fresh) => {
            if (fresh) {
              startReconnectStream()
            } else {
              setConnectionLost(true)
              setIsStreaming(false)
            }
          })
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

  // ── Internal: dispatch the actual SSE POST ───────────────────────────────
  //
  // Split out from startStream() so the 401-refresh path in onClose can
  // re-fire the same fetch without re-pushing the optimistic user message
  // or clobbering the auth-retry flags. startStream() owns the user-facing
  // bookkeeping (transcript push, flag reset); _doStreamRequest only owns
  // the network call + its own onClose lifecycle.
  const dispatchStreamRequest = useCallback(
    (agentId: string, body: AgentInvokeBody) => {
      const ctrl = new AbortController()
      bag.abort = ctrl
      setIsStreaming(true)

      const authToken = useAuthStore.getState().accessToken ?? undefined
      const workspaceId =
        useWorkspaceStore.getState().currentWorkspaceId ?? undefined

      void streamAgent({
        url: `/api/v1/agents/${encodeURIComponent(agentId)}/chat`,
        body,
        authToken,
        workspaceId,
        signal: ctrl.signal,
        onEvent: handleEvent,
        onError: (err) => {
          // 401 path: agent-stream uses raw fetch and bypasses the axios
          // 401-retry interceptor in lib/api-client.ts. Without this hook
          // an expired access token would 401 the chat POST, then loop
          // through the entire reconnect budget firing the same stale
          // Bearer token until connectionLost. Defer the actual refresh
          // to onClose so we can re-fire the fetch cleanly afterwards.
          if (
            err instanceof AgentStreamError &&
            err.code === 'http' &&
            err.status === 401 &&
            !bag.authRefreshTried
          ) {
            bag.pendingAuthRefresh = true
            return
          }
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
          // Refresh-then-retry once on a fresh 401 before falling into
          // the resume-reconnect loop. If refresh fails we surface
          // connectionLost; if it succeeds we replay the original POST
          // (not /stream, because we never got a session id back yet).
          if (bag.pendingAuthRefresh && !bag.authRefreshTried) {
            bag.pendingAuthRefresh = false
            bag.authRefreshTried = true
            void refreshAccessToken().then((fresh) => {
              if (fresh) {
                dispatchStreamRequest(agentId, body)
              } else {
                setConnectionLost(true)
                setIsStreaming(false)
              }
            })
            return
          }
          // Stream dropped before 'done' — try resuming.
          bag.attemptReconnect()
        },
      })
    },
    [bag, handleEvent],
  )

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
      // Fresh user-initiated request: reset the one-shot 401 refresh flag
      // so a token that expires between turns can be refreshed once per
      // turn without ever falling through to connectionLost.
      bag.authRefreshTried = false
      bag.pendingAuthRefresh = false

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

      dispatchStreamRequest(agentId, body)
    },
    [bag, dispatchStreamRequest],
  )

  // ── Public: cancel ───────────────────────────────────────────────────────
  //
  // Stops the active generation as snappily as possible:
  //   1. Mark cancelledByUser so onClose stops the streaming spinner and
  //      the reconnect loop doesn't kick in.
  //   2. Abort the local SSE fetch — UI returns to idle even if the server
  //      takes a moment to react. (Previously we left the fetch open hoping
  //      the server's terminal "cancelled" / "done" frames would land —
  //      but if the user clicked cancel before the first ``session`` frame,
  //      ``bag.sessionId`` was null and this whole method was a no-op.)
  //   3. POST /cancel when we have a session id, so the LangGraph run also
  //      stops on the server and doesn't burn budget. When session id is
  //      not yet known we skip the POST — backend will finish the current
  //      step and persist whatever it has; from the user's POV the chat
  //      already looks idle.
  const cancel = useCallback(async () => {
    bag.cancelledByUser = true
    if (bag.abort) {
      try {
        bag.abort.abort()
      } catch {
        // already aborted — fine
      }
      bag.abort = null
    }
    if (bag.reconnectTimer) {
      clearTimeout(bag.reconnectTimer)
      bag.reconnectTimer = null
    }
    setIsStreaming(false)
    setIsReconnecting(false)
    const sid = bag.sessionId
    if (!sid) return
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

  // ── Public: loadHistory ──────────────────────────────────────────────────
  //
  // Seeds ``events`` with synthetic ``message`` frames so the chat history
  // shows a previously-persisted conversation. The build-render-items
  // bucketer already turns ``message`` events into UserMessage /
  // AssistantText render items, so no extra work is required downstream.
  //
  // Aborts any in-flight stream first — switching to an old session means
  // the user no longer cares about the current run.
  const loadHistory = useCallback(
    (
      messages: Array<{ role: 'user' | 'assistant'; content: string }>,
      sid: string,
    ) => {
      bag.abort?.abort()
      bag.abort = null
      if (bag.reconnectTimer) {
        clearTimeout(bag.reconnectTimer)
        bag.reconnectTimer = null
      }
      bag.cancelledByUser = true
      bag.sessionId = sid
      bag.lastEventId = 0
      bag.lastEventKind = null
      bag.reconnectAttempt = 0
      // Past sessions already have whatever title they're going to have —
      // don't re-fire the auto-title call when the user picks an old one.
      bag.titleRequested = true
      const seeded: AgentSSEEvent[] = []
      for (const m of messages) {
        if (!m.content) continue
        bag.lastEventId += 1
        seeded.push({
          id: bag.lastEventId,
          kind: 'message',
          payload: { role: m.role, text: m.content },
        })
      }
      setEvents(seeded)
      setSessionId(sid)
      setIsStreaming(false)
      setIsReconnecting(false)
      setConnectionLost(false)
      setLastError(null)
    },
    [bag],
  )

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
    bag.titleRequested = false
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
    loadHistory,
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
