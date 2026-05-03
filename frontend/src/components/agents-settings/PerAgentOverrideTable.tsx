import type { PerAgentSettings } from '../../hooks/use-agents-settings'

// Built-in agents we always render rows for — even if the user hasn't
// stored any overrides yet. Matches the initial agent set shipped by
// agent-core-mvp (general / researcher / diagram-explainer).
const BUILTIN_AGENTS = ['general', 'researcher', 'diagram-explainer'] as const

export type AgentId = (typeof BUILTIN_AGENTS)[number] | string

interface Props {
  /** Current draft state of the per-agent overrides (parent owns it). */
  agents: Record<string, PerAgentSettings>
  /** Default model from settings.litellm.model_default — shown as the
   *  placeholder in the model input so users see what they'd inherit. */
  defaultModel: string | null
  /** Update one field on one agent's overrides. Pass null to clear. */
  onChange: (
    agentId: AgentId,
    field: keyof PerAgentSettings,
    value: string | number | null,
  ) => void
}

export function PerAgentOverrideTable({ agents, defaultModel, onChange }: Props) {
  // Show built-in rows + any custom agents that already have overrides
  // saved (so admins can see and edit everything in one place).
  const customAgentIds = Object.keys(agents).filter(
    (id) => !BUILTIN_AGENTS.includes(id as (typeof BUILTIN_AGENTS)[number]),
  )
  const allIds: AgentId[] = [...BUILTIN_AGENTS, ...customAgentIds]

  return (
    <div
      data-testid="per-agent-table"
      className="bg-neutral-900 border border-neutral-800 rounded-lg overflow-hidden"
    >
      <table className="w-full text-sm">
        <thead>
          <tr className="text-xs text-neutral-500 border-b border-neutral-800">
            <th className="text-left px-4 py-2 font-medium">Agent</th>
            <th className="text-left px-4 py-2 font-medium">Model</th>
            <th className="text-left px-4 py-2 font-medium">Turn limit</th>
            <th className="text-left px-4 py-2 font-medium">Budget (USD)</th>
            <th className="text-left px-4 py-2 font-medium">Budget scope</th>
          </tr>
        </thead>
        <tbody>
          {allIds.map((agentId) => {
            const overrides = agents[agentId] ?? {}
            return (
              <tr
                key={agentId}
                data-testid={`agent-row-${agentId}`}
                className="border-b border-neutral-800 last:border-0"
              >
                <td className="px-4 py-2 text-xs text-neutral-300 font-mono">
                  {agentId}
                </td>
                <td className="px-4 py-2">
                  <input
                    type="text"
                    value={overrides.model ?? ''}
                    placeholder={defaultModel ?? 'inherit default'}
                    onChange={(e) =>
                      onChange(
                        agentId,
                        'model',
                        e.target.value.trim() === '' ? null : e.target.value,
                      )
                    }
                    data-testid={`agent-${agentId}-model`}
                    className="w-full bg-neutral-800 border border-neutral-700 rounded px-2 py-1 text-xs outline-none focus:border-neutral-500"
                  />
                </td>
                <td className="px-4 py-2">
                  <input
                    type="number"
                    min={1}
                    value={overrides.turn_limit ?? ''}
                    placeholder="—"
                    onChange={(e) =>
                      onChange(
                        agentId,
                        'turn_limit',
                        e.target.value === '' ? null : Number(e.target.value),
                      )
                    }
                    data-testid={`agent-${agentId}-turn_limit`}
                    className="w-20 bg-neutral-800 border border-neutral-700 rounded px-2 py-1 text-xs outline-none focus:border-neutral-500"
                  />
                </td>
                <td className="px-4 py-2">
                  <input
                    type="text"
                    inputMode="decimal"
                    value={overrides.budget_usd ?? ''}
                    placeholder="—"
                    onChange={(e) =>
                      onChange(
                        agentId,
                        'budget_usd',
                        e.target.value.trim() === '' ? null : e.target.value,
                      )
                    }
                    data-testid={`agent-${agentId}-budget_usd`}
                    className="w-24 bg-neutral-800 border border-neutral-700 rounded px-2 py-1 text-xs outline-none focus:border-neutral-500"
                  />
                </td>
                <td className="px-4 py-2">
                  <select
                    value={overrides.budget_scope ?? ''}
                    onChange={(e) =>
                      onChange(
                        agentId,
                        'budget_scope',
                        e.target.value === '' ? null : e.target.value,
                      )
                    }
                    data-testid={`agent-${agentId}-budget_scope`}
                    className="bg-neutral-800 border border-neutral-700 rounded px-2 py-1 text-xs outline-none focus:border-neutral-500"
                  >
                    <option value="">—</option>
                    <option value="per_session">per_session</option>
                    <option value="per_run">per_run</option>
                    <option value="per_day">per_day</option>
                  </select>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
