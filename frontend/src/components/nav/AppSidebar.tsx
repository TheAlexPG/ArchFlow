import { NavLink } from 'react-router-dom'
import { useAuthStore } from '../../stores/auth-store'

const NAV_ITEMS = [
  { label: 'Overview', icon: '◉', path: '/' },
  { label: 'Diagrams', icon: '▦', path: '/diagrams' },
  { label: 'Model Objects', icon: '☰', path: '/objects' },
  { label: 'Connections', icon: '⇄', path: '/connections' },
  { label: 'Drafts', icon: '✎', path: '/drafts' },
  { label: 'Activity', icon: '⏱', path: '/activity' },
  { label: 'Settings', icon: '⚙', path: '/settings' },
]

/**
 * Shared top-level sidebar for dashboard pages (Overview / Diagrams /
 * Objects / Connections / Activity). The diagram editor page uses its own
 * in-canvas navigation and does not render this.
 */
export function AppSidebar() {
  const { logout } = useAuthStore()

  return (
    <div
      style={{
        width: 200,
        borderRight: '1px solid #262626',
        display: 'flex',
        flexDirection: 'column',
        padding: '16px 0',
        background: '#111',
      }}
    >
      <div style={{ padding: '0 16px', marginBottom: 24 }}>
        <div style={{ fontWeight: 700, fontSize: 16 }}>ArchFlow</div>
      </div>

      <nav style={{ flex: 1 }}>
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            end={item.path === '/'}
            style={({ isActive }) => ({
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              padding: '8px 16px',
              fontSize: 13,
              color: isActive ? '#f5f5f5' : '#737373',
              background: isActive ? '#1a1a1a' : 'transparent',
              textDecoration: 'none',
              borderLeft: isActive ? '2px solid #3b82f6' : '2px solid transparent',
            })}
          >
            <span style={{ opacity: 0.6 }}>{item.icon}</span>
            {item.label}
          </NavLink>
        ))}
      </nav>

      <div style={{ padding: '8px 16px', borderTop: '1px solid #262626' }}>
        <button
          onClick={logout}
          style={{
            background: 'none',
            border: 'none',
            color: '#737373',
            cursor: 'pointer',
            fontSize: 12,
            padding: 0,
          }}
        >
          Sign out
        </button>
      </div>
    </div>
  )
}
