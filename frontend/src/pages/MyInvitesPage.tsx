import { useWorkspaceStore } from '../stores/workspace-store'
import { AppSidebar } from '../components/nav/AppSidebar'
import {
  useAcceptMyInvite,
  useDeclineMyInvite,
  useMyInvites,
} from '../hooks/use-api'

export function MyInvitesPage() {
  const { data: invites = [], isLoading } = useMyInvites()
  const accept = useAcceptMyInvite()
  const decline = useDeclineMyInvite()
  const setCurrentWorkspaceId = useWorkspaceStore((s) => s.setCurrentWorkspaceId)

  return (
    <div className="flex h-screen bg-neutral-950 text-neutral-200">
      <AppSidebar />
      <div className="flex-1 overflow-y-auto p-8">
        <h1 className="text-xl font-semibold mb-2">Invitations</h1>
        <p className="text-xs text-neutral-500 mb-6">
          Workspaces you've been invited to. Accept to join, decline to dismiss.
        </p>

        {isLoading && (
          <div className="text-xs text-neutral-500 italic">Loading…</div>
        )}

        {!isLoading && invites.length === 0 && (
          <div className="bg-neutral-900 border border-neutral-800 rounded-lg p-6 text-center text-sm text-neutral-500 max-w-2xl">
            No pending invitations.
          </div>
        )}

        <div className="space-y-3 max-w-2xl">
          {invites.map((inv) => (
            <div
              key={inv.id}
              className="bg-neutral-900 border border-neutral-800 rounded-lg p-4 flex items-center justify-between"
            >
              <div>
                <div className="text-sm font-medium">{inv.workspace_name}</div>
                <div className="text-xs text-neutral-400 mt-0.5">
                  Role: <span className="text-neutral-300">{inv.role}</span>
                  {' · '}
                  <span className="text-neutral-500">
                    {new Date(inv.invited_at).toLocaleString()}
                  </span>
                </div>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={async () => {
                    const res = await accept.mutateAsync(inv.id)
                    // Auto-switch to the joined workspace.
                    setCurrentWorkspaceId(res.workspace_id)
                  }}
                  disabled={accept.isPending}
                  className="bg-blue-600 hover:bg-blue-500 text-white text-xs font-medium rounded px-3 py-1.5 disabled:opacity-40"
                >
                  Accept
                </button>
                <button
                  onClick={() => decline.mutate(inv.id)}
                  disabled={decline.isPending}
                  className="bg-neutral-800 hover:bg-neutral-700 text-neutral-300 text-xs rounded px-3 py-1.5 disabled:opacity-40"
                >
                  Decline
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
