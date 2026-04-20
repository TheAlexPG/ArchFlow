import { useEffect } from 'react'
import { useWorkspaces } from '../../hooks/use-api'
import { useWorkspaceStore } from '../../stores/workspace-store'

/**
 * Dropdown that shows the caller's workspaces and lets them switch.
 *
 * When the user has just signed in and no workspace is selected yet, this
 * component auto-picks the first one so the X-Workspace-ID header starts
 * attaching on subsequent requests — otherwise writes wouldn't be tagged
 * with any workspace.
 */
export function WorkspaceSwitcher() {
  const { data: workspaces = [], isLoading } = useWorkspaces()
  const { currentWorkspaceId, setCurrentWorkspaceId } = useWorkspaceStore()

  useEffect(() => {
    if (!currentWorkspaceId && workspaces.length > 0) {
      setCurrentWorkspaceId(workspaces[0].id)
    }
    if (
      currentWorkspaceId &&
      workspaces.length > 0 &&
      !workspaces.some((w) => w.id === currentWorkspaceId)
    ) {
      // Stale selection (user lost access to that workspace) — pick first
      setCurrentWorkspaceId(workspaces[0].id)
    }
  }, [currentWorkspaceId, workspaces, setCurrentWorkspaceId])

  if (isLoading || workspaces.length === 0) {
    return (
      <div className="px-4 py-2 text-xs text-neutral-600 italic">Loading…</div>
    )
  }

  return (
    <div className="px-4 py-2">
      <label className="block text-[10px] uppercase tracking-wide text-neutral-600 mb-1">
        Workspace
      </label>
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
    </div>
  )
}
