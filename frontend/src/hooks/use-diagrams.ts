import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import axios from 'axios'
import { useAuthStore } from '../stores/auth-store'
import type { ModelObject } from '../types/model'

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
  pinned: boolean
  draft_id: string | null
  created_at: string
  updated_at: string
}

export function useDiagrams(scopeObjectId?: string | null) {
  return useQuery({
    queryKey: ['diagrams', { scope: scopeObjectId }],
    queryFn: async () => {
      const params = scopeObjectId ? { scope_object_id: scopeObjectId } : {}
      const { data } = await api.get<Diagram[]>('/diagrams', { params })
      return data
    },
  })
}

export function useCreateDiagram() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (data: { name: string; type: string; description?: string; scope_object_id?: string | null }) => {
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

export function useUpdateDiagram() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, ...data }: { id: string; pinned?: boolean; name?: string; description?: string | null }) => {
      const { data: result } = await api.put<Diagram>(`/diagrams/${id}`, data)
      return result
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['diagrams'] }),
  })
}

// C4 diagram hierarchy:  system_landscape / system_context  →  container  →  component
// Given a child diagram type, returns the expected parent diagram types.
function parentDiagramTypes(type: string): string[] {
  if (type === 'container') return ['system_landscape', 'system_context']
  if (type === 'component') return ['container']
  return []
}

/**
 * Walk up the C4 parent chain from the current diagram.
 * Returns an ordered array starting from the topmost ancestor down to the
 * current diagram (inclusive).
 *
 * Strategy:
 *   1. Start with the current diagram.
 *   2. If it has scope_object_id, fetch that object, then fetch all diagrams
 *      that *contain* that object (`GET /objects/{id}/diagrams`) and pick the
 *      one whose type is one level up.
 *   3. Repeat up to 6 levels deep to guard against cycles.
 */
export function useDiagramBreadcrumbs(diagramId: string | undefined): Diagram[] {
  // Fetch the starting diagram
  const { data: currentDiagram } = useDiagram(diagramId)

  // Build a chain of (scopeObjectId, diagram) pairs up the hierarchy.
  // We use individual queries for each level so react-query caches them.
  // Level 0 = current, level N = ancestor at depth N.

  // Collect scope_object_ids we need to walk up: current → parent → ...
  // We do this iteratively using nested useQuery calls.  Because hooks can't
  // be called conditionally, we pre-declare queries for each depth level and
  // stop using results once a level doesn't apply.

  const l0ScopeId = currentDiagram?.scope_object_id ?? null

  // Prefetch the scope object (unused directly; cache warmup for ObjectSidebar)
  useQuery({
    queryKey: ['objects', l0ScopeId],
    queryFn: async () => {
      const { data } = await api.get<ModelObject>(`/objects/${l0ScopeId}`)
      return data
    },
    enabled: !!l0ScopeId,
  })

  const { data: l0ParentDiagrams = [] } = useQuery({
    queryKey: ['object-diagrams', l0ScopeId],
    queryFn: async () => {
      const { data } = await api.get<Diagram[]>(`/objects/${l0ScopeId}/diagrams`)
      return data
    },
    enabled: !!l0ScopeId,
  })

  const l0ParentDiagram = l0ParentDiagrams.find((d) =>
    parentDiagramTypes(currentDiagram?.type ?? '').includes(d.type),
  ) ?? null

  // Level 1 — parent of the parent
  const l1ScopeId = l0ParentDiagram?.scope_object_id ?? null

  const { data: _l0Obj } = useQuery({
    queryKey: ['objects', l1ScopeId],
    queryFn: async () => {
      const { data } = await api.get<ModelObject>(`/objects/${l1ScopeId}`)
      return data
    },
    enabled: !!l1ScopeId,
  })
  void _l0Obj // used only to prefill cache

  const { data: l1ParentDiagrams = [] } = useQuery({
    queryKey: ['object-diagrams', l1ScopeId],
    queryFn: async () => {
      const { data } = await api.get<Diagram[]>(`/objects/${l1ScopeId}/diagrams`)
      return data
    },
    enabled: !!l1ScopeId,
  })

  const l1ParentDiagram = l1ParentDiagrams.find((d) =>
    parentDiagramTypes(l0ParentDiagram?.type ?? '').includes(d.type),
  ) ?? null

  // Level 2 — grandparent (capped at MAX_BREADCRUMB_DEPTH = 6 in spirit;
  // the C4 chain is max 3 levels deep so 2 ancestor hops is the practical limit).
  const l2ScopeId = l1ParentDiagram?.scope_object_id ?? null

  const { data: _l1Obj } = useQuery({
    queryKey: ['objects', l2ScopeId],
    queryFn: async () => {
      const { data } = await api.get<ModelObject>(`/objects/${l2ScopeId}`)
      return data
    },
    enabled: !!l2ScopeId,
  })
  void _l1Obj

  const { data: l2ParentDiagrams = [] } = useQuery({
    queryKey: ['object-diagrams', l2ScopeId],
    queryFn: async () => {
      const { data } = await api.get<Diagram[]>(`/objects/${l2ScopeId}/diagrams`)
      return data
    },
    enabled: !!l2ScopeId,
  })

  const l2ParentDiagram = l2ParentDiagrams.find((d) =>
    parentDiagramTypes(l1ParentDiagram?.type ?? '').includes(d.type),
  ) ?? null

  // Build ordered chain from top to bottom
  const chain: Diagram[] = []
  if (l2ParentDiagram) chain.push(l2ParentDiagram)
  if (l1ParentDiagram && !chain.includes(l1ParentDiagram)) chain.push(l1ParentDiagram)
  if (l0ParentDiagram && !chain.includes(l0ParentDiagram)) chain.push(l0ParentDiagram)
  if (currentDiagram) chain.push(currentDiagram)

  return chain
}
