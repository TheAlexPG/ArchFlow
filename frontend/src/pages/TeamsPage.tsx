import { useState } from 'react'
import { AppSidebar } from '../components/nav/AppSidebar'
import {
  useAddTeamMember,
  useCreateTeam,
  useDeleteTeam,
  useRemoveTeamMember,
  useTeamMembers,
  useTeams,
  useWorkspaceMembers,
} from '../hooks/use-api'
import { useWorkspaceStore } from '../stores/workspace-store'

export function TeamsPage() {
  const wsId = useWorkspaceStore((s) => s.currentWorkspaceId)
  const { data: teams = [], isLoading } = useTeams(wsId)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [createOpen, setCreateOpen] = useState(false)

  return (
    <div className="flex h-screen bg-neutral-950 text-neutral-200">
      <AppSidebar />
      <div className="flex-1 overflow-y-auto p-8">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-xl font-semibold">Teams</h1>
          <button
            onClick={() => setCreateOpen(true)}
            className="bg-blue-600 hover:bg-blue-500 text-white text-xs font-medium rounded px-3 py-1.5"
          >
            + New team
          </button>
        </div>

        <div className="grid grid-cols-[minmax(240px,320px)_1fr] gap-6 max-w-5xl">
          <div className="bg-neutral-900 border border-neutral-800 rounded-lg overflow-hidden">
            {isLoading && (
              <div className="px-4 py-3 text-xs text-neutral-500 italic">Loading…</div>
            )}
            {!isLoading && teams.length === 0 && (
              <div className="px-4 py-3 text-xs text-neutral-500 italic">
                No teams yet.
              </div>
            )}
            {teams.map((t) => (
              <button
                key={t.id}
                onClick={() => setSelectedId(t.id)}
                className={`block w-full text-left px-4 py-2 border-b border-neutral-800 last:border-0 text-sm ${
                  selectedId === t.id
                    ? 'bg-neutral-800 text-neutral-100'
                    : 'hover:bg-neutral-800/50 text-neutral-300'
                }`}
              >
                <div>{t.name}</div>
                {t.description && (
                  <div className="text-xs text-neutral-500 mt-0.5 truncate">
                    {t.description}
                  </div>
                )}
              </button>
            ))}
          </div>

          {selectedId ? (
            <TeamDetail teamId={selectedId} workspaceId={wsId} />
          ) : (
            <div className="text-sm text-neutral-500 italic">
              Pick a team on the left to see its members.
            </div>
          )}
        </div>
      </div>

      {createOpen && wsId && (
        <CreateTeamModal workspaceId={wsId} onClose={() => setCreateOpen(false)} />
      )}
    </div>
  )
}

function TeamDetail({
  workspaceId,
  teamId,
}: {
  workspaceId: string | null
  teamId: string
}) {
  const { data: members = [] } = useTeamMembers(workspaceId, teamId)
  const { data: wsMembers = [] } = useWorkspaceMembers(workspaceId)
  const add = useAddTeamMember(workspaceId, teamId)
  const remove = useRemoveTeamMember(workspaceId, teamId)
  const del = useDeleteTeam(workspaceId)

  const memberIds = new Set(members.map((m) => m.user_id))
  const candidates = wsMembers.filter((m) => !memberIds.has(m.user_id))

  return (
    <div className="bg-neutral-900 border border-neutral-800 rounded-lg p-4">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold">Members ({members.length})</h2>
        <button
          onClick={() => {
            if (confirm('Delete this team? Grants will also be removed.'))
              del.mutate(teamId)
          }}
          className="text-xs text-red-400 hover:text-red-300"
        >
          Delete team
        </button>
      </div>

      {candidates.length > 0 && (
        <div className="mb-4">
          <label className="block text-xs text-neutral-400 mb-1">Add member</label>
          <select
            onChange={(e) => {
              const id = e.target.value
              if (id) {
                add.mutate(id)
                e.currentTarget.value = ''
              }
            }}
            className="w-full bg-neutral-800 border border-neutral-700 rounded px-2 py-1.5 text-sm"
          >
            <option value="">Select a workspace member…</option>
            {candidates.map((m) => (
              <option key={m.user_id} value={m.user_id}>
                {m.name} — {m.email}
              </option>
            ))}
          </select>
        </div>
      )}

      {members.length === 0 ? (
        <div className="text-xs text-neutral-500 italic">No members yet.</div>
      ) : (
        <table className="w-full text-sm">
          <tbody>
            {members.map((m) => (
              <tr key={m.user_id} className="border-b border-neutral-800 last:border-0">
                <td className="py-1.5">{m.name}</td>
                <td className="py-1.5 text-xs text-neutral-400">{m.email}</td>
                <td className="py-1.5 text-right">
                  <button
                    onClick={() => remove.mutate(m.user_id)}
                    className="text-xs text-red-400 hover:text-red-300"
                  >
                    Remove
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

function CreateTeamModal({
  workspaceId,
  onClose,
}: {
  workspaceId: string
  onClose: () => void
}) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const create = useCreateTeam(workspaceId)

  const submit = async () => {
    if (!name.trim()) return
    await create.mutateAsync({ name: name.trim(), description: description.trim() || undefined })
    onClose()
  }

  return (
    <div
      className="fixed inset-0 bg-black/60 flex items-center justify-center z-50"
      onClick={onClose}
    >
      <div
        className="bg-neutral-900 border border-neutral-800 rounded-lg w-[460px] p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-sm font-semibold mb-4">Create team</h3>
        <label className="block text-xs text-neutral-400 mb-1">Name</label>
        <input
          autoFocus
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Frontend, Platform, SRE…"
          className="w-full bg-neutral-800 border border-neutral-700 rounded px-2 py-1.5 text-sm mb-4 outline-none focus:border-neutral-500"
        />
        <label className="block text-xs text-neutral-400 mb-1">Description (optional)</label>
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={2}
          className="w-full bg-neutral-800 border border-neutral-700 rounded px-2 py-1.5 text-sm mb-4 outline-none focus:border-neutral-500"
        />
        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="text-xs text-neutral-400 px-3 py-1.5">
            Cancel
          </button>
          <button
            onClick={submit}
            disabled={!name.trim() || create.isPending}
            className="bg-blue-600 hover:bg-blue-500 text-white text-xs font-medium rounded px-3 py-1.5 disabled:opacity-40"
          >
            {create.isPending ? 'Creating…' : 'Create'}
          </button>
        </div>
      </div>
    </div>
  )
}
