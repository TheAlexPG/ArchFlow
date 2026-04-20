import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import axios from 'axios'
import type {
  Comment,
  CommentCreate,
  CommentTargetType,
  CommentUpdate,
  Connection,
  ConnectionCreate,
  ConnectionUpdate,
  Draft,
  DraftCreate,
  DraftDiagram,
  DraftDiff,
  DraftFromDiagram,
  Flow,
  FlowCreate,
  FlowUpdate,
  ModelObject,
  ObjectCreate,
  ObjectUpdate,
} from '../types/model'
import { useAuthStore } from '../stores/auth-store'

const api = axios.create({ baseURL: '/api/v1' })

// Auth interceptor
api.interceptors.request.use((config) => {
  const token = useAuthStore.getState().accessToken
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// ─── Objects ─────────────────────────────────────────────

export function useObjects(draftId?: string | null) {
  return useQuery({
    queryKey: ['objects', { draftId: draftId ?? null }],
    queryFn: async () => {
      const { data } = await api.get<ModelObject[]>('/objects', {
        params: draftId ? { draft_id: draftId } : undefined,
      })
      return data
    },
  })
}

export function useObject(id: string | null) {
  return useQuery({
    queryKey: ['objects', id],
    queryFn: async () => {
      const { data } = await api.get<ModelObject>(`/objects/${id}`)
      return data
    },
    enabled: !!id,
  })
}

export interface ActivityLogEntry {
  id: string
  target_type: 'object' | 'connection' | 'diagram'
  target_id: string
  action: 'created' | 'updated' | 'deleted'
  changes: Record<string, { before: unknown; after: unknown }> | Record<string, unknown> | null
  user_id: string | null
  created_at: string
}

export function useObjectChildren(id: string | null) {
  return useQuery({
    queryKey: ['objects', id, 'children'],
    queryFn: async () => {
      const { data } = await api.get<ModelObject[]>(`/objects/${id}/children`)
      return data
    },
    enabled: !!id,
  })
}

export function useObjectHistory(id: string | null) {
  return useQuery({
    queryKey: ['objects', id, 'history'],
    queryFn: async () => {
      const { data } = await api.get<ActivityLogEntry[]>(`/objects/${id}/history`)
      return data
    },
    enabled: !!id,
  })
}

export function useGlobalActivity(params: {
  target_type?: 'object' | 'connection' | 'diagram' | null
  limit?: number
  offset?: number
}) {
  return useQuery({
    queryKey: ['activity', params],
    queryFn: async () => {
      const { data } = await api.get<ActivityLogEntry[]>('/activity', {
        params: {
          target_type: params.target_type || undefined,
          limit: params.limit ?? 100,
          offset: params.offset ?? 0,
        },
      })
      return data
    },
  })
}

export function useCreateObject(draftId?: string | null) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (obj: ObjectCreate) => {
      const { data } = await api.post<ModelObject>('/objects', obj, {
        params: draftId ? { draft_id: draftId } : undefined,
      })
      return data
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['objects'] }),
  })
}

export function useUpdateObject() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, ...data }: ObjectUpdate & { id: string }) => {
      const { data: result } = await api.put<ModelObject>(`/objects/${id}`, data)
      return result
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['objects'] }),
  })
}

export function useDeleteObject() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => {
      await api.delete(`/objects/${id}`)
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['objects'] }),
  })
}

// ─── Connections ─────────────────────────────────────────

export function useConnections(draftId?: string | null) {
  return useQuery({
    queryKey: ['connections', { draftId: draftId ?? null }],
    queryFn: async () => {
      const { data } = await api.get<Connection[]>('/connections', {
        params: draftId ? { draft_id: draftId } : undefined,
      })
      return data
    },
  })
}

export function useCreateConnection(draftId?: string | null) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (conn: ConnectionCreate) => {
      const { data } = await api.post<Connection>('/connections', conn, {
        params: draftId ? { draft_id: draftId } : undefined,
      })
      return data
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['connections'] }),
  })
}

export function useSavePosition() {
  return useMutation({
    mutationFn: async ({ id, x, y }: { id: string; x: number; y: number }) => {
      await api.put(`/objects/${id}`, { metadata: { position: { x, y } } })
    },
  })
}

// ─── Diagram Objects ────────────────────────────────────

export interface DiagramObjectData {
  id: string
  diagram_id: string
  object_id: string
  position_x: number
  position_y: number
  width: number | null
  height: number | null
}

export function useDiagramObjects(diagramId: string | undefined) {
  return useQuery({
    queryKey: ['diagram-objects', diagramId],
    queryFn: async () => {
      const { data } = await api.get<DiagramObjectData[]>(`/diagrams/${diagramId}/objects`)
      return data
    },
    enabled: !!diagramId,
  })
}

export function useAddObjectToDiagram() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({
      diagramId, objectId, x, y,
    }: { diagramId: string; objectId: string; x: number; y: number }) => {
      const { data } = await api.post(`/diagrams/${diagramId}/objects`, {
        object_id: objectId, position_x: x, position_y: y,
      })
      return data
    },
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: ['diagram-objects', vars.diagramId] })
    },
  })
}

export function useSaveDiagramPosition() {
  return useMutation({
    mutationFn: async ({
      diagramId, objectId, x, y,
    }: { diagramId: string; objectId: string; x: number; y: number }) => {
      await api.put(`/diagrams/${diagramId}/objects/${objectId}`, {
        position_x: x, position_y: y,
      })
    },
  })
}

export function useSaveDiagramSize() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({
      diagramId, objectId, width, height,
    }: { diagramId: string; objectId: string; width: number; height: number }) => {
      await api.put(`/diagrams/${diagramId}/objects/${objectId}`, {
        width, height,
      })
    },
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: ['diagram-objects', vars.diagramId] })
    },
  })
}

export function useRemoveObjectFromDiagram() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ diagramId, objectId }: { diagramId: string; objectId: string }) => {
      await api.delete(`/diagrams/${diagramId}/objects/${objectId}`)
    },
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: ['diagram-objects', vars.diagramId] })
    },
  })
}

export function useDeleteConnection() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => {
      await api.delete(`/connections/${id}`)
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['connections'] }),
  })
}

export function useConnection(id: string | null) {
  return useQuery({
    queryKey: ['connections', id],
    queryFn: async () => {
      const { data } = await api.get<Connection>(`/connections/${id}`)
      return data
    },
    enabled: !!id,
  })
}

export function useUpdateConnection() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, ...data }: ConnectionUpdate & { id: string }) => {
      const { data: result } = await api.put<Connection>(`/connections/${id}`, data)
      return result
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['connections'] }),
  })
}

// ─── Comments ────────────────────────────────────────────

export function useComments(targetType: CommentTargetType, targetId: string | null) {
  return useQuery({
    queryKey: ['comments', targetType, targetId],
    queryFn: async () => {
      const { data } = await api.get<Comment[]>('/comments', {
        params: { target_type: targetType, target_id: targetId },
      })
      return data
    },
    enabled: !!targetId,
  })
}

export function useCreateComment() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (data: CommentCreate) => {
      const { data: result } = await api.post<Comment>('/comments', data)
      return result
    },
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: ['comments', vars.target_type, vars.target_id] })
    },
  })
}

export function useUpdateComment() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, ...data }: CommentUpdate & { id: string }) => {
      const { data: result } = await api.put<Comment>(`/comments/${id}`, data)
      return result
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['comments'] }),
  })
}

export function useDeleteComment() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => {
      await api.delete(`/comments/${id}`)
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['comments'] }),
  })
}

// ─── AI Insights ─────────────────────────────────────────

export interface ObjectInsights {
  summary: string
  observations: string[]
  recommendations: string[]
}

export function useGetInsights() {
  return useMutation({
    mutationFn: async (objectId: string) => {
      const { data } = await api.post<ObjectInsights>(`/objects/${objectId}/insights`)
      return data
    },
  })
}

// ─── Flows ───────────────────────────────────────────────

export function useFlows(diagramId: string | undefined) {
  return useQuery({
    queryKey: ['flows', diagramId],
    queryFn: async () => {
      const { data } = await api.get<Flow[]>(`/diagrams/${diagramId}/flows`)
      return data
    },
    enabled: !!diagramId,
  })
}

export function useCreateFlow() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ diagramId, ...data }: FlowCreate & { diagramId: string }) => {
      const { data: result } = await api.post<Flow>(`/diagrams/${diagramId}/flows`, data)
      return result
    },
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: ['flows', vars.diagramId] })
    },
  })
}

export function useUpdateFlow() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, ...data }: FlowUpdate & { id: string }) => {
      const { data: result } = await api.put<Flow>(`/flows/${id}`, data)
      return result
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['flows'] }),
  })
}

export function useDeleteFlow() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => {
      await api.delete(`/flows/${id}`)
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['flows'] }),
  })
}

// ─── Drafts (diagram forks) ───────────────────────────────

export function useDrafts() {
  return useQuery({
    queryKey: ['drafts'],
    queryFn: async () => {
      const { data } = await api.get<Draft[]>('/drafts')
      return data
    },
  })
}

export function useDraft(id: string | null) {
  return useQuery({
    queryKey: ['drafts', id],
    queryFn: async () => {
      const { data } = await api.get<Draft>(`/drafts/${id}`)
      return data
    },
    enabled: !!id,
  })
}

export function useCreateDraft() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (data: DraftCreate) => {
      const { data: result } = await api.post<Draft>('/drafts', data)
      return result
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['drafts'] }),
  })
}

/**
 * Fork an existing diagram into a new draft. Returns the draft with
 * `forked_diagram_id` set — the frontend should navigate the user there.
 */
export function useCreateDraftFromDiagram() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({
      diagramId,
      ...data
    }: DraftFromDiagram & { diagramId: string }) => {
      const { data: result } = await api.post<Draft>(
        `/drafts/from-diagram/${diagramId}`,
        data,
      )
      return result
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['drafts'] })
      qc.invalidateQueries({ queryKey: ['diagrams'] })
    },
  })
}

export function useAddDiagramToDraft() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ draftId, diagramId }: { draftId: string; diagramId: string }) => {
      const { data } = await api.post<DraftDiagram>(`/drafts/${draftId}/diagrams/${diagramId}`)
      return data
    },
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: ['drafts'] })
      qc.invalidateQueries({ queryKey: ['drafts', vars.draftId] })
      qc.invalidateQueries({ queryKey: ['diagrams', vars.diagramId, 'drafts'] })
    },
  })
}

export function useRemoveDiagramFromDraft() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ draftId, diagramId }: { draftId: string; diagramId: string }) => {
      await api.delete(`/drafts/${draftId}/diagrams/${diagramId}`)
    },
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: ['drafts'] })
      qc.invalidateQueries({ queryKey: ['drafts', vars.draftId] })
      qc.invalidateQueries({ queryKey: ['diagrams', vars.diagramId, 'drafts'] })
    },
  })
}

/** Slim entry returned by GET /diagrams/{id}/drafts */
export interface DiagramDraftEntry {
  draft_id: string
  draft_name: string
  draft_status: string
  source_diagram_id: string
  forked_diagram_id: string
}

export function useDraftsForDiagram(diagramId: string | undefined) {
  return useQuery({
    queryKey: ['diagrams', diagramId, 'drafts'],
    queryFn: async () => {
      const { data } = await api.get<DiagramDraftEntry[]>(`/diagrams/${diagramId}/drafts`)
      return data
    },
    enabled: !!diagramId,
  })
}

export function useDeleteDraft() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => {
      await api.delete(`/drafts/${id}`)
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['drafts'] }),
  })
}

export function useApplyDraft() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (draftId: string) => {
      const { data } = await api.post(`/drafts/${draftId}/apply`)
      return data
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['drafts'] })
      qc.invalidateQueries({ queryKey: ['objects'] })
      qc.invalidateQueries({ queryKey: ['connections'] })
      qc.invalidateQueries({ queryKey: ['diagrams'] })
    },
  })
}

/**
 * Row-level diff between the source diagram and the forked draft. Powers
 * the coloured badges on the side-by-side compare canvases and the summary
 * strip above them.
 */
export function useDraftDiff(draftId: string | null) {
  return useQuery({
    queryKey: ['drafts', draftId, 'diff'],
    queryFn: async () => {
      const { data } = await api.get<DraftDiff>(`/drafts/${draftId}/diff`)
      return data
    },
    enabled: !!draftId,
  })
}

export function useDiscardDraft() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (draftId: string) => {
      const { data } = await api.post<Draft>(`/drafts/${draftId}/discard`)
      return data
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['drafts'] })
      qc.invalidateQueries({ queryKey: ['diagrams'] })
    },
  })
}
