import { useEffect, useState } from 'react'
import {
  useCreateWorkspace,
  useDeleteWorkspace,
  useRenameWorkspace,
  useWorkspaces,
} from '../../hooks/use-api'
import { useWorkspaceStore } from '../../stores/workspace-store'

/**
 * Dropdown that shows the caller's workspaces + a gear icon for quick
 * rename/delete and a "+ New workspace" action.
 *
 * When the user has just signed in and no workspace is selected yet, this
 * component auto-picks the first one so the X-Workspace-ID header starts
 * attaching on subsequent requests — otherwise writes wouldn't be tagged
 * with any workspace.
 */
export function WorkspaceSwitcher() {
  const { data: workspaces = [], isLoading } = useWorkspaces()
  const { currentWorkspaceId, setCurrentWorkspaceId } = useWorkspaceStore()
  const create = useCreateWorkspace()
  const rename = useRenameWorkspace()
  const remove = useDeleteWorkspace()

  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState(false)
  const [newName, setNewName] = useState('')
  const [error, setError] = useState<string | null>(null)

  const current = workspaces.find((w) => w.id === currentWorkspaceId) ?? null
  const canMutate =
    current?.role === 'owner' || current?.role === 'admin'
  const canDelete = current?.role === 'owner'

  useEffect(() => {
    if (!currentWorkspaceId && workspaces.length > 0) {
      setCurrentWorkspaceId(workspaces[0].id)
    }
    if (
      currentWorkspaceId &&
      workspaces.length > 0 &&
      !workspaces.some((w) => w.id === currentWorkspaceId)
    ) {
      setCurrentWorkspaceId(workspaces[0].id)
    }
  }, [currentWorkspaceId, workspaces, setCurrentWorkspaceId])

  useEffect(() => {
    if (current) setNewName(current.name)
    setEditing(false)
    setError(null)
  }, [current?.id])

  if (isLoading || workspaces.length === 0) {
    return (
      <div className="px-1 py-1 text-[11px] text-text-4 italic">Loading…</div>
    )
  }

  const saveRename = async () => {
    if (!current || !newName.trim() || newName.trim() === current.name) {
      setEditing(false)
      return
    }
    setError(null)
    try {
      await rename.mutateAsync({ id: current.id, name: newName.trim() })
      setEditing(false)
    } catch (e) {
      setError(
        (e as { response?: { data?: { detail?: string } } }).response?.data
          ?.detail ?? 'Rename failed',
      )
    }
  }

  const createNew = async () => {
    const name = prompt('Workspace name?')
    if (!name || !name.trim()) return
    try {
      const ws = await create.mutateAsync(name.trim())
      setCurrentWorkspaceId(ws.id)
      setOpen(false)
    } catch (e) {
      alert(
        (e as { response?: { data?: { detail?: string } } }).response?.data
          ?.detail ?? 'Create failed',
      )
    }
  }

  const deleteCurrent = async () => {
    if (!current) return
    if (
      !confirm(
        `Delete workspace "${current.name}"? This can't be undone. The workspace must be empty (no diagrams).`,
      )
    )
      return
    try {
      await remove.mutateAsync(current.id)
      setCurrentWorkspaceId(null)
      setOpen(false)
    } catch (e) {
      alert(
        (e as { response?: { data?: { detail?: string } } }).response?.data
          ?.detail ?? 'Delete failed',
      )
    }
  }

  // Initials from workspace name
  const wsInitials = current?.name
    ? current.name
        .split(/\s+/)
        .slice(0, 2)
        .map((w) => w[0])
        .join('')
        .toUpperCase()
    : '?'

  return (
    <div className="relative">
      {/* ── Trigger button ── */}
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-3 py-2 rounded-md border border-border-base bg-surface hover:bg-surface-hi transition-all duration-[120ms]"
      >
        <div className="flex items-center gap-2 min-w-0">
          <div className="w-5 h-5 flex-shrink-0 rounded bg-gradient-to-br from-coral to-accent-purple flex items-center justify-center text-[10px] font-bold text-bg select-none">
            {wsInitials.slice(0, 1)}
          </div>
          <span className="text-[12.5px] text-text-base truncate">
            {current?.name ?? 'No workspace'}
          </span>
        </div>
        <svg
          width="12"
          height="12"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          className="flex-shrink-0 text-text-3 ml-1"
        >
          <path d="m7 15 5 5 5-5M7 9l5-5 5 5"/>
        </svg>
      </button>

      {/* ── Dropdown ── */}
      {open && (
        <div className="absolute left-0 right-0 top-[calc(100%+4px)] z-50 bg-panel border border-border-base rounded-md shadow-popup overflow-hidden">
          {/* Workspace list */}
          <div className="py-1 max-h-[200px] overflow-y-auto">
            {workspaces.map((w) => (
              <button
                key={w.id}
                onClick={() => {
                  setCurrentWorkspaceId(w.id)
                  setOpen(false)
                }}
                className={[
                  'w-full flex items-center gap-2 px-3 py-1.5 text-[12.5px] text-left',
                  'hover:bg-surface transition-colors duration-[120ms]',
                  w.id === currentWorkspaceId ? 'text-text-base' : 'text-text-2',
                ].join(' ')}
              >
                <span
                  className={[
                    'w-1.5 h-1.5 rounded-full flex-shrink-0',
                    w.id === currentWorkspaceId ? 'bg-coral' : 'bg-transparent',
                  ].join(' ')}
                />
                <span className="flex-1 truncate">{w.name}</span>
                {w.role && (
                  <span className="font-mono text-[10px] text-text-4 flex-shrink-0">
                    {w.role}
                  </span>
                )}
              </button>
            ))}
          </div>

          {/* Actions */}
          <div className="border-t border-border-base px-3 py-2 flex gap-3">
            <button
              onClick={() => void createNew()}
              className="text-[11px] text-text-3 hover:text-text-base transition-colors"
            >
              + New
            </button>
            {canMutate && !editing && (
              <button
                onClick={() => setEditing(true)}
                className="text-[11px] text-text-3 hover:text-text-base transition-colors"
              >
                Rename
              </button>
            )}
            {canDelete && !editing && (
              <button
                onClick={() => void deleteCurrent()}
                className="ml-auto text-[11px] text-text-3 hover:text-red-400 transition-colors"
              >
                Delete
              </button>
            )}
          </div>

          {/* Inline rename */}
          {editing && (
            <div className="border-t border-border-base px-3 py-2 flex gap-1.5">
              <input
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                autoFocus
                onKeyDown={(e) => {
                  if (e.key === 'Enter') void saveRename()
                  if (e.key === 'Escape') {
                    setEditing(false)
                    setNewName(current?.name ?? '')
                    setError(null)
                  }
                }}
                className="flex-1 bg-surface border border-border-base text-text-base text-[12px] rounded px-2 py-1 outline-none focus:border-border-hi"
              />
              <button
                onClick={() => void saveRename()}
                disabled={rename.isPending}
                className="text-[12px] text-coral hover:text-coral/80 disabled:opacity-40 px-1.5"
              >
                ✓
              </button>
            </div>
          )}
          {error && (
            <div className="px-3 pb-2 text-[10px] text-red-400">{error}</div>
          )}
        </div>
      )}
    </div>
  )
}
