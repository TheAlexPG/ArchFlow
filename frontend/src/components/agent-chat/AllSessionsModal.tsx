import { useRef, useState } from 'react'
import { cn } from '../../utils/cn'
import {
  useAgentSessions,
  useDeleteAgentSession,
  type AgentSessionListItem,
} from './hooks/use-agent-sessions'

// ─── Types ───────────────────────────────────────────────────────────────────

interface Props {
  open: boolean
  onClose: () => void
  onSelectSession: (session: AgentSessionListItem) => void
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  })
}

// ─── DeleteConfirmDialog ─────────────────────────────────────────────────────

interface DeleteConfirmProps {
  sessionTitle: string | null
  onConfirm: () => void
  onCancel: () => void
}

function DeleteConfirmDialog({ sessionTitle, onConfirm, onCancel }: DeleteConfirmProps) {
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Delete session"
      data-testid="delete-confirm-dialog"
      className={cn(
        'absolute inset-0 z-10',
        'flex items-center justify-center',
        'bg-black/50 rounded-xl',
      )}
    >
      <div
        className={cn(
          'bg-panel border border-border-base rounded-lg shadow-window',
          'p-5 max-w-xs w-full mx-4',
        )}
      >
        <h3 className="text-[14px] font-medium text-text-base mb-2">
          Delete session?
        </h3>
        <p className="text-[12px] text-text-3 mb-5">
          "{sessionTitle ?? 'Untitled session'}" will be permanently deleted.
        </p>
        <div className="flex justify-end gap-2">
          <button
            data-testid="delete-cancel-btn"
            onClick={onCancel}
            className={cn(
              'px-3 py-1.5 rounded text-[12px]',
              'text-text-2 border border-border-base',
              'hover:bg-surface-hi transition-colors duration-100',
            )}
          >
            Cancel
          </button>
          <button
            data-testid="delete-confirm-btn"
            onClick={onConfirm}
            className={cn(
              'px-3 py-1.5 rounded text-[12px]',
              'bg-red-600 text-white',
              'hover:bg-red-700 transition-colors duration-100',
            )}
          >
            Delete
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── AllSessionsModal ─────────────────────────────────────────────────────────

const PAGE_SIZE = 20

export function AllSessionsModal({ open, onClose, onSelectSession }: Props) {
  const [search, setSearch] = useState('')
  const [filterAgentId, setFilterAgentId] = useState('')
  const [filterContextKind, setFilterContextKind] = useState('')
  const [page, setPage] = useState(0)
  const [pendingDelete, setPendingDelete] = useState<AgentSessionListItem | null>(null)
  const overlayRef = useRef<HTMLDivElement>(null)

  const { data: allSessions, isLoading } = useAgentSessions(
    filterAgentId || filterContextKind
      ? {
          agent_id: filterAgentId || undefined,
          context_kind: filterContextKind || undefined,
        }
      : undefined,
  )

  const deleteSession = useDeleteAgentSession()

  if (!open) return null

  // Client-side search filter
  const filtered = (allSessions ?? []).filter((s) => {
    if (!search) return true
    const needle = search.toLowerCase()
    return (s.title ?? '').toLowerCase().includes(needle)
  })

  // Derive unique agent_ids and context_kinds for filter dropdowns
  const agentIds = Array.from(new Set((allSessions ?? []).map((s) => s.agent_id)))
  const contextKinds = Array.from(new Set((allSessions ?? []).map((s) => s.context_kind)))

  // Paginate client-side
  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const paginated = filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)

  function handleOverlayClick(e: React.MouseEvent) {
    if (e.target === overlayRef.current) onClose()
  }

  function handleConfirmDelete() {
    if (!pendingDelete) return
    deleteSession.mutate(pendingDelete.id)
    setPendingDelete(null)
  }

  return (
    <div
      ref={overlayRef}
      data-testid="all-sessions-overlay"
      onClick={handleOverlayClick}
      className={cn(
        'fixed inset-0 z-[60]',
        'flex items-center justify-center',
        'bg-black/60',
      )}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="All sessions"
        data-testid="all-sessions-modal"
        className={cn(
          'relative',
          'w-full max-w-2xl mx-4',
          'bg-panel border border-border-base rounded-xl shadow-window',
          'flex flex-col',
          'max-h-[80vh]',
        )}
      >
        {/* Delete confirm overlay */}
        {pendingDelete && (
          <DeleteConfirmDialog
            sessionTitle={pendingDelete.title}
            onConfirm={handleConfirmDelete}
            onCancel={() => setPendingDelete(null)}
          />
        )}

        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-border-base">
          <h2 className="text-[14px] font-medium text-text-base">All sessions</h2>
          <button
            data-testid="all-sessions-close-btn"
            onClick={onClose}
            aria-label="Close"
            className={cn(
              'w-7 h-7 flex items-center justify-center rounded',
              'text-text-3 hover:text-text-base hover:bg-surface-hi',
              'transition-colors duration-100 text-[12px]',
            )}
          >
            ✕
          </button>
        </div>

        {/* Filters */}
        <div className="flex items-center gap-2 px-4 py-2 border-b border-border-base flex-wrap">
          <input
            data-testid="sessions-search-input"
            type="text"
            placeholder="Search by title…"
            value={search}
            onChange={(e) => { setSearch(e.target.value); setPage(0) }}
            className={cn(
              'flex-1 min-w-[160px] px-3 py-1',
              'bg-surface border border-border-base rounded text-[12px]',
              'text-text-1 placeholder:text-text-4',
              'focus:outline-none focus:ring-1 focus:ring-coral/40',
            )}
          />

          {agentIds.length > 1 && (
            <select
              data-testid="sessions-filter-agent"
              value={filterAgentId}
              onChange={(e) => { setFilterAgentId(e.target.value); setPage(0) }}
              className={cn(
                'px-2 py-1 bg-surface border border-border-base rounded',
                'text-[12px] text-text-2',
                'focus:outline-none focus:ring-1 focus:ring-coral/40',
              )}
            >
              <option value="">All agents</option>
              {agentIds.map((id) => (
                <option key={id} value={id}>{id}</option>
              ))}
            </select>
          )}

          {contextKinds.length > 1 && (
            <select
              data-testid="sessions-filter-context"
              value={filterContextKind}
              onChange={(e) => { setFilterContextKind(e.target.value); setPage(0) }}
              className={cn(
                'px-2 py-1 bg-surface border border-border-base rounded',
                'text-[12px] text-text-2',
                'focus:outline-none focus:ring-1 focus:ring-coral/40',
              )}
            >
              <option value="">All contexts</option>
              {contextKinds.map((k) => (
                <option key={k} value={k}>{k}</option>
              ))}
            </select>
          )}
        </div>

        {/* Session list */}
        <div className="flex-1 overflow-y-auto min-h-0">
          {isLoading ? (
            <p className="px-4 py-6 text-[12px] text-text-4 text-center">
              Loading…
            </p>
          ) : paginated.length === 0 ? (
            <p
              data-testid="sessions-empty-state"
              className="px-4 py-6 text-[12px] text-text-4 text-center"
            >
              {search ? 'No sessions match your search.' : 'No sessions yet.'}
            </p>
          ) : (
            <ul>
              {paginated.map((session) => (
                <li
                  key={session.id}
                  data-testid={`session-list-row-${session.id}`}
                  className={cn(
                    'flex items-center gap-2 px-4 py-2.5',
                    'border-b border-border-base last:border-b-0',
                    'hover:bg-surface-hi transition-colors duration-100',
                  )}
                >
                  {/* Clickable row content */}
                  <button
                    className="flex-1 text-left min-w-0"
                    onClick={() => onSelectSession(session)}
                  >
                    <span className="block text-[12px] text-text-1 truncate">
                      {session.title ?? 'Untitled session'}
                    </span>
                    <span className="block text-[10px] text-text-4 font-mono mt-0.5">
                      {session.agent_id} · {session.context_kind} · {formatDate(session.last_message_at)}
                    </span>
                  </button>

                  {/* Delete button */}
                  <button
                    data-testid={`session-delete-btn-${session.id}`}
                    onClick={() => setPendingDelete(session)}
                    aria-label={`Delete session: ${session.title ?? 'Untitled session'}`}
                    className={cn(
                      'flex-shrink-0 w-6 h-6 flex items-center justify-center rounded',
                      'text-text-4 hover:text-red-500 hover:bg-red-500/10',
                      'transition-colors duration-100 text-[11px]',
                    )}
                  >
                    ✕
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="flex items-center justify-between px-4 py-2 border-t border-border-base">
            <button
              data-testid="sessions-prev-btn"
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0}
              className={cn(
                'px-3 py-1 rounded text-[12px]',
                'text-text-2 border border-border-base',
                'hover:bg-surface-hi disabled:opacity-30 disabled:cursor-not-allowed',
                'transition-colors duration-100',
              )}
            >
              ← Prev
            </button>
            <span className="text-[11px] text-text-4">
              {page + 1} / {totalPages}
            </span>
            <button
              data-testid="sessions-next-btn"
              onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
              disabled={page >= totalPages - 1}
              className={cn(
                'px-3 py-1 rounded text-[12px]',
                'text-text-2 border border-border-base',
                'hover:bg-surface-hi disabled:opacity-30 disabled:cursor-not-allowed',
                'transition-colors duration-100',
              )}
            >
              Next →
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
