import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface WorkspaceState {
  /** ID the user has picked as "current". Null until the API returns their
   *  workspaces list and we auto-select the first one. */
  currentWorkspaceId: string | null
  setCurrentWorkspaceId: (id: string | null) => void
}

export const useWorkspaceStore = create<WorkspaceState>()(
  persist(
    (set) => ({
      currentWorkspaceId: null,
      setCurrentWorkspaceId: (id) => set({ currentWorkspaceId: id }),
    }),
    { name: 'archflow-workspace' },
  ),
)
