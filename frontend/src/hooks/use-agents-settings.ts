import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api-client'

// ─── Types ─────────────────────────────────────────────────────────────────

/**
 * Agents settings shape returned by GET /api/v1/agents/settings.
 *
 * Mirrors `AgentSettingsResponse` in
 * `backend/app/api/v1/agent_settings.py`. The LLM API key is never
 * exposed — `litellm.has_key` is a boolean instead.
 */
export interface LLMSettings {
  provider: string | null
  base_url: string | null
  model_default: string | null
  context_window: number | null
  has_key: boolean
}

export interface ContextSettings {
  threshold: number
  strategy: string
  // `ladder` is no longer surfaced in the UI; the backend may still emit it,
  // so keep it optional rather than break the type.
  ladder?: string[]
  tool_result_trim_threshold_tokens: number
}

export interface PerAgentSettings {
  model?: string | null
  turn_limit?: number | null
  budget_usd?: string | null
  budget_scope?: string | null
  context_threshold?: number | null
}

export interface ModelPricing {
  input_per_million: string
  output_per_million: string
}

export type AnalyticsConsent = 'off' | 'errors_only' | 'full'
export type AgentEditsPolicy = 'live_only' | 'drafts_only' | 'ask'

export interface AgentSettings {
  litellm: LLMSettings
  context: ContextSettings
  analytics_consent: AnalyticsConsent
  agent_edits_policy: AgentEditsPolicy
  agents: Record<string, PerAgentSettings>
  model_pricing: Record<string, ModelPricing>
}

// ─── Update payload types ──────────────────────────────────────────────────

/**
 * Update payload — all top-level fields optional.
 * The PUT endpoint deep-merges; passing `null` for a scalar clears it.
 *
 * `litellm.api_key` is plaintext in transit only; the backend encrypts at
 * rest. Pass `null` to clear, pass a string to (re)set.
 */
export interface LLMSettingsUpdate {
  provider?: string | null
  base_url?: string | null
  model_default?: string | null
  context_window?: number | null
  api_key?: string | null
}

export interface ContextSettingsUpdate {
  threshold?: number
  strategy?: string
  tool_result_trim_threshold_tokens?: number
}

export interface AgentSettingsUpdate {
  litellm?: LLMSettingsUpdate
  context?: ContextSettingsUpdate
  analytics_consent?: AnalyticsConsent
  agent_edits_policy?: AgentEditsPolicy
  agents?: Record<string, PerAgentSettings>
  model_pricing?: Record<string, ModelPricing>
}

// ─── Hooks ─────────────────────────────────────────────────────────────────

const KEY = ['agents-settings'] as const

export function useAgentsSettings(opts?: { enabled?: boolean }) {
  return useQuery({
    queryKey: KEY,
    queryFn: async () => {
      const { data } = await api.get<AgentSettings>('/agents/settings')
      return data
    },
    enabled: opts?.enabled ?? true,
    // Settings drift slowly and the page is workspace-admin-only — cache
    // generously so re-opening the page is instant.
    staleTime: 60_000,
  })
}

export function useUpdateAgentsSettings() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: AgentSettingsUpdate) => {
      const { data } = await api.put<AgentSettings>('/agents/settings', body)
      return data
    },
    onSuccess: (data) => {
      // Backend returns the merged result — write it directly so the page
      // reflects saved values without a roundtrip refetch.
      qc.setQueryData(KEY, data)
    },
  })
}
