import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  useMarkAllNotificationsRead,
  useMarkNotificationRead,
  useNotifications,
  useUnreadNotificationCount,
} from '../../hooks/use-api'
import { useUserSocket } from '../../hooks/use-realtime'

/**
 * Bell with unread badge. Opens a dropdown listing recent notifications.
 * Fed by both periodic polling (fallback) and the per-user WebSocket
 * (instant — triggered when someone @-mentions you).
 */
export function NotificationsBell() {
  const { data: unread = 0 } = useUnreadNotificationCount()
  const { data: items = [] } = useNotifications()
  const markRead = useMarkNotificationRead()
  const markAll = useMarkAllNotificationsRead()
  const [open, setOpen] = useState(false)
  const navigate = useNavigate()

  // Spin up the per-user socket so notification.new events push straight
  // into the TanStack cache via useWorkspaceSocket's invalidation logic.
  useUserSocket()

  const dropdownRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const onDocClick = (e: MouseEvent) => {
      if (!dropdownRef.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [open])

  const handleClick = (id: string, target: string | null) => {
    markRead.mutate(id)
    setOpen(false)
    if (target) navigate(target)
  }

  return (
    <div style={{ position: 'relative' }} ref={dropdownRef}>
      <button
        onClick={() => setOpen((v) => !v)}
        style={{
          background: 'none',
          border: 'none',
          color: '#a3a3a3',
          cursor: 'pointer',
          fontSize: 16,
          padding: '4px 8px',
          position: 'relative',
        }}
        title={unread > 0 ? `${unread} unread` : 'Notifications'}
      >
        <span>🔔</span>
        {unread > 0 && (
          <span
            style={{
              position: 'absolute',
              top: 0,
              right: 2,
              minWidth: 16,
              height: 16,
              padding: '0 4px',
              borderRadius: 8,
              background: '#ef4444',
              color: '#fff',
              fontSize: 10,
              fontWeight: 700,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              lineHeight: 1,
            }}
          >
            {unread > 99 ? '99+' : unread}
          </span>
        )}
      </button>

      {open && (
        <div
          style={{
            position: 'absolute',
            top: '100%',
            left: 0,
            marginTop: 4,
            width: 320,
            maxHeight: 420,
            overflowY: 'auto',
            background: '#171717',
            border: '1px solid #333',
            borderRadius: 8,
            boxShadow: '0 8px 24px rgba(0,0,0,0.5)',
            zIndex: 100,
          }}
        >
          <div
            style={{
              padding: '10px 12px',
              borderBottom: '1px solid #262626',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
            }}
          >
            <span style={{ fontSize: 12, fontWeight: 600, color: '#d4d4d4' }}>
              Notifications
            </span>
            {unread > 0 && (
              <button
                onClick={() => markAll.mutate()}
                style={{
                  background: 'none',
                  border: 'none',
                  color: '#3b82f6',
                  fontSize: 11,
                  cursor: 'pointer',
                  padding: 0,
                }}
              >
                Mark all read
              </button>
            )}
          </div>
          {items.length === 0 ? (
            <div
              style={{
                padding: 20,
                fontSize: 12,
                color: '#737373',
                fontStyle: 'italic',
                textAlign: 'center',
              }}
            >
              No notifications yet
            </div>
          ) : (
            items.map((n) => (
              <button
                key={n.id}
                onClick={() => handleClick(n.id, n.target_url)}
                style={{
                  display: 'block',
                  width: '100%',
                  textAlign: 'left',
                  padding: '10px 12px',
                  background: n.read_at ? 'transparent' : '#1e293b',
                  border: 'none',
                  borderBottom: '1px solid #262626',
                  cursor: 'pointer',
                  color: 'inherit',
                }}
              >
                <div
                  style={{
                    fontSize: 12,
                    fontWeight: n.read_at ? 400 : 600,
                    color: '#e5e5e5',
                    marginBottom: 2,
                  }}
                >
                  {n.title}
                </div>
                {n.body && (
                  <div
                    style={{
                      fontSize: 11,
                      color: '#a3a3a3',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {n.body}
                  </div>
                )}
                <div style={{ fontSize: 10, color: '#525252', marginTop: 4 }}>
                  {new Date(n.created_at).toLocaleString()}
                </div>
              </button>
            ))
          )}
        </div>
      )}
    </div>
  )
}
