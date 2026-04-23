import { memo } from 'react'

interface Props {
  users: { user_id: string; user_name: string }[]
}

function hueFromId(id: string): number {
  let h = 5381
  for (let i = 0; i < id.length; i++) {
    h = ((h << 5) + h) ^ id.charCodeAt(i)
  }
  return Math.abs(h) % 360
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return '?'
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (parts[0][0] + parts[1][0]).toUpperCase()
}

/**
 * Avatar stack pinned to the top-right of the canvas. Shows who else is
 * in this diagram room — colors match the cursors + selection outlines,
 * so the user can match a label to a pointer at a glance.
 */
export const PresenceRoster = memo(function PresenceRoster({ users }: Props) {
  if (users.length === 0) return null

  return (
    <div
      style={{
        position: 'absolute',
        top: 16,
        right: 64,
        zIndex: 1001,
        display: 'flex',
        alignItems: 'center',
        gap: 0,
        pointerEvents: 'auto',
      }}
    >
      {users.map((u, i) => {
        const hue = hueFromId(u.user_id)
        return (
          <div
            key={u.user_id}
            title={u.user_name}
            style={{
              width: 28,
              height: 28,
              borderRadius: '50%',
              background: `hsl(${hue}, 70%, 55%)`,
              color: '#0a0a0a',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: 11,
              fontWeight: 700,
              border: '2px solid #0a0a0a',
              marginLeft: i === 0 ? 0 : -10,
              boxShadow: '0 2px 6px rgba(0,0,0,0.4)',
              cursor: 'default',
            }}
          >
            {initials(u.user_name)}
          </div>
        )
      })}
    </div>
  )
})
