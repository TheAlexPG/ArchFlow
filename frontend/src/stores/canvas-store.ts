import { create } from 'zustand'

interface CanvasState {
  selectedNodeId: string | null
  selectedEdgeId: string | null
  sidebarOpen: boolean
  sidebarTab: 'details' | 'connections' | 'history'
  activeFilter: 'none' | 'tags' | 'technology' | 'status' | 'teams'
  // When set, only objects whose activeFilter value equals this are kept
  // at full opacity; others dim. Like IcePanel's group chips — click a
  // chip to scope the canvas to that slice of the model.
  activeFilterValue: string | null
  addingObjectType: string | null
  treeOpen: boolean
  // When set, canvas dims all nodes/edges that aren't directly connected
  // to this object (upstream or downstream) so the user can trace its
  // dependencies visually. Triggered from the object context menu.
  dependenciesFocusId: string | null
  // Flow playback state: when a flow is playing the canvas dims non-flow
  // edges, highlights each step with a number badge, and surfaces
  // Previous/Next controls. `activeBranch` filters the step list when the
  // selected flow has branching alternative paths.
  playingFlowId: string | null
  playingStepIdx: number
  activeBranch: string | null
  // When set, the next click on empty canvas drops a comment pin of this
  // type at the click position. Cleared after placing one, or on ESC.
  commentComposeType: 'question' | 'inaccuracy' | 'idea' | 'note' | null
  // Per-node live-edit presence: map node_id -> list of remote user names
  // currently selecting/editing that node. Populated by ArchFlowCanvas from
  // the realtime `selections` payload and consumed by individual node
  // components so they can render an `● editing` indicator.
  remoteNodeEditors: Record<string, string[]>
  // Flat list of users currently connected to the active diagram room.
  // Mirrored out of useDiagramSocket(...).presence by ArchFlowCanvas so the
  // page-level top bar (which doesn't own the socket) can render the
  // overlapping avatar stack without duplicating the WS connection.
  presenceUsers: { user_id: string; user_name: string }[]

  selectNode: (id: string | null) => void
  selectEdge: (id: string | null) => void
  toggleSidebar: (open?: boolean) => void
  setSidebarTab: (tab: 'details' | 'connections' | 'history') => void
  setActiveFilter: (filter: 'none' | 'tags' | 'technology' | 'status' | 'teams') => void
  setActiveFilterValue: (value: string | null) => void
  setAddingObjectType: (type: string | null) => void
  toggleTree: () => void
  setDependenciesFocus: (id: string | null) => void
  startFlow: (flowId: string, branch?: string | null) => void
  stopFlow: () => void
  setFlowStep: (idx: number) => void
  setFlowBranch: (branch: string | null) => void
  setCommentComposeType: (t: 'question' | 'inaccuracy' | 'idea' | 'note' | null) => void
  setRemoteNodeEditors: (map: Record<string, string[]>) => void
  setPresenceUsers: (users: { user_id: string; user_name: string }[]) => void
}

export const useCanvasStore = create<CanvasState>((set) => ({
  selectedNodeId: null,
  selectedEdgeId: null,
  sidebarOpen: false,
  sidebarTab: 'details',
  activeFilter: 'none',
  activeFilterValue: null,
  addingObjectType: null,
  treeOpen: false,
  dependenciesFocusId: null,
  playingFlowId: null,
  playingStepIdx: 0,
  activeBranch: null,
  commentComposeType: null,
  remoteNodeEditors: {},
  presenceUsers: [],

  selectNode: (id) =>
    set({ selectedNodeId: id, selectedEdgeId: null, sidebarOpen: id !== null }),
  selectEdge: (id) =>
    set({ selectedEdgeId: id, selectedNodeId: null, sidebarOpen: id !== null }),
  toggleSidebar: (open) =>
    set((state) => ({ sidebarOpen: open ?? !state.sidebarOpen })),
  setSidebarTab: (tab) => set({ sidebarTab: tab }),
  // Switching dimensions invalidates any previous chip selection, so reset.
  setActiveFilter: (filter) =>
    set({ activeFilter: filter, activeFilterValue: null }),
  setActiveFilterValue: (value) => set({ activeFilterValue: value }),
  setAddingObjectType: (type) => set({ addingObjectType: type }),
  toggleTree: () => set((state) => ({ treeOpen: !state.treeOpen })),
  setDependenciesFocus: (id) => set({ dependenciesFocusId: id }),
  startFlow: (flowId, branch = null) =>
    set({ playingFlowId: flowId, playingStepIdx: 0, activeBranch: branch }),
  stopFlow: () =>
    set({ playingFlowId: null, playingStepIdx: 0, activeBranch: null }),
  setFlowStep: (idx) => set({ playingStepIdx: idx }),
  setFlowBranch: (branch) =>
    set({ activeBranch: branch, playingStepIdx: 0 }),
  setCommentComposeType: (t) => set({ commentComposeType: t }),
  setRemoteNodeEditors: (map) => set({ remoteNodeEditors: map }),
  setPresenceUsers: (users) => set({ presenceUsers: users }),
}))
