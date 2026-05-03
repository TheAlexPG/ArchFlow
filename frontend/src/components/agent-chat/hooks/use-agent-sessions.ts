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

// ─── Auto-title helper (Phase 1 simplification) ──────────────────────────────
//
// Truncates the first user message to 50 chars and PATCHes the session title.
// Fire-and-forget — callers do not await this.

export function maybeTitleSession(
  sessionId: string,
  firstUserMessage: string,
): void {
  const title = firstUserMessage.slice(0, 50).trim()
  if (!title) return
  // Fire-and-forget: ignore the result — failure here is non-blocking.
  api
    .patch(`/agents/sessions/${sessionId}`, { title })
    .catch(() => { /* intentionally swallowed */ })
}
