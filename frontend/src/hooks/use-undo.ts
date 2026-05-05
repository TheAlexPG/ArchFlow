import { useEffect } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../lib/api-client'
import {
  useUndo as useUndoRaw,
  useRedo as useRedoRaw,
  useUndoTo as useUndoToRaw,
  type UndoHistoryResponse,
} from './use-undo-api'
import { ctxKey, useUndoStore, type HistoryEntry } from '../stores/undo-store'

// ---------------------------------------------------------------------------
// Controller
// ---------------------------------------------------------------------------

interface ControllerOptions {
  diagramId: string
  draftId?: string | null
  onUndo: () => void
  onRedo: () => void
}

const isEditableTarget = (el: EventTarget | null): boolean => {
  if (!(el instanceof HTMLElement)) return false
  const tag = el.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || el.isContentEditable
}

export function useUndoController({ diagramId, draftId, onUndo, onRedo }: ControllerOptions) {
  // diagramId / draftId are part of the context but the controller itself
  // only owns keybinds; the parent passes onUndo/onRedo bound to the
  // current context.
  void diagramId
  void draftId

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (isEditableTarget(e.target)) return
      const mod = e.metaKey || e.ctrlKey
      if (!mod) return

      if (e.key === 'z' && !e.shiftKey) {
        e.preventDefault()
        onUndo()
      } else if ((e.key === 'z' && e.shiftKey) || e.key === 'y') {
        e.preventDefault()
        onRedo()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onUndo, onRedo])
}

// ---------------------------------------------------------------------------
// useUndoMutation
// ---------------------------------------------------------------------------

export function useUndoMutation(diagramId: string, draftId?: string | null) {
  const qc = useQueryClient()
  const ctx = ctxKey(diagramId, draftId)
  const setStackInfo = useUndoStore((s) => s.setStackInfo)
  const undoMut = useUndoRaw()

  return useMutation({
    mutationFn: async () => {
      setStackInfo(ctx, { isInFlight: true })
      const expectedSeq = useUndoStore.getState().getStackInfo(ctx).cursorSeq
      return undoMut.mutateAsync({
        diagramId,
        draftId: draftId ?? null,
        body: { expected_seq: expectedSeq ?? null },
      })
    },
    onSettled: async (data) => {
      setStackInfo(ctx, { isInFlight: false })
      if (data) {
        setStackInfo(ctx, {
          cursorSeq: data.cursor_seq,
          undoCount: data.remaining_undo_count,
          redoCount: data.redo_count,
        })
      }
      // 204 (empty stack) returns null; nothing to write but still drop
      // any cached query data that might be stale.
      await qc.invalidateQueries({ queryKey: ['diagram', diagramId] })
    },
    onError: async (err: any) => {
      setStackInfo(ctx, { isInFlight: false })
      // 409 means the client's expected_seq drifted from the server. Drop
      // the history cache so the next render pulls fresh.
      if (err?.response?.status === 409) {
        await qc.invalidateQueries({ queryKey: ['undo-history', diagramId, draftId] })
      }
    },
  })
}

// ---------------------------------------------------------------------------
// useRedoMutation
// ---------------------------------------------------------------------------

export function useRedoMutation(diagramId: string, draftId?: string | null) {
  const qc = useQueryClient()
  const ctx = ctxKey(diagramId, draftId)
  const setStackInfo = useUndoStore((s) => s.setStackInfo)
  const redoMut = useRedoRaw()

  return useMutation({
    mutationFn: async () => {
      setStackInfo(ctx, { isInFlight: true })
      return redoMut.mutateAsync({
        diagramId,
        draftId: draftId ?? null,
      })
    },
    onSettled: async (data) => {
      setStackInfo(ctx, { isInFlight: false })
      if (data) {
        setStackInfo(ctx, {
          cursorSeq: data.cursor_seq,
          undoCount: data.remaining_undo_count,
          redoCount: data.redo_count,
        })
      }
      await qc.invalidateQueries({ queryKey: ['diagram', diagramId] })
    },
    onError: async () => {
      setStackInfo(ctx, { isInFlight: false })
    },
  })
}

// ---------------------------------------------------------------------------
// useUndoTo
// ---------------------------------------------------------------------------

export function useUndoTo(diagramId: string, draftId?: string | null) {
  const qc = useQueryClient()
  const ctx = ctxKey(diagramId, draftId)
  const setStackInfo = useUndoStore((s) => s.setStackInfo)
  const undoToMut = useUndoToRaw()

  return useMutation({
    mutationFn: async ({
      entryId,
      expectedPathLength,
    }: {
      entryId: string
      expectedPathLength?: number
    }) => {
      setStackInfo(ctx, { isInFlight: true })
      return undoToMut.mutateAsync({
        diagramId,
        entryId,
        draftId: draftId ?? null,
        body: { expected_path_length: expectedPathLength ?? null },
      })
    },
    onSettled: async (data) => {
      setStackInfo(ctx, { isInFlight: false })
      if (data) {
        setStackInfo(ctx, { cursorSeq: data.cursor_seq })
      }
      await qc.invalidateQueries({ queryKey: ['diagram', diagramId] })
      await qc.invalidateQueries({ queryKey: ['undo-history', diagramId, draftId] })
    },
    onError: async () => {
      setStackInfo(ctx, { isInFlight: false })
    },
  })
}

// ---------------------------------------------------------------------------
// useDiagramHistory
// Re-implemented (not using useUndoHistoryRaw) to properly forward the
// `enabled` flag. useUndoHistoryRaw hardcodes `enabled: !!diagramId`, so
// callers cannot suppress the fetch when the history panel is closed.
// ---------------------------------------------------------------------------

export function useDiagramHistory(
  diagramId: string,
  draftId?: string | null,
  enabled = false,
) {
  const ctx = ctxKey(diagramId, draftId)

  const query = useQuery({
    queryKey: ['undo-history', diagramId, draftId],
    queryFn: async () => {
      const params: Record<string, string | number> = { limit: 50 }
      if (draftId) params.draft_id = draftId
      const { data } = await api.get<UndoHistoryResponse>(
        `/diagrams/${diagramId}/history`,
        { params },
      )
      return data
    },
    enabled: !!diagramId && enabled,
  })

  // Sync entries AND derived counts into the Zustand store whenever the
  // query data changes. Without populating undoCount/redoCount the toolbar
  // buttons stay disabled even when the fetched history has active or
  // undone entries — normal mutation routes never call setStackInfo
  // themselves, so this is the only path that initialises those numbers.
  useEffect(() => {
    if (query.data) {
      const entries = query.data.entries as unknown as HistoryEntry[]
      let undoCount = 0
      let redoCount = 0
      for (const e of entries) {
        if (e.state === 'active') undoCount += 1
        else if (e.state === 'undone') redoCount += 1
      }
      useUndoStore.getState().setStackInfo(ctx, {
        cursorSeq: query.data.cursor_seq,
        undoCount,
        redoCount,
        recentEntries: entries,
      })
    }
  }, [query.data, ctx])

  return query
}
