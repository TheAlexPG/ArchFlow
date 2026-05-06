import { useState } from 'react'
import type { ModelPricing } from '../../hooks/use-agents-settings'

interface Props {
  /** The pricing draft, keyed by model id. Parent owns this state. */
  pricing: Record<string, ModelPricing>
  /** Replace one model's pricing entry. Pass null to delete (PUT will
   *  clear the row server-side once we wire null-handling). For now we
   *  simply remove the key locally and the backend won't see it. */
  onChange: (modelId: string, value: ModelPricing | null) => void
}

export function ModelPricingTable({ pricing, onChange }: Props) {
  // Local state for the "+ Add row" form. Once the user hits Add we
  // commit the row into the parent draft and reset.
  const [newId, setNewId] = useState('')
  const [newInput, setNewInput] = useState('')
  const [newOutput, setNewOutput] = useState('')

  const entries = Object.entries(pricing).sort(([a], [b]) => a.localeCompare(b))

  const addRow = () => {
    const id = newId.trim()
    if (!id) return
    onChange(id, {
      input_per_million: newInput.trim() || '0',
      output_per_million: newOutput.trim() || '0',
    })
    setNewId('')
    setNewInput('')
    setNewOutput('')
  }

  return (
    <div
      data-testid="model-pricing-table"
      className="bg-neutral-900 border border-neutral-800 rounded-lg overflow-hidden"
    >
      <table className="w-full text-sm">
        <thead>
          <tr className="text-xs text-neutral-500 border-b border-neutral-800">
            <th className="text-left px-4 py-2 font-medium">Model</th>
            <th className="text-left px-4 py-2 font-medium">Input ($/1M tokens)</th>
            <th className="text-left px-4 py-2 font-medium">Output ($/1M tokens)</th>
            <th className="text-right px-4 py-2 font-medium" />
          </tr>
        </thead>
        <tbody>
          {entries.length === 0 && (
            <tr>
              <td
                colSpan={4}
                className="px-4 py-3 text-xs text-neutral-500 italic"
              >
                No pricing overrides — falling back to LiteLLM defaults.
              </td>
            </tr>
          )}
          {entries.map(([modelId, p]) => (
            <tr
              key={modelId}
              data-testid={`pricing-row-${modelId}`}
              className="border-b border-neutral-800 last:border-0"
            >
              <td className="px-4 py-2 text-xs font-mono text-neutral-300">
                {modelId}
              </td>
              <td className="px-4 py-2">
                <input
                  type="text"
                  inputMode="decimal"
                  value={p.input_per_million}
                  onChange={(e) =>
                    onChange(modelId, {
                      ...p,
                      input_per_million: e.target.value,
                    })
                  }
                  data-testid={`pricing-${modelId}-input`}
                  className="w-28 bg-neutral-800 border border-neutral-700 rounded px-2 py-1 text-xs outline-none focus:border-neutral-500"
                />
              </td>
              <td className="px-4 py-2">
                <input
                  type="text"
                  inputMode="decimal"
                  value={p.output_per_million}
                  onChange={(e) =>
                    onChange(modelId, {
                      ...p,
                      output_per_million: e.target.value,
                    })
                  }
                  data-testid={`pricing-${modelId}-output`}
                  className="w-28 bg-neutral-800 border border-neutral-700 rounded px-2 py-1 text-xs outline-none focus:border-neutral-500"
                />
              </td>
              <td className="px-4 py-2 text-right">
                <button
                  type="button"
                  onClick={() => onChange(modelId, null)}
                  data-testid={`pricing-${modelId}-delete`}
                  className="text-xs text-red-400 hover:text-red-300"
                >
                  Delete
                </button>
              </td>
            </tr>
          ))}
          {/* Add row */}
          <tr className="bg-neutral-950">
            <td className="px-4 py-2">
              <input
                type="text"
                value={newId}
                onChange={(e) => setNewId(e.target.value)}
                placeholder="claude-haiku-3-5"
                data-testid="pricing-new-id"
                className="w-full bg-neutral-800 border border-neutral-700 rounded px-2 py-1 text-xs outline-none focus:border-neutral-500"
              />
            </td>
            <td className="px-4 py-2">
              <input
                type="text"
                inputMode="decimal"
                value={newInput}
                onChange={(e) => setNewInput(e.target.value)}
                placeholder="0.80"
                data-testid="pricing-new-input"
                className="w-28 bg-neutral-800 border border-neutral-700 rounded px-2 py-1 text-xs outline-none focus:border-neutral-500"
              />
            </td>
            <td className="px-4 py-2">
              <input
                type="text"
                inputMode="decimal"
                value={newOutput}
                onChange={(e) => setNewOutput(e.target.value)}
                placeholder="4.00"
                data-testid="pricing-new-output"
                className="w-28 bg-neutral-800 border border-neutral-700 rounded px-2 py-1 text-xs outline-none focus:border-neutral-500"
              />
            </td>
            <td className="px-4 py-2 text-right">
              <button
                type="button"
                onClick={addRow}
                disabled={!newId.trim()}
                data-testid="pricing-add"
                className="text-xs text-blue-400 hover:text-blue-300 disabled:opacity-40 disabled:cursor-not-allowed"
              >
                + Add row
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  )
}
