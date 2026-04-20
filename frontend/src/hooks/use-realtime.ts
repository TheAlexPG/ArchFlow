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

export interface DiagramSocketResult {
  cursors: Record<string, CursorState>
  presence: PresenceUser[]
  sendCursor: (x: number, y: number) => void
  sendSelection: (ids: string[]) => void
}

// ── WS URL helper ─────────────────────────────────────────────────────────────

function wsUrl(path: string, token: string): string {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${location.host}${path}?token=${encodeURIComponent(token)}`
}

// ── useDiagramSocket ──────────────────────────────────────────────────────────

export function useDiagramSocket(diagramId: string | null): DiagramSocketResult {
  const token = useAuthStore((s) => s.accessToken)

  const [cursors, setCursors] = useState<Record<string, CursorState>>({})
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
          clearEvictTimer(user.user_id)
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
      setPresence([])
    }
    // reconnect on diagramId or token change
  }, [diagramId, token, scheduleEvict, clearEvictTimer])

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

  return { cursors, presence, sendCursor, sendSelection }
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

        if (type.startsWith('object.')) {
          void queryClient.invalidateQueries({ queryKey: ['objects'] })
        } else if (type.startsWith('connection.')) {
          void queryClient.invalidateQueries({ queryKey: ['connections'] })
        } else if (type.startsWith('diagram.')) {
          void queryClient.invalidateQueries({ queryKey: ['diagrams'] })
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
