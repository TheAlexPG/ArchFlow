import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import axios from 'axios'
import type {
  Connection,
  ConnectionCreate,
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

export function useDeleteConnection() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => {
      await api.delete(`/connections/${id}`)
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['connections'] }),
  })
}
