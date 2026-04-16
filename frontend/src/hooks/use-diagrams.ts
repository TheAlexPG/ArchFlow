import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import axios from 'axios'
import { useAuthStore } from '../stores/auth-store'

const api = axios.create({ baseURL: '/api/v1' })

api.interceptors.request.use((config) => {
  const token = useAuthStore.getState().accessToken
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

export interface Diagram {
  id: string
  name: string
  type: string
  description: string | null
  scope_object_id: string | null
  settings: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

export function useDiagrams() {
  return useQuery({
    queryKey: ['diagrams'],
    queryFn: async () => {
      const { data } = await api.get<Diagram[]>('/diagrams')
      return data
    },
  })
}

export function useCreateDiagram() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (data: { name: string; type: string; description?: string }) => {
      const { data: result } = await api.post<Diagram>('/diagrams', data)
      return result
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['diagrams'] }),
  })
}

export function useObjectDiagrams(objectId: string | undefined) {
  return useQuery({
    queryKey: ['object-diagrams', objectId],
    queryFn: async () => {
      const { data } = await api.get<Diagram[]>(`/objects/${objectId}/diagrams`)
      return data
    },
    enabled: !!objectId,
  })
}

export function useDiagram(id: string | undefined) {
  return useQuery({
    queryKey: ['diagrams', id],
    queryFn: async () => {
      const { data } = await api.get<Diagram>(`/diagrams/${id}`)
      return data
    },
    enabled: !!id,
  })
}

export function useDeleteDiagram() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => {
      await api.delete(`/diagrams/${id}`)
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['diagrams'] }),
  })
}
