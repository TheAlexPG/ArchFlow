import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api-client'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface UndoEntryRead {
  id: string
  seq: number
  state: 'active' | 'undone' | 'skipped'
  target_type: 'object' | 'connection' | 'diagram_object' | 'edge_property' | 'comment'
  target_id: string
  action: 'create' | 'update' | 'delete'
  forward_summary: string
  created_at: string
  updated_at: string
  undone_at: string | null
}

export interface UndoActionResponse {
  undone_entry: UndoEntryRead | null
  redone_entry: UndoEntryRead | null
  cursor_seq: number | null
  remaining_undo_count: number
  redo_count: number
}

export interface UndoHistoryResponse {
  entries: UndoEntryRead[]
  cursor_seq: number | null
}

export interface UndoToResponse {
  applied: { entry_id: string; direction: 'undo' | 'redo' }[]
  cursor_seq: number | null
}

export interface UndoActionRequest {
  expected_seq?: number | null
}

export interface UndoToRequest {
  expected_path_length?: number | null
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

export function useUndo() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({
      diagramId,
      draftId,
      body,
    }: {
      diagramId: string
      draftId?: string | null
      body?: UndoActionRequest
    }): Promise<UndoActionResponse | null> => {
      const response = await api.post<UndoActionResponse>(
        `/diagrams/${diagramId}/undo`,
        body ?? {},
        { params: draftId ? { draft_id: draftId } : undefined },
      )
      if (response.status === 204) return null
      return response.data
    },
    onSuccess: (_data, { diagramId, draftId }) => {
      qc.invalidateQueries({ queryKey: ['undo-history', diagramId, draftId] })
    },
  })
}

export function useRedo() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({
      diagramId,
      draftId,
      body,
    }: {
      diagramId: string
      draftId?: string | null
      body?: UndoActionRequest
    }): Promise<UndoActionResponse | null> => {
      const response = await api.post<UndoActionResponse>(
        `/diagrams/${diagramId}/redo`,
        body ?? {},
        { params: draftId ? { draft_id: draftId } : undefined },
      )
      if (response.status === 204) return null
      return response.data
    },
    onSuccess: (_data, { diagramId, draftId }) => {
      qc.invalidateQueries({ queryKey: ['undo-history', diagramId, draftId] })
    },
  })
}

export function useUndoHistory(diagramId: string | undefined, draftId?: string | null) {
  return useQuery({
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
    enabled: !!diagramId,
  })
}

export function useUndoTo() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({
      diagramId,
      entryId,
      draftId,
      body,
    }: {
      diagramId: string
      entryId: string
      draftId?: string | null
      body?: UndoToRequest
    }): Promise<UndoToResponse> => {
      const { data } = await api.post<UndoToResponse>(
        `/diagrams/${diagramId}/undo-to/${entryId}`,
        body ?? {},
        { params: draftId ? { draft_id: draftId } : undefined },
      )
      return data
    },
    onSuccess: (_data, { diagramId, draftId }) => {
      qc.invalidateQueries({ queryKey: ['undo-history', diagramId, draftId] })
    },
  })
}
