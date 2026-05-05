import { create } from 'zustand'

export type ContextKey = string // `${diagramId}:${draftId ?? 'live'}`

export interface HistoryEntry {
  id: string
  seq: number
  state: 'active' | 'undone' | 'skipped'
  target_type: string
  target_id: string
  forward_summary: string
  created_at: string
  updated_at: string
  undone_at: string | null
}

export interface StackInfo {
  cursorSeq: number | null
  undoCount: number
  redoCount: number
  recentEntries: HistoryEntry[]
  isInFlight: boolean
}

// Stable singleton returned by getStackInfo when a context has no entry.
// Returning a fresh object literal would make Zustand selectors fire on
// every render and trigger an infinite update loop.
const EMPTY_STACK: StackInfo = Object.freeze({
  cursorSeq: null,
  undoCount: 0,
  redoCount: 0,
  recentEntries: [] as HistoryEntry[],
  isInFlight: false,
}) as StackInfo

const emptyStack = (): StackInfo => ({
  cursorSeq: null,
  undoCount: 0,
  redoCount: 0,
  recentEntries: [],
  isInFlight: false,
})

interface UndoStore {
  byContext: Record<ContextKey, StackInfo>
  getStackInfo(ctx: ContextKey): StackInfo
  setStackInfo(ctx: ContextKey, patch: Partial<StackInfo>): void
  setRecentEntries(ctx: ContextKey, entries: HistoryEntry[]): void
  applyUserUndoEvent(
    ctx: ContextKey,
    evt: { cursor_seq: number | null; redo_count: number },
  ): void
  reset(): void
}

export const useUndoStore = create<UndoStore>((set, get) => ({
  byContext: {},
  getStackInfo: (ctx) => get().byContext[ctx] ?? EMPTY_STACK,
  setStackInfo: (ctx, patch) =>
    set((s) => ({
      byContext: {
        ...s.byContext,
        [ctx]: { ...emptyStack(), ...s.byContext[ctx], ...patch },
      },
    })),
  setRecentEntries: (ctx, entries) =>
    set((s) => ({
      byContext: {
        ...s.byContext,
        [ctx]: { ...emptyStack(), ...s.byContext[ctx], recentEntries: entries },
      },
    })),
  applyUserUndoEvent: (ctx, evt) =>
    set((s) => ({
      byContext: {
        ...s.byContext,
        [ctx]: {
          ...emptyStack(),
          ...s.byContext[ctx],
          cursorSeq: evt.cursor_seq,
          redoCount: evt.redo_count,
        },
      },
    })),
  reset: () => set({ byContext: {} }),
}))

export const ctxKey = (diagramId: string, draftId?: string | null): ContextKey =>
  `${diagramId}:${draftId ?? 'live'}`
