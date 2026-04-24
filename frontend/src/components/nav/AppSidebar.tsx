import { NavLink } from 'react-router-dom'
import { useAuthStore } from '../../stores/auth-store'
import { useDrafts, useMe, useMyInvites } from '../../hooks/use-api'
import { NotificationsBell } from './NotificationsBell'
import { WorkspaceSwitcher } from './WorkspaceSwitcher'
import { Avatar } from '../ui/Avatar'
import { SectionLabel } from '../ui/SectionLabel'
import { Pill } from '../ui/Pill'
import { cn } from '../../utils/cn'

// ─── Nav config ────────────────────────────────────────────────────────────

interface NavItemDef {
  label: string
  path: string
  icon: React.ReactNode
  end?: boolean
}

// Stroke SVG icons matching the reference HTML (lines 571-619)
const OverviewIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
    <rect x="3" y="3" width="7" height="9" rx="1"/>
    <rect x="14" y="3" width="7" height="5" rx="1"/>
    <rect x="14" y="12" width="7" height="9" rx="1"/>
    <rect x="3" y="16" width="7" height="5" rx="1"/>
  </svg>
)

const DiagramsIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
    <path d="M21 12V7a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h7"/>
    <circle cx="17" cy="17" r="4"/>
    <path d="m20 20-1.5-1.5"/>
  </svg>
)

const ObjectsIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
    <circle cx="6" cy="6" r="3"/>
    <circle cx="18" cy="18" r="3"/>
    <path d="M6 9v6a3 3 0 0 0 3 3h6"/>
  </svg>
)

const ConnectionsIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
    <path d="M8 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V5a2 2 0 0 0-2-2h-3"/>
    <path d="M9 14l2 2 4-4"/>
    <rect x="8" y="2" width="8" height="4" rx="1"/>
  </svg>
)

const DraftsIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
    <path d="M12 5v14M5 12h14"/>
  </svg>
)

const TechnologiesIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
    <rect x="3" y="3" width="7" height="7" rx="1"/>
    <rect x="14" y="3" width="7" height="7" rx="1"/>
    <rect x="3" y="14" width="7" height="7" rx="1"/>
    <circle cx="17.5" cy="17.5" r="3.5"/>
  </svg>
)

const ActivityIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
    <path d="M12 2v2m0 16v2M4 12H2m20 0h-2m-2.93-7.07L15.65 6.34m-7.3 11.32L6.93 19.07M19.07 19.07l-1.42-1.41m-11.3-11.31L4.93 4.93"/>
    <circle cx="12" cy="12" r="4"/>
  </svg>
)

const VersionsIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
    <path d="M12 8v4l3 3M12 3v.01M3 12v.01M12 21v-.01M21 12v-.01"/>
    <circle cx="12" cy="12" r="9"/>
  </svg>
)

const MembersIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
    <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/>
    <circle cx="9" cy="7" r="4"/>
    <path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>
  </svg>
)

const InvitesIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
    <path d="M21 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-3"/>
    <path d="m16 12 5-5M14 7l-4 4 2 2 4-4"/>
  </svg>
)

const TeamsIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
    <circle cx="12" cy="12" r="3"/>
    <path d="M12 1v6m0 10v6m-11-11h6m10 0h6m-2.5-8.5L16 7m-8 10-4.5 4.5M16 17l4.5 4.5M8 7 3.5 2.5"/>
  </svg>
)

const SettingsIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
    <circle cx="12" cy="12" r="3"/>
    <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
  </svg>
)

const SignOutIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
    <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>
    <path d="m16 17 5-5-5-5M21 12H9"/>
  </svg>
)

// ─── Nav item sections ──────────────────────────────────────────────────────

const MAIN_ITEMS: NavItemDef[] = [
  { label: 'Overview',      path: '/',            icon: <OverviewIcon />,     end: true },
  { label: 'Diagrams',      path: '/diagrams',    icon: <DiagramsIcon /> },
  { label: 'Model Objects', path: '/objects',      icon: <ObjectsIcon /> },
  { label: 'Connections',   path: '/connections',  icon: <ConnectionsIcon /> },
  { label: 'Technologies',  path: '/technologies', icon: <TechnologiesIcon /> },
]

const WORKSPACE_ITEMS: NavItemDef[] = [
  { label: 'Drafts',    path: '/drafts',   icon: <DraftsIcon /> },
  { label: 'Activity',  path: '/activity', icon: <ActivityIcon /> },
  { label: 'Versions',  path: '/versions', icon: <VersionsIcon /> },
]

const TEAM_ITEMS: NavItemDef[] = [
  { label: 'Members',   path: '/members', icon: <MembersIcon /> },
  { label: 'Invites',   path: '/invites', icon: <InvitesIcon /> },
  { label: 'Teams',     path: '/teams',   icon: <TeamsIcon /> },
]

const SETTINGS_ITEM: NavItemDef = {
  label: 'Settings', path: '/settings', icon: <SettingsIcon />,
}

// ─── NavRow ─────────────────────────────────────────────────────────────────

function NavRow({
  item,
  badge,
}: {
  item: NavItemDef
  badge?: React.ReactNode
}) {
  return (
    <NavLink
      to={item.path}
      end={item.end}
      className={({ isActive }) =>
        cn(
          'flex items-center gap-2.5 px-2.5 py-[7px] rounded-md',
          'text-[13px] text-text-2 transition-all duration-[120ms]',
          'hover:bg-surface hover:text-text-base',
          isActive
            ? 'bg-surface text-text-base shadow-[inset_2px_0_0_theme(colors.coral)]'
            : '',
        )
      }
    >
      <span className="flex-shrink-0 text-current">{item.icon}</span>
      <span className="flex-1 truncate">{item.label}</span>
      {badge}
    </NavLink>
  )
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function getInitialsFromName(name: string): string {
  const words = name.trim().split(/\s+/)
  if (words.length >= 2) {
    return (words[0][0] + words[1][0]).toUpperCase()
  }
  return name.slice(0, 2).toUpperCase()
}

function getInitialsFromEmail(email: string): string {
  const local = email.split('@')[0]
  const parts = local.split(/[._\-+]/)
  if (parts.length >= 2) {
    return (parts[0][0] + parts[1][0]).toUpperCase()
  }
  return local.slice(0, 2).toUpperCase()
}

// ─── AppSidebar ──────────────────────────────────────────────────────────────

/**
 * Shared top-level sidebar for dashboard pages (Overview / Diagrams /
 * Objects / Connections / Activity). The diagram editor page uses its own
 * in-canvas navigation and does not render this.
 */
export function AppSidebar() {
  const { logout } = useAuthStore()
  const { data: invites = [] } = useMyInvites()
  const pendingInviteCount = invites.length

  const { data: me, isLoading: meLoading } = useMe()

  const initials = me
    ? (me.name ? getInitialsFromName(me.name) : getInitialsFromEmail(me.email))
    : null
  const displayName = me ? (me.name || me.email.split('@')[0]) : null
  const email = me?.email ?? null

  const { data: drafts = [] } = useDrafts()
  const openDraftCount = drafts.filter((d) => d.status === 'open').length

  return (
    <div className="w-[240px] flex-shrink-0 border-r border-border-base bg-panel flex flex-col h-full">

      {/* ── Top block ──────────────────────────────────────────────────── */}
      <div className="p-4 border-b border-border-base">
        {/* Logo row */}
        <div className="flex items-center gap-2 mb-3">
          <svg width="18" height="18" viewBox="0 0 512 512" aria-hidden="true">
            <line x1="128" y1="400" x2="256" y2="112" stroke="#FF6B35" strokeWidth="34" strokeLinecap="round"/>
            <line x1="384" y1="400" x2="256" y2="112" stroke="#FF6B35" strokeWidth="34" strokeLinecap="round"/>
            <line x1="192" y1="280" x2="320" y2="280" stroke="#FF6B35" strokeWidth="34" strokeLinecap="round"/>
            <circle cx="256" cy="112" r="50" fill="#FF8552"/>
            <circle cx="128" cy="400" r="50" fill="#FF8552"/>
            <circle cx="384" cy="400" r="50" fill="#FF8552"/>
          </svg>
          <span className="text-[14px] font-semibold text-text-base flex-1">ArchFlow</span>
          <NotificationsBell />
        </div>

        {/* Workspace switcher — keep existing logic, restyle wrapper */}
        <WorkspaceSwitcher />
      </div>

      {/* ── Nav body ───────────────────────────────────────────────────── */}
      <nav className="flex-1 px-3 py-4 space-y-0.5 overflow-y-auto">

        {/* Main */}
        <div className="pb-2">
          <SectionLabel className="px-2 pb-2 pt-0">Main</SectionLabel>
        </div>
        {MAIN_ITEMS.map((item) => (
          <NavRow key={item.path} item={item} />
        ))}

        {/* Workspace */}
        <div className="pb-2 pt-5">
          <SectionLabel className="px-2 pb-2 pt-0">Workspace</SectionLabel>
        </div>
        {WORKSPACE_ITEMS.map((item) => {
          const badge =
            item.path === '/drafts' && openDraftCount > 0 ? (
              <Pill variant="draft" className="ml-auto px-1.5 py-0 text-[9.5px]">
                {openDraftCount} NEW
              </Pill>
            ) : undefined
          return <NavRow key={item.path} item={item} badge={badge} />
        })}

        {/* Team */}
        <div className="pb-2 pt-5">
          <SectionLabel className="px-2 pb-2 pt-0">Team</SectionLabel>
        </div>
        {TEAM_ITEMS.map((item) => {
          const badge =
            item.path === '/invites' && pendingInviteCount > 0 ? (
              <span className="ml-auto min-w-[18px] px-1.5 py-px rounded-full bg-red-500/90 text-white font-mono text-[10px] font-bold text-center leading-none">
                {pendingInviteCount}
              </span>
            ) : undefined
          return <NavRow key={item.path} item={item} badge={badge} />
        })}

        {/* Settings (standalone) */}
        <div className="pt-5">
          <NavRow item={SETTINGS_ITEM} />
        </div>
      </nav>

      {/* ── Account block ──────────────────────────────────────────────── */}
      <div className="border-t border-border-base p-3 flex items-center gap-3">
        {meLoading || !initials ? (
          <div className="w-7 h-7 rounded-full bg-surface animate-pulse flex-shrink-0" />
        ) : (
          <Avatar initials={initials} gradient="coral-amber" size="sm" />
        )}
        <div className="flex-1 min-w-0">
          {meLoading || !displayName ? (
            <>
              <div className="h-3 w-24 rounded bg-surface animate-pulse mb-1" />
              <div className="h-2.5 w-32 rounded bg-surface animate-pulse" />
            </>
          ) : (
            <>
              <div className="text-[12.5px] text-text-base truncate">{displayName}</div>
              <div className="font-mono text-[10px] text-text-3 truncate">{email}</div>
            </>
          )}
        </div>
        <button
          onClick={logout}
          title="Sign out"
          className={cn(
            'flex-shrink-0 p-1 rounded-md',
            'text-text-3 hover:text-text-base hover:bg-surface',
            'border border-transparent hover:border-border-base',
            'transition-all duration-[120ms]',
          )}
        >
          <SignOutIcon />
        </button>
      </div>
    </div>
  )
}
