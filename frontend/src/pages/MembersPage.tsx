import { useState } from 'react'
import { AppSidebar } from '../components/nav/AppSidebar'
import { PageToolbar } from '../components/nav/PageToolbar'
import {
  useInviteMember,
  useMe,
  useRemoveMember,
  useRevokeInvite,
  useTeams,
  useUpdateMemberRole,
  useWorkspaceInvites,
  useWorkspaceMembers,
} from '../hooks/use-api'
import { useWorkspaceStore } from '../stores/workspace-store'
import type { AgentAccess, WorkspaceRole } from '../types/model'

const ROLES: WorkspaceRole[] = ['owner', 'admin', 'editor', 'reviewer', 'viewer']

const AGENT_ACCESS_OPTIONS: { value: AgentAccess; label: string; hint: string }[] = [
  {
    value: 'read_only',
    label: 'Read-only (recommended)',
    hint: 'User can chat with the agent in read-only mode.',
  },
  {
    value: 'full',
    label: 'Full',
    hint: 'User can chat and let the agent modify diagrams (subject to drafts policy).',
  },
  {
    value: 'none',
    label: 'Disabled',
    hint: "User can't access the agent at all.",
  },
]

const AGENT_ACCESS_BADGE: Record<AgentAccess, string> = {
  full: 'Full',
  read_only: 'Read-only',
  none: 'Disabled',
}

const CAN_EDIT_ROLES: WorkspaceRole[] = ['owner', 'admin']

export function MembersPage() {
  const wsId = useWorkspaceStore((s) => s.currentWorkspaceId)
  const { data: members = [], isLoading } = useWorkspaceMembers(wsId)
  const invite = useInviteMember(wsId)
  const updateRole = useUpdateMemberRole(wsId)
  const remove = useRemoveMember(wsId)
  const { data: pendingInvites = [] } = useWorkspaceInvites(wsId)
  const revokeInvite = useRevokeInvite(wsId)
  const { data: me } = useMe()

  const { data: teams = [] } = useTeams(wsId)

  const [email, setEmail] = useState('')
  const [role, setRole] = useState<WorkspaceRole>('editor')
  const [agentAccess, setAgentAccess] = useState<AgentAccess>('read_only')
  const [selectedTeams, setSelectedTeams] = useState<string[]>([])
  const [inviteLink, setInviteLink] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)

  const currentMember = me ? members.find((m) => m.user_id === me.id) : undefined
  const currentRole = currentMember?.role ?? 'viewer'
  const canEditAgentAccess = CAN_EDIT_ROLES.includes(currentRole)

  const agentAccessHint =
    AGENT_ACCESS_OPTIONS.find((o) => o.value === agentAccess)?.hint ?? ''

  const submit = async () => {
    setErr(null)
    setInviteLink(null)
    try {
      const result = await invite.mutateAsync({
        email: email.trim(),
        role,
        agent_access: agentAccess,
        team_ids: selectedTeams,
      })
      setEmail('')
      setSelectedTeams([])
      setAgentAccess('read_only')
      setInviteLink(
        `${window.location.origin}/accept-invite?token=${result.invite.token}`,
      )
    } catch (e) {
      const msg =
        (e as { response?: { data?: { detail?: string } } }).response?.data
          ?.detail ?? 'Could not invite'
      setErr(msg)
    }
  }

  return (
    <div className="flex h-screen bg-bg text-text-base">
      <AppSidebar />
      <div className="flex-1 flex flex-col overflow-hidden">
        <PageToolbar breadcrumb={['alex / personal', 'Members']} />
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

          {/* Agent access field */}
          <div className="mt-3">
            <label className="block text-xs text-neutral-400 mb-1">
              Agent access
              <span className="ml-1 text-neutral-600">
                — What level of agent access this user gets when joining.
              </span>
            </label>
            <select
              data-testid="invite-agent-access"
              value={agentAccess}
              onChange={(e) => setAgentAccess(e.target.value as AgentAccess)}
              className="bg-neutral-800 border border-neutral-700 rounded px-2 py-1.5 text-sm"
            >
              {AGENT_ACCESS_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
            {agentAccessHint && (
              <p className="text-xs text-neutral-500 mt-1">{agentAccessHint}</p>
            )}
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
              Invite sent. Share this link with anyone without an account yet:
              <br />
              <code>{inviteLink}</code>
            </div>
          )}
        </section>

        {pendingInvites.length > 0 && (
          <section className="max-w-3xl mb-8 bg-neutral-900 border border-neutral-800 rounded-lg overflow-hidden">
            <div className="px-4 py-2 text-xs font-semibold border-b border-neutral-800 text-neutral-400">
              Pending invites ({pendingInvites.length})
            </div>
            <table className="w-full text-sm">
              <tbody>
                {pendingInvites.map((inv) => (
                  <tr
                    key={inv.id}
                    className="border-b border-neutral-800 last:border-0"
                  >
                    <td className="px-4 py-2 text-neutral-300">{inv.email}</td>
                    <td className="px-4 py-2 text-xs text-neutral-500">
                      {inv.role}
                    </td>
                    <td className="px-4 py-2 text-right">
                      <button
                        onClick={() => {
                          if (confirm(`Revoke invite for ${inv.email}?`))
                            revokeInvite.mutate(inv.id)
                        }}
                        className="text-xs text-red-400 hover:text-red-300"
                      >
                        Revoke
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        )}

        <div className="bg-neutral-900 border border-neutral-800 rounded-lg overflow-hidden max-w-3xl">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-neutral-500 border-b border-neutral-800">
                <th className="text-left px-4 py-2 font-medium">Name</th>
                <th className="text-left px-4 py-2 font-medium">Email</th>
                <th className="text-left px-4 py-2 font-medium">Role</th>
                <th className="text-left px-4 py-2 font-medium">Agent access</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {isLoading && (
                <tr>
                  <td colSpan={5} className="px-4 py-4 text-xs text-neutral-500 italic">
                    Loading…
                  </td>
                </tr>
              )}
              {members.map((m) => {
                const effectiveAccess: AgentAccess = m.agent_access ?? 'full'
                // Owners and admins can edit any row, including their own.
                // The backend's last-owner guard prevents lockouts on the
                // role column; agent_access has no equivalent risk (an owner
                // who locks themselves out of agent_access can flip it back
                // any time).
                const canEdit = canEditAgentAccess
                return (
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
                    <td className="px-4 py-2">
                      {canEdit ? (
                        <select
                          data-testid={`agent-access-select-${m.user_id}`}
                          value={effectiveAccess}
                          onChange={(e) =>
                            updateRole.mutate({
                              userId: m.user_id,
                              agent_access: e.target.value as AgentAccess,
                            })
                          }
                          className="bg-neutral-800 border border-neutral-700 rounded px-2 py-0.5 text-xs"
                        >
                          {AGENT_ACCESS_OPTIONS.map((o) => (
                            <option key={o.value} value={o.value}>
                              {o.label}
                            </option>
                          ))}
                        </select>
                      ) : (
                        <span
                          data-testid={`agent-access-badge-${m.user_id}`}
                          className={`text-xs px-1.5 py-0.5 rounded border ${
                            effectiveAccess === 'none'
                              ? 'bg-neutral-800 border-neutral-700 text-neutral-500'
                              : effectiveAccess === 'full'
                                ? 'bg-blue-900/30 border-blue-700/50 text-blue-300'
                                : 'bg-neutral-800 border-neutral-700 text-neutral-400'
                          }`}
                        >
                          {AGENT_ACCESS_BADGE[effectiveAccess]}
                        </span>
                      )}
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
                )
              })}
            </tbody>
          </table>
        </div>
        </div>
      </div>
    </div>
  )
}
