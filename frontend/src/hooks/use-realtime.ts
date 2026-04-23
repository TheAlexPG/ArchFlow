import { useEffect, useRef, useCallback, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useAuthStore } from '../stores/auth-store'
import { useWorkspaceStore } from '../stores/workspace-store'

// ── Inline types ──────────────────────────────────────────────────────────────

interface PresenceUser {
  user_id: string
  user_name: string
}

export interface CursorState {
  x: number
  y: number
  user_name: string
  updatedAt: number
}

export interface SelectionState {
  ids: string[]
  user_name: string
}

export interface DiagramSocketResult {
  cursors: Record<string, CursorState>
  /** user_id → node ids that user has selected. Cleared on presence.leave
   *  or when the user broadcasts an empty selection. */
  selections: Record<string, SelectionState>
  presence: PresenceUser[]
  sendCursor: (x: number, y: number) => void
  sendSelection: (ids: string[]) => void
}

// ── WS URL helper ─────────────────────────────────────────────────────────────

function wsUrl(path: string, token: string): string {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${location.host}${path}?token=${encodeURIComponent(token)}`
}

/** Merge or insert an entity into a (possibly undefined) id-keyed list.
 *  Used by useWorkspaceSocket to patch TanStack cache on object/connection/
 *  diagram events without hitting the network.
 *
 *  Guard: setQueriesData({queryKey: ['objects']}) matches ALL queries
 *  beginning with that prefix, which includes single-entity caches like
 *  ['objects', id]. If prev isn't an array (e.g. a single object), we
 *  leave it untouched — the single-entity merge is handled separately. */
function mergeEntity<T extends { id: string }>(
  prev: T[] | T | undefined,
  next: T,
): T[] | T | undefined {
  // setQueriesData({ queryKey: ['foo'] }) matches by PREFIX, so a callback
  // here can receive both the list cache (['foo', { ... }], an array) AND
  // the individual-item cache (['foo', id], a single object). Wrapping a
  // single object into an array would corrupt the individual cache into an
  // array-shaped blob that useFoo(id) can't read. Leave non-arrays alone —
  // the individual cache is patched explicitly via setQueryData elsewhere.
  if (prev === undefined) return [next]
  if (!Array.isArray(prev)) return prev
  const idx = prev.findIndex((row) => row.id === next.id)
  if (idx === -1) return [...prev, next]
  const merged = [...prev]
  merged[idx] = { ...prev[idx], ...next }
  return merged
}

/** Safe filter for list caches matched by prefix: only operate on arrays,
 *  pass everything else through untouched. */
function filterList<T>(
  prev: T[] | unknown,
  keep: (row: T) => boolean,
): T[] | unknown {
  if (!Array.isArray(prev)) return prev
  return prev.filter(keep)
}

// ── useDiagramSocket ──────────────────────────────────────────────────────────

export function useDiagramSocket(diagramId: string | null): DiagramSocketResult {
  const token = useAuthStore((s) => s.accessToken)
  const queryClient = useQueryClient()

  const [cursors, setCursors] = useState<Record<string, CursorState>>({})
  const [selections, setSelections] = useState<Record<string, SelectionState>>({})
  const [presence, setPresence] = useState<PresenceUser[]>([])

  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const evictTimers = useRef<Record<string, ReturnType<typeof setTimeout>>>({})
  const lastCursorSend = useRef<number>(0)
  // Track current diagramId + token inside ref so the cleanup function always
  // sees the latest value without re-creating the effect.
  const paramsRef = useRef({ diagramId, token })
  paramsRef.current = { diagramId, token }

  const clearEvictTimer = useCallback((userId: string) => {
    if (evictTimers.current[userId]) {
      clearTimeout(evictTimers.current[userId])
      delete evictTimers.current[userId]
    }
  }, [])

  const scheduleEvict = useCallback(
    (userId: string) => {
      clearEvictTimer(userId)
      evictTimers.current[userId] = setTimeout(() => {
        setCursors((prev) => {
          const next = { ...prev }
          delete next[userId]
          return next
        })
        delete evictTimers.current[userId]
      }, 5000)
    },
    [clearEvictTimer],
  )

  useEffect(() => {
    if (!diagramId || !token) return

    let backoff = 500
    let destroyed = false

    function connect() {
      if (destroyed) return
      const ws = new WebSocket(wsUrl(`/api/v1/ws/diagrams/${diagramId}`, token!))
      wsRef.current = ws

      ws.onmessage = (ev) => {
        let msg: Record<string, unknown>
        try {
          msg = JSON.parse(ev.data as string) as Record<string, unknown>
        } catch {
          return
        }
        const type = msg.type as string | undefined

        if (type === 'presence.init') {
          setPresence((msg.users as PresenceUser[]) ?? [])
        } else if (type === 'presence.join') {
          const user = msg.user as PresenceUser
          setPresence((prev) => {
            if (prev.some((u) => u.user_id === user.user_id)) return prev
            return [...prev, user]
          })
        } else if (type === 'presence.leave') {
          const user = msg.user as PresenceUser
          setPresence((prev) => prev.filter((u) => u.user_id !== user.user_id))
          setCursors((prev) => {
            const next = { ...prev }
            delete next[user.user_id]
            return next
          })
          setSelections((prev) => {
            const next = { ...prev }
            delete next[user.user_id]
            return next
          })
          clearEvictTimer(user.user_id)
        } else if (type === 'selection') {
          const userId = msg.user_id as string
          const ids = (msg.ids as string[]) ?? []
          setSelections((prev) => {
            if (ids.length === 0) {
              if (!(userId in prev)) return prev
              const next = { ...prev }
              delete next[userId]
              return next
            }
            return {
              ...prev,
              [userId]: { ids, user_name: msg.user_name as string },
            }
          })
        } else if (
          type === 'diagram_object.added' ||
          type === 'diagram_object.updated'
        ) {
          const row = msg.diagram_object as { id: string } | undefined
          const dId = msg.diagram_id as string | undefined
          if (dId && row) {
            queryClient.setQueriesData(
              { queryKey: ['diagram-objects', dId] },
              (prev: unknown) =>
                mergeEntity(prev as Array<{ id: string }> | undefined, row),
            )
          } else if (dId) {
            void queryClient.invalidateQueries({
              queryKey: ['diagram-objects', dId],
            })
          }
        } else if (type === 'diagram_object.removed') {
          const dId = msg.diagram_id as string | undefined
          const objectId = msg.object_id as string | undefined
          if (dId && objectId) {
            queryClient.setQueriesData(
              { queryKey: ['diagram-objects', dId] },
              (prev: unknown) =>
                filterList<{ object_id: string }>(
                  prev,
                  (r) => r.object_id !== objectId,
                ),
            )
          } else if (dId) {
            void queryClient.invalidateQueries({
              queryKey: ['diagram-objects', dId],
            })
          }
        } else if (type === 'object.updated') {
          const obj = msg.object as { id: string } | undefined
          if (obj) {
            queryClient.setQueriesData(
              { queryKey: ['objects'] },
              (prev: unknown) => mergeEntity(prev as never, obj),
            )
            queryClient.setQueryData(['objects', obj.id], obj as never)
          } else {
            void queryClient.invalidateQueries({ queryKey: ['objects'] })
          }
        } else if (type === 'object.deleted') {
          const id = msg.id as string | undefined
          if (id) {
            queryClient.setQueriesData(
              { queryKey: ['objects'] },
              (prev: unknown) =>
                filterList<{ id: string }>(prev, (o) => o.id !== id),
            )
            queryClient.removeQueries({ queryKey: ['objects', id] })
          } else {
            void queryClient.invalidateQueries({ queryKey: ['objects'] })
          }
        } else if (
          type === 'connection.created' ||
          type === 'connection.updated'
        ) {
          const conn = msg.connection as { id: string } | undefined
          if (conn) {
            queryClient.setQueriesData(
              { queryKey: ['connections'] },
              (prev: unknown) => mergeEntity(prev as never, conn),
            )
          } else {
            void queryClient.invalidateQueries({ queryKey: ['connections'] })
          }
        } else if (type === 'connection.deleted') {
          const id = msg.id as string | undefined
          if (id) {
            queryClient.setQueriesData(
              { queryKey: ['connections'] },
              (prev: unknown) =>
                filterList<{ id: string }>(prev, (c) => c.id !== id),
            )
          } else {
            void queryClient.invalidateQueries({ queryKey: ['connections'] })
          }
        } else if (type === 'cursor') {
          const userId = msg.user_id as string
          setCursors((prev) => ({
            ...prev,
            [userId]: {
              x: msg.x as number,
              y: msg.y as number,
              user_name: msg.user_name as string,
              updatedAt: Date.now(),
            },
          }))
          scheduleEvict(userId)
        }
        // selection frames and pong are accepted but not stored in state
      }

      ws.onopen = () => {
        // Reset backoff on successful connection
        backoff = 500
      }

      ws.onclose = () => {
        if (destroyed) return
        reconnectTimer.current = setTimeout(() => {
          backoff = Math.min(backoff * 2, 10000)
          connect()
        }, backoff)
      }

      ws.onerror = () => {
        // onclose will fire after onerror — let it handle reconnect
        ws.close()
      }
    }

    connect()

    return () => {
      destroyed = true
      if (reconnectTimer.current) {
        clearTimeout(reconnectTimer.current)
        reconnectTimer.current = null
      }
      // Evict all cursor timers
      for (const t of Object.values(evictTimers.current)) {
        clearTimeout(t)
      }
      evictTimers.current = {}
      wsRef.current?.close()
      wsRef.current = null
      setCursors({})
      setSelections({})
      setPresence([])
    }
    // reconnect on diagramId or token change
  }, [diagramId, token, scheduleEvict, clearEvictTimer, queryClient])

  const sendCursor = useCallback((x: number, y: number) => {
    if (document.hidden) return
    const ws = wsRef.current
    if (!ws || ws.readyState !== WebSocket.OPEN) return
    // Throttle to ~20fps (50ms)
    const now = Date.now()
    if (now - lastCursorSend.current < 50) return
    lastCursorSend.current = now
    ws.send(JSON.stringify({ type: 'cursor', x, y }))
  }, [])

  const sendSelection = useCallback((ids: string[]) => {
    const ws = wsRef.current
    if (!ws || ws.readyState !== WebSocket.OPEN) return
    ws.send(JSON.stringify({ type: 'selection', ids }))
  }, [])

  return { cursors, selections, presence, sendCursor, sendSelection }
}

// ── useUserSocket ─────────────────────────────────────────────────────────────

/** Opens the per-user notification stream — notifications.new events
 *  invalidate the notifications query so the bell badge updates live. */
export function useUserSocket(): void {
  const token = useAuthStore((s) => s.accessToken)
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  const queryClient = useQueryClient()

  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (!isAuthenticated || !token) return

    let backoff = 500
    let destroyed = false

    function connect() {
      if (destroyed) return
      const ws = new WebSocket(wsUrl('/api/v1/ws/me', token!))
      wsRef.current = ws

      ws.onmessage = (ev) => {
        let msg: Record<string, unknown>
        try {
          msg = JSON.parse(ev.data as string) as Record<string, unknown>
        } catch {
          return
        }
        if (msg.type === 'notification.new') {
          void queryClient.invalidateQueries({ queryKey: ['notifications'] })
        }
      }

      ws.onopen = () => {
        backoff = 500
      }

      ws.onclose = () => {
        if (destroyed) return
        reconnectTimer.current = setTimeout(() => {
          backoff = Math.min(backoff * 2, 10000)
          connect()
        }, backoff)
      }

      ws.onerror = () => {
        ws.close()
      }
    }

    connect()

    return () => {
      destroyed = true
      if (reconnectTimer.current) {
        clearTimeout(reconnectTimer.current)
        reconnectTimer.current = null
      }
      wsRef.current?.close()
      wsRef.current = null
    }
  }, [isAuthenticated, token, queryClient])
}

// ── useWorkspaceSocket ────────────────────────────────────────────────────────

export function useWorkspaceSocket(): void {
  const token = useAuthStore((s) => s.accessToken)
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  const workspaceId = useWorkspaceStore((s) => s.currentWorkspaceId)
  const queryClient = useQueryClient()

  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (!isAuthenticated || !token || !workspaceId) return

    let backoff = 500
    let destroyed = false

    function connect() {
      if (destroyed) return
      const ws = new WebSocket(
        wsUrl(`/api/v1/ws/workspace/${workspaceId}`, token!),
      )
      wsRef.current = ws

      ws.onmessage = (ev) => {
        let msg: Record<string, unknown>
        try {
          msg = JSON.parse(ev.data as string) as Record<string, unknown>
        } catch {
          return
        }
        const type = msg.type as string | undefined
        if (!type) return

        // Fast path: the backend ships the full entity payload inside the
        // event so we can merge it straight into TanStack cache — no
        // refetch round-trip, other clients see changes in ~one tick.
        // Fallback to invalidate when the payload isn't available
        // (deletes, or events that pre-date this optimization).
        if (type === 'object.created' || type === 'object.updated') {
          const obj = msg.object as { id: string } | undefined
          if (obj) {
            queryClient.setQueriesData(
              { queryKey: ['objects'] },
              (prev: unknown) => mergeEntity(prev as never, obj),
            )
            queryClient.setQueryData(['objects', obj.id], obj as never)
          } else {
            void queryClient.invalidateQueries({ queryKey: ['objects'] })
          }
        } else if (type === 'object.deleted') {
          const id = msg.id as string | undefined
          if (id) {
            queryClient.setQueriesData(
              { queryKey: ['objects'] },
              (prev: unknown) =>
                filterList<{ id: string }>(prev, (o) => o.id !== id),
            )
            queryClient.removeQueries({ queryKey: ['objects', id] })
          } else {
            void queryClient.invalidateQueries({ queryKey: ['objects'] })
          }
        } else if (type === 'connection.created' || type === 'connection.updated') {
          const conn = msg.connection as { id: string } | undefined
          if (conn) {
            queryClient.setQueriesData(
              { queryKey: ['connections'] },
              (prev: unknown) => mergeEntity(prev as never, conn),
            )
          } else {
            void queryClient.invalidateQueries({ queryKey: ['connections'] })
          }
        } else if (type === 'connection.deleted') {
          const id = msg.id as string | undefined
          if (id) {
            queryClient.setQueriesData(
              { queryKey: ['connections'] },
              (prev: unknown) =>
                filterList<{ id: string }>(prev, (c) => c.id !== id),
            )
          } else {
            void queryClient.invalidateQueries({ queryKey: ['connections'] })
          }
        } else if (
          type === 'diagram_object.added' ||
          type === 'diagram_object.updated'
        ) {
          const diagramId = msg.diagram_id as string | undefined
          const row = msg.diagram_object as { id: string } | undefined
          if (diagramId && row) {
            queryClient.setQueriesData(
              { queryKey: ['diagram-objects', diagramId] },
              (prev: unknown) => mergeEntity(prev as never, row),
            )
          } else if (diagramId) {
            void queryClient.invalidateQueries({
              queryKey: ['diagram-objects', diagramId],
            })
          }
        } else if (type === 'diagram_object.removed') {
          const diagramId = msg.diagram_id as string | undefined
          const objectId = msg.object_id as string | undefined
          if (diagramId && objectId) {
            queryClient.setQueriesData(
              { queryKey: ['diagram-objects', diagramId] },
              (prev: unknown) =>
                filterList<{ object_id: string }>(
                  prev,
                  (r) => r.object_id !== objectId,
                ),
            )
          } else if (diagramId) {
            void queryClient.invalidateQueries({
              queryKey: ['diagram-objects', diagramId],
            })
          }
        } else if (type === 'diagram.created' || type === 'diagram.updated') {
          const diagram = msg.diagram as { id: string } | undefined
          if (diagram) {
            queryClient.setQueriesData(
              { queryKey: ['diagrams'] },
              (prev: unknown) => mergeEntity(prev as never, diagram),
            )
            queryClient.setQueryData(['diagrams', diagram.id], diagram)
          } else {
            void queryClient.invalidateQueries({ queryKey: ['diagrams'] })
          }
        } else if (type === 'diagram.deleted') {
          const id = msg.id as string | undefined
          if (id) {
            queryClient.setQueriesData(
              { queryKey: ['diagrams'] },
              (prev: unknown) =>
                filterList<{ id: string }>(prev, (d) => d.id !== id),
            )
            queryClient.removeQueries({ queryKey: ['diagrams', id] })
          } else {
            void queryClient.invalidateQueries({ queryKey: ['diagrams'] })
          }
        } else if (type === 'notification.new') {
          // Let the bell's own query refetch — payload has only the
          // unread_count delta, not the full row shape.
          void queryClient.invalidateQueries({ queryKey: ['notifications'] })
        } else if (
          type === 'technology.created' ||
          type === 'technology.updated' ||
          type === 'technology.deleted'
        ) {
          // Cheap invalidate — the catalog list is small (~200 rows) and
          // rarely mutated, so a full refetch keeps the picker consistent
          // across all filter/scope variants without us merging by hand.
          void queryClient.invalidateQueries({
            queryKey: ['technologies', workspaceId],
          })
        }
      }

      ws.onopen = () => {
        backoff = 500
      }

      ws.onclose = () => {
        if (destroyed) return
        reconnectTimer.current = setTimeout(() => {
          backoff = Math.min(backoff * 2, 10000)
          connect()
        }, backoff)
      }

      ws.onerror = () => {
        ws.close()
      }
    }

    connect()

    return () => {
      destroyed = true
      if (reconnectTimer.current) {
        clearTimeout(reconnectTimer.current)
        reconnectTimer.current = null
      }
      wsRef.current?.close()
      wsRef.current = null
    }
  }, [isAuthenticated, token, workspaceId, queryClient])
}
