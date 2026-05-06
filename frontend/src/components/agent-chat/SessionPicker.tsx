import { useEffect, useRef, useState } from 'react'
import { cn } from '../../utils/cn'
import { useAgentStream } from './hooks/use-agent-stream'
import { useAgentSessions, type AgentSessionListItem } from './hooks/use-agent-sessions'
import { useAgentChatStore } from './store'
import { AllSessionsModal } from './AllSessionsModal'

// ─── Helpers ────────────────────────────────────────────────────────────────

function formatRelative(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60_000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  return `${days}d ago`
}

// ─── SessionRow ──────────────────────────────────────────────────────────────

interface SessionRowProps {
  session: AgentSessionListItem
  isActive: boolean
  onClick: () => void
}

function SessionRow({ session, isActive, onClick }: SessionRowProps) {
  return (
    <button
      data-testid={`session-row-${session.id}`}
      onClick={onClick}
      className={cn(
        'w-full text-left px-3 py-2 flex flex-col gap-0.5',
        'hover:bg-surface-hi transition-colors duration-100',
        isActive && 'bg-coral/10',
      )}
    >
      <span className="text-[12px] text-text-1 truncate">
        {session.title ?? 'Untitled session'}
      </span>
      <span className="text-[10px] text-text-4 font-mono">
        {session.context_kind} · {formatRelative(session.last_message_at)}
      </span>
    </button>
  )
}

// ─── SessionPicker ───────────────────────────────────────────────────────────

export function SessionPicker() {
  const [open, setOpen] = useState(false)
  const [allSessionsOpen, setAllSessionsOpen] = useState(false)
  const dropdownRef = useRef<HTMLDivElement>(null)

  const { data: sessions } = useAgentSessions()
  const stream = useAgentStream()
  const activeSessionId = useAgentChatStore((s) => s.activeSessionId)
  const setActive = useAgentChatStore((s) => s.setActiveSessionId)

  // Top-5 most recent (backend returns newest-first; slice to 5)
  const recentSessions = (sessions ?? []).slice(0, 5)

  // Close dropdown when clicking outside
  useEffect(() => {
    if (!open) return
    function handleClickOutside(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [open])

  function handleSelectSession(session: AgentSessionListItem) {
    stream.reset()
    setActive(session.id)
    setOpen(false)
  }

  function handleNewSession() {
    stream.reset()
    setActive(null)
    setOpen(false)
  }

  const activeSession = sessions?.find((s) => s.id === activeSessionId)

  return (
    <>
      <div className="relative" ref={dropdownRef}>
        <button
          data-testid="session-picker-trigger"
          onClick={() => setOpen((v) => !v)}
          className={cn(
            'flex items-center gap-1 px-1.5 py-0.5 rounded',
            'text-[11px] text-text-3 hover:text-text-2',
            'border border-transparent hover:border-border-base',
            'transition-colors duration-100 max-w-[140px]',
          )}
          title={activeSession?.title ?? 'New session'}
        >
          <span className="truncate">
            {activeSession?.title ?? 'New session'}
          </span>
          <span aria-hidden="true" className="flex-shrink-0">▾</span>
        </button>

        {open && (
          <div
            data-testid="session-picker-dropdown"
            className={cn(
              'absolute top-full left-0 mt-1 z-50',
              'w-64 rounded-md overflow-hidden',
              'bg-panel border border-border-base shadow-window',
            )}
          >
            {/* New session */}
            <button
              data-testid="session-new-btn"
              onClick={handleNewSession}
              className={cn(
                'w-full text-left px-3 py-2',
                'text-[12px] text-coral font-medium',
                'hover:bg-surface-hi transition-colors duration-100',
                'border-b border-border-base',
              )}
            >
              + New session
            </button>

            {/* Recent sessions */}
            {recentSessions.length === 0 ? (
              <p
                data-testid="session-empty-state"
                className="px-3 py-3 text-[11px] text-text-4 text-center"
              >
                No sessions yet
              </p>
            ) : (
              recentSessions.map((s) => (
                <SessionRow
                  key={s.id}
                  session={s}
                  isActive={s.id === activeSessionId}
                  onClick={() => handleSelectSession(s)}
                />
              ))
            )}

            {/* All sessions link */}
            {(sessions?.length ?? 0) > 0 && (
              <button
                data-testid="session-all-btn"
                onClick={() => {
                  setOpen(false)
                  setAllSessionsOpen(true)
                }}
                className={cn(
                  'w-full text-left px-3 py-2',
                  'text-[11px] text-text-3 hover:text-text-2',
                  'hover:bg-surface-hi transition-colors duration-100',
                  'border-t border-border-base',
                )}
              >
                All sessions →
              </button>
            )}
          </div>
        )}
      </div>

      <AllSessionsModal
        open={allSessionsOpen}
        onClose={() => setAllSessionsOpen(false)}
        onSelectSession={(session) => {
          stream.reset()
          setActive(session.id)
          setAllSessionsOpen(false)
        }}
      />
    </>
  )
}
