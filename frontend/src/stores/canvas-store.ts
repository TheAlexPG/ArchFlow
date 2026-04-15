import { create } from 'zustand'

interface CanvasState {
  selectedNodeId: string | null
  selectedEdgeId: string | null
  sidebarOpen: boolean
  sidebarTab: 'details' | 'connections' | 'history'
  activeFilter: 'none' | 'tags' | 'technology' | 'status' | 'teams'
  addingObjectType: string | null

  selectNode: (id: string | null) => void
  selectEdge: (id: string | null) => void
  toggleSidebar: (open?: boolean) => void
  setSidebarTab: (tab: 'details' | 'connections' | 'history') => void
  setActiveFilter: (filter: 'none' | 'tags' | 'technology' | 'status' | 'teams') => void
  setAddingObjectType: (type: string | null) => void
}

export const useCanvasStore = create<CanvasState>((set) => ({
  selectedNodeId: null,
  selectedEdgeId: null,
  sidebarOpen: false,
  sidebarTab: 'details',
  activeFilter: 'none',
  addingObjectType: null,

  selectNode: (id) =>
    set({ selectedNodeId: id, selectedEdgeId: null, sidebarOpen: id !== null }),
  selectEdge: (id) =>
    set({ selectedEdgeId: id, selectedNodeId: null }),
  toggleSidebar: (open) =>
    set((state) => ({ sidebarOpen: open ?? !state.sidebarOpen })),
  setSidebarTab: (tab) => set({ sidebarTab: tab }),
  setActiveFilter: (filter) => set({ activeFilter: filter }),
  setAddingObjectType: (type) => set({ addingObjectType: type }),
}))
