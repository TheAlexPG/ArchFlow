import {
  useDiagramGrants,
  useGrantTeamAccess,
  useGrantUserAccess,
  useRevokeTeamAccess,
  useRevokeUserAccess,
  useTeams,
  useWorkspaceMembers,
} from '../../hooks/use-api'
import { useWorkspaceStore } from '../../stores/workspace-store'
import type { DiagramAccessLevel } from '../../types/model'

const LEVELS: DiagramAccessLevel[] = ['read', 'write', 'admin']

/**
 * Admin-facing modal. Two sections:
 *   - Teams: multi-select, each team picks its own access level.
 *   - Users: direct grants for individuals (override or supplement team access).
 *
 * Any grant (team OR user) flips the diagram to restricted. Empty = visible
 * to every workspace member.
 */
export function DiagramAccessModal({
  diagramId,
  onClose,
}: {
  diagramId: string
  onClose: () => void
}) {
  const wsId = useWorkspaceStore((s) => s.currentWorkspaceId)
  const { data: teams = [] } = useTeams(wsId)
  const { data: members = [] } = useWorkspaceMembers(wsId)
  const { data: grants = [] } = useDiagramGrants(diagramId)

  const grantTeam = useGrantTeamAccess(diagramId)
  const revokeTeam = useRevokeTeamAccess(diagramId)
  const grantUser = useGrantUserAccess(diagramId)
  const revokeUser = useRevokeUserAccess(diagramId)

  const teamGrant = new Map(
    grants.filter((g) => g.team_id).map((g) => [g.team_id!, g.access_level]),
  )
  const userGrant = new Map(
    grants.filter((g) => g.user_id).map((g) => [g.user_id!, g.access_level]),
  )

  const ungrantedMembers = members.filter((m) => !userGrant.has(m.user_id))

  return (
    <div
      className="fixed inset-0 bg-black/60 flex items-center justify-center z-50"
      onClick={onClose}
    >
      <div
        className="bg-neutral-900 border border-neutral-800 rounded-lg w-[560px] max-h-[80vh] overflow-y-auto p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-sm font-semibold mb-1">Diagram access</h3>
        <p className="text-xs text-neutral-500 mb-5">
          Pick teams or individual users who can see or edit this diagram. With
          nothing assigned, every workspace member can see it.
        </p>

        <h4 className="text-xs font-semibold text-neutral-300 mb-2">Teams</h4>
        {teams.length === 0 ? (
          <div className="text-xs text-neutral-500 italic mb-5">
            No teams yet. Create one on the Teams page.
          </div>
        ) : (
          <table className="w-full text-sm mb-6">
            <tbody>
              {teams.map((t) => {
                const current = teamGrant.get(t.id)
                return (
                  <tr key={t.id} className="border-b border-neutral-800 last:border-0">
                    <td className="py-2">{t.name}</td>
                    <td className="py-2 text-right">
                      {current ? (
                        <>
                          <select
                            value={current}
                            onChange={(e) =>
                              grantTeam.mutate({
                                team_id: t.id,
                                level: e.target.value as DiagramAccessLevel,
                              })
                            }
                            className="bg-neutral-800 border border-neutral-700 rounded px-2 py-0.5 text-xs mr-2"
                          >
                            {LEVELS.map((lvl) => (
                              <option key={lvl} value={lvl}>
                                {lvl}
                              </option>
                            ))}
                          </select>
                          <button
                            onClick={() => revokeTeam.mutate(t.id)}
                            className="text-xs text-red-400 hover:text-red-300"
                          >
                            Revoke
                          </button>
                        </>
                      ) : (
                        <button
                          onClick={() =>
                            grantTeam.mutate({ team_id: t.id, level: 'read' })
                          }
                          className="text-xs text-blue-400 hover:text-blue-300"
                        >
                          + Grant read
                        </button>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}

        <h4 className="text-xs font-semibold text-neutral-300 mb-2">
          Individual users
        </h4>
        <p className="text-xs text-neutral-500 mb-2">
          Use this when someone needs access outside of their team — e.g. an
          auditor or a cross-functional reviewer.
        </p>

        {userGrant.size > 0 && (
          <table className="w-full text-sm mb-3">
            <tbody>
              {Array.from(userGrant.entries()).map(([userId, level]) => {
                const user = members.find((m) => m.user_id === userId)
                return (
                  <tr key={userId} className="border-b border-neutral-800 last:border-0">
                    <td className="py-2">
                      {user ? (
                        <>
                          <span>{user.name}</span>
                          <span className="text-xs text-neutral-500 ml-2">
                            {user.email}
                          </span>
                        </>
                      ) : (
                        <span className="text-xs text-neutral-500 italic">
                          former member
                        </span>
                      )}
                    </td>
                    <td className="py-2 text-right">
                      <select
                        value={level}
                        onChange={(e) =>
                          grantUser.mutate({
                            user_id: userId,
                            level: e.target.value as DiagramAccessLevel,
                          })
                        }
                        className="bg-neutral-800 border border-neutral-700 rounded px-2 py-0.5 text-xs mr-2"
                      >
                        {LEVELS.map((lvl) => (
                          <option key={lvl} value={lvl}>
                            {lvl}
                          </option>
                        ))}
                      </select>
                      <button
                        onClick={() => revokeUser.mutate(userId)}
                        className="text-xs text-red-400 hover:text-red-300"
                      >
                        Revoke
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}

        {ungrantedMembers.length > 0 && (
          <div className="mb-5">
            <select
              onChange={(e) => {
                const uid = e.target.value
                if (uid) {
                  grantUser.mutate({ user_id: uid, level: 'read' })
                  e.currentTarget.value = ''
                }
              }}
              className="w-full bg-neutral-800 border border-neutral-700 rounded px-2 py-1.5 text-sm"
            >
              <option value="">Grant a user directly…</option>
              {ungrantedMembers.map((m) => (
                <option key={m.user_id} value={m.user_id}>
                  {m.name} — {m.email}
                </option>
              ))}
            </select>
          </div>
        )}

        <div className="flex justify-end">
          <button
            onClick={onClose}
            className="bg-blue-600 hover:bg-blue-500 text-white text-xs font-medium rounded px-3 py-1.5"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  )
}
