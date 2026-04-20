import { useState } from 'react'
import { AppSidebar } from '../components/nav/AppSidebar'
import {
  useInviteMember,
  useRemoveMember,
  useTeams,
  useUpdateMemberRole,
  useWorkspaceMembers,
} from '../hooks/use-api'
import { useWorkspaceStore } from '../stores/workspace-store'
import type { WorkspaceRole } from '../types/model'

const ROLES: WorkspaceRole[] = ['owner', 'admin', 'editor', 'reviewer', 'viewer']

export function MembersPage() {
  const wsId = useWorkspaceStore((s) => s.currentWorkspaceId)
  const { data: members = [], isLoading } = useWorkspaceMembers(wsId)
  const invite = useInviteMember(wsId)
  const updateRole = useUpdateMemberRole(wsId)
  const remove = useRemoveMember(wsId)

  const { data: teams = [] } = useTeams(wsId)

  const [email, setEmail] = useState('')
  const [role, setRole] = useState<WorkspaceRole>('editor')
  const [selectedTeams, setSelectedTeams] = useState<string[]>([])
  const [inviteLink, setInviteLink] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)

  const submit = async () => {
    setErr(null)
    setInviteLink(null)
    try {
      const result = await invite.mutateAsync({
        email: email.trim(),
        role,
        team_ids: selectedTeams,
      })
      setEmail('')
      setSelectedTeams([])
      if (result.type === 'invite_created') {
        setInviteLink(
          `${window.location.origin}/accept-invite?token=${result.invite.token}`,
        )
      }
    } catch (e) {
      const msg =
        (e as { response?: { data?: { detail?: string } } }).response?.data
          ?.detail ?? 'Could not invite'
      setErr(msg)
    }
  }

  return (
    <div className="flex h-screen bg-neutral-950 text-neutral-200">
      <AppSidebar />
      <div className="flex-1 overflow-y-auto p-8">
        <h1 className="text-xl font-semibold mb-6">Workspace members</h1>

        <section className="max-w-3xl mb-8 bg-neutral-900 border border-neutral-800 rounded-lg p-4">
          <h2 className="text-sm font-semibold mb-3">Invite someone</h2>
          <div className="flex gap-2">
            <input
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="teammate@company.com"
              className="flex-1 bg-neutral-800 border border-neutral-700 rounded px-2 py-1.5 text-sm outline-none focus:border-neutral-500"
            />
            <select
              value={role}
              onChange={(e) => setRole(e.target.value as WorkspaceRole)}
              className="bg-neutral-800 border border-neutral-700 rounded px-2 py-1.5 text-sm"
            >
              {ROLES.filter((r) => r !== 'owner').map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
            <button
              onClick={submit}
              disabled={!email.trim() || invite.isPending}
              className="bg-blue-600 hover:bg-blue-500 text-white text-xs font-medium rounded px-4 disabled:opacity-40"
            >
              {invite.isPending ? 'Sending…' : 'Invite'}
            </button>
          </div>

          {teams.length > 0 && (
            <div className="mt-3">
              <label className="block text-xs text-neutral-400 mb-1">
                Add to teams ({selectedTeams.length} selected) — they'll see
                only what these teams can access
              </label>
              <div className="flex flex-wrap gap-1.5">
                {teams.map((t) => {
                  const on = selectedTeams.includes(t.id)
                  return (
                    <button
                      type="button"
                      key={t.id}
                      onClick={() =>
                        setSelectedTeams(
                          on
                            ? selectedTeams.filter((x) => x !== t.id)
                            : [...selectedTeams, t.id],
                        )
                      }
                      className={`text-xs px-2 py-1 rounded border ${
                        on
                          ? 'bg-blue-600/20 border-blue-500 text-blue-300'
                          : 'bg-neutral-800 border-neutral-700 text-neutral-400 hover:border-neutral-500'
                      }`}
                    >
                      {on ? '✓ ' : '+ '}
                      {t.name}
                    </button>
                  )
                })}
              </div>
            </div>
          )}

          {err && <div className="text-xs text-red-400 mt-2">{err}</div>}
          {inviteLink && (
            <div className="text-xs text-amber-300 mt-2 break-all">
              Invite link (no account yet — share with them):
              <br />
              <code>{inviteLink}</code>
            </div>
          )}
        </section>

        <div className="bg-neutral-900 border border-neutral-800 rounded-lg overflow-hidden max-w-3xl">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-neutral-500 border-b border-neutral-800">
                <th className="text-left px-4 py-2 font-medium">Name</th>
                <th className="text-left px-4 py-2 font-medium">Email</th>
                <th className="text-left px-4 py-2 font-medium">Role</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {isLoading && (
                <tr>
                  <td colSpan={4} className="px-4 py-4 text-xs text-neutral-500 italic">
                    Loading…
                  </td>
                </tr>
              )}
              {members.map((m) => (
                <tr key={m.user_id} className="border-b border-neutral-800 last:border-0">
                  <td className="px-4 py-2">{m.name}</td>
                  <td className="px-4 py-2 text-neutral-400 text-xs">{m.email}</td>
                  <td className="px-4 py-2">
                    <select
                      value={m.role}
                      onChange={(e) =>
                        updateRole.mutate({
                          userId: m.user_id,
                          role: e.target.value as WorkspaceRole,
                        })
                      }
                      className="bg-neutral-800 border border-neutral-700 rounded px-2 py-0.5 text-xs"
                    >
                      {ROLES.map((r) => (
                        <option key={r} value={r}>
                          {r}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="px-4 py-2 text-right">
                    <button
                      onClick={() => {
                        if (confirm(`Remove ${m.name}?`)) remove.mutate(m.user_id)
                      }}
                      className="text-xs text-red-400 hover:text-red-300"
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
