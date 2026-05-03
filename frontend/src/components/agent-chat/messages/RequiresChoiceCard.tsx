import { useState } from 'react'
import { cn } from '../../../utils/cn'
import { useAgentStream } from '../hooks/use-agent-stream'

// ─── RequiresChoiceCard ────────────────────────────────────────────────────
//
// HITL prompt for ambiguous decisions (spec §6.5: "Create draft / Edit live
// / Use existing draft"). Each option is rendered as a card; clicking sends
// `POST /sessions/{id}/respond` via stream.respond(tool_call_id, choice_id).
//
// Once the user has chosen, the card collapses to a single confirmation row
// — the next stream event (e.g. `applied_change` or another `tool_call`)
// will continue the conversation underneath.

interface ChoiceOption {
  id: string
  label: string
  description?: string
}

interface RequiresChoiceCardProps {
  kind: string
  message: string
  options: ChoiceOption[]
  tool_call_id: string
}

export function RequiresChoiceCard({
  kind,
  message,
  options,
  tool_call_id,
}: RequiresChoiceCardProps) {
  const stream = useAgentStream()
  const [busy, setBusy] = useState(false)
  const [selected, setSelected] = useState<string | null>(null)

  const handleSelect = async (optionId: string) => {
    if (busy) return
    setBusy(true)
    setSelected(optionId)
    try {
      await stream.respond(tool_call_id, optionId)
    } catch {
      // On error, allow re-selection.
      setSelected(null)
    } finally {
      setBusy(false)
    }
  }

  if (selected) {
    const choice = options.find((o) => o.id === selected)
    return (
      <div
        data-testid="requires-choice-card"
        data-resolved-choice={selected}
        className={cn(
          'flex items-center gap-2 px-3 py-2 rounded-lg',
          'bg-surface border border-border-base',
          'text-[12px] text-text-2',
        )}
      >
        <span className="text-emerald-400" aria-hidden="true">
          ✓
        </span>
        <span>
          You chose <span className="text-text-base font-medium">{choice?.label ?? selected}</span>
        </span>
      </div>
    )
  }

  return (
    <div
      data-testid="requires-choice-card"
      data-kind={kind}
      className={cn(
        'flex flex-col gap-2 px-3 py-2 rounded-lg',
        'bg-surface border border-amber-500/40',
      )}
    >
      <div className="flex items-start gap-2">
        <span aria-hidden="true" className="mt-0.5">
          🤔
        </span>
        <div className="flex-1 text-[12px] text-text-base leading-snug">{message}</div>
      </div>
      <div className="grid gap-1.5">
        {options.map((opt) => (
          <button
            key={opt.id}
            type="button"
            disabled={busy}
            onClick={() => handleSelect(opt.id)}
            data-testid={`requires-choice-option-${opt.id}`}
            className={cn(
              'flex flex-col items-start gap-0.5 px-3 py-2 rounded-md text-left',
              'bg-panel border border-border-base',
              'hover:border-coral/50 hover:bg-surface-hi',
              'transition-colors duration-100',
              'focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-coral/50',
              'disabled:opacity-50 disabled:cursor-not-allowed',
            )}
          >
            <span className="text-[12px] font-medium text-text-base">{opt.label}</span>
            {opt.description && (
              <span className="text-[11px] text-text-3">{opt.description}</span>
            )}
          </button>
        ))}
      </div>
    </div>
  )
}
