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
      <div className="px-4 py-2 text-xs text-neutral-600 italic">Loading…</div>
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
    } catch (e) {
      alert(
        (e as { response?: { data?: { detail?: string } } }).response?.data
          ?.detail ?? 'Delete failed',
      )
    }
  }

  return (
    <div className="px-4 py-2">
      <label className="block text-[10px] uppercase tracking-wide text-neutral-600 mb-1">
        Workspace
      </label>

      {editing ? (
        <div className="flex gap-1">
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
            className="flex-1 bg-neutral-900 border border-neutral-700 text-neutral-100 text-xs rounded px-2 py-1 outline-none focus:border-neutral-500"
          />
          <button
            onClick={() => void saveRename()}
            disabled={rename.isPending}
            className="text-xs text-blue-400 hover:text-blue-300 disabled:opacity-40 px-2"
            title="Save"
          >
            ✓
          </button>
        </div>
      ) : (
        <select
          value={currentWorkspaceId ?? ''}
          onChange={(e) => setCurrentWorkspaceId(e.target.value)}
          className="w-full bg-neutral-900 border border-neutral-800 text-neutral-200 text-xs rounded px-2 py-1 outline-none focus:border-neutral-600"
        >
          {workspaces.map((w) => (
            <option key={w.id} value={w.id}>
              {w.name}
            </option>
          ))}
        </select>
      )}

      {error && <div className="text-[10px] text-red-400 mt-1">{error}</div>}

      <div className="flex gap-3 mt-1.5 text-[10px]">
        <button
          onClick={createNew}
          className="text-neutral-500 hover:text-neutral-300"
        >
          + New
        </button>
        {canMutate && !editing && (
          <button
            onClick={() => setEditing(true)}
            className="text-neutral-500 hover:text-neutral-300"
          >
            Rename
          </button>
        )}
        {canDelete && !editing && (
          <button
            onClick={deleteCurrent}
            className="ml-auto text-neutral-500 hover:text-red-400"
          >
            Delete
          </button>
        )}
      </div>
    </div>
  )
}
