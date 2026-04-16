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

export function useObjects() {
  return useQuery({
    queryKey: ['objects'],
    queryFn: async () => {
      const { data } = await api.get<ModelObject[]>('/objects')
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

export function useCreateObject() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (obj: ObjectCreate) => {
      const { data } = await api.post<ModelObject>('/objects', obj)
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

export function useConnections() {
  return useQuery({
    queryKey: ['connections'],
    queryFn: async () => {
      const { data } = await api.get<Connection[]>('/connections')
      return data
    },
  })
}

export function useCreateConnection() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (conn: ConnectionCreate) => {
      const { data } = await api.post<Connection>('/connections', conn)
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
