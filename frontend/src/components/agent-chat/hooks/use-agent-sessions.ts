import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../../../lib/api-client'

// ─── Types ──────────────────────────────────────────────────────────────────

export interface AgentSessionListItem {
  id: string
  workspace_id: string
  agent_id: string
  title: string | null
  context_kind: string
  context_id: string | null
  context_draft_id: string | null
  last_message_at: string
  created_at: string
}

interface AgentSessionListResponse {
  items: AgentSessionListItem[]
  next_cursor: string | null
}

export interface AgentSessionDetail extends AgentSessionListItem {
  messages: AgentSessionMessage[]
}

export interface AgentSessionMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  created_at: string
}

// ─── Hooks ──────────────────────────────────────────────────────────────────

export interface AgentSessionFilters {
  agent_id?: string
  context_kind?: string
  cursor?: string
  limit?: number
}

export function useAgentSessions(filters?: AgentSessionFilters) {
  return useQuery({
    queryKey: ['agent-sessions', filters],
    queryFn: async () => {
      const { data } = await api.get<AgentSessionListResponse>(
        '/agents/sessions',
        { params: filters },
      )
      return data.items
    },
  })
}

export function useAgentSession(sessionId: string | null) {
  return useQuery({
    queryKey: ['agent-session', sessionId],
    queryFn: async () => {
      const { data } = await api.get<AgentSessionDetail>(
        `/agents/sessions/${sessionId}`,
      )
      return data
    },
    enabled: !!sessionId,
  })
}

export function useDeleteAgentSession() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (sessionId: string) => {
      await api.delete(`/agents/sessions/${sessionId}`)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['agent-sessions'] })
    },
  })
}

// ─── Auto-title helper ────────────────────────────────────────────────────
//
// Hits the backend's POST /agents/sessions/{id}/auto-title endpoint, which
// runs a quick LLM call against the first persisted user message and
// updates the session title in the background. Idempotent server-side —
// re-calling on a session that already has a title returns the existing
// one. Fire-and-forget; failure is non-blocking. Optional ``onSuccess``
// callback is invoked after the title lands so callers can invalidate
// React Query caches (the picker list, the per-session detail).

export function maybeTitleSession(
  sessionId: string,
  onSuccess?: () => void,
): void {
  api
    .post(`/agents/sessions/${sessionId}/auto-title`)
    .then(() => {
      try {
        onSuccess?.()
      } catch {
        /* user code threw — ignore, this is fire-and-forget */
      }
    })
    .catch(() => { /* intentionally swallowed */ })
}
