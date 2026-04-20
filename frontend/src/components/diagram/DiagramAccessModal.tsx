import {
  useDiagramGrants,
  useGrantTeamAccess,
  useRevokeTeamAccess,
  useTeams,
} from '../../hooks/use-api'
import { useWorkspaceStore } from '../../stores/workspace-store'
import type { DiagramAccessLevel } from '../../types/model'

const LEVELS: DiagramAccessLevel[] = ['read', 'write', 'admin']

/**
 * Admin-facing modal to grant or revoke per-diagram team access. No grants =
 * diagram visible workspace-wide. Any grant flips it to restricted.
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
  const { data: grants = [] } = useDiagramGrants(diagramId)
  const grant = useGrantTeamAccess(diagramId)
  const revoke = useRevokeTeamAccess(diagramId)

  const granted = new Map(grants.map((g) => [g.team_id, g.access_level]))

  return (
    <div
      className="fixed inset-0 bg-black/60 flex items-center justify-center z-50"
      onClick={onClose}
    >
      <div
        className="bg-neutral-900 border border-neutral-800 rounded-lg w-[520px] p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-sm font-semibold mb-1">Diagram access</h3>
        <p className="text-xs text-neutral-500 mb-4">
          Pick which teams can see or edit this diagram. With no teams assigned,
          every workspace member can see it.
        </p>

        {teams.length === 0 ? (
          <div className="text-xs text-neutral-500 italic mb-4">
            You haven't created any teams yet. Create one from the Teams page.
          </div>
        ) : (
          <table className="w-full text-sm mb-4">
            <tbody>
              {teams.map((t) => {
                const current = granted.get(t.id)
                return (
                  <tr key={t.id} className="border-b border-neutral-800 last:border-0">
                    <td className="py-2">{t.name}</td>
                    <td className="py-2 text-right">
                      {current ? (
                        <>
                          <select
                            value={current}
                            onChange={(e) =>
                              grant.mutate({
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
                            onClick={() => revoke.mutate(t.id)}
                            className="text-xs text-red-400 hover:text-red-300"
                          >
                            Revoke
                          </button>
                        </>
                      ) : (
                        <button
                          onClick={() =>
                            grant.mutate({ team_id: t.id, level: 'read' })
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
