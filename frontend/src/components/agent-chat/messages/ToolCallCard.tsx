import { useState } from 'react'
import { cn } from '../../../utils/cn'
import { useAgentStream } from '../hooks/use-agent-stream'

// ─── ToolCallCard ───────────────────────────────────────────────────────────
//
// Collapsed by default: status icon + tool name + short preview line.
// Expanded: pretty-printed args + result content.
//
// HITL: when status === 'awaiting_confirmation', render inline [Approve]
// [Cancel] buttons. Approve calls stream.respond(id, 'confirm'); Cancel
// calls stream.respond(id, 'cancel'). The buttons disable themselves while
// the request is in-flight to prevent double-submits.

export type ToolStatus = 'pending' | 'ok' | 'error' | 'denied' | 'awaiting_confirmation'

const STATUS_META: Record<ToolStatus, { icon: string; label: string; tone: string }> = {
  pending: { icon: '', label: 'Running', tone: 'text-coral' },
  ok: { icon: '✓', label: 'Done', tone: 'text-emerald-400' },
  error: { icon: '✗', label: 'Error', tone: 'text-red-400' },
  denied: { icon: '⛔', label: 'Denied', tone: 'text-red-400' },
  awaiting_confirmation: { icon: '⏸', label: 'Awaiting confirmation', tone: 'text-amber-400' },
}

// Spinner SVG used for the running state — animated via Tailwind
// ``animate-spin`` so the tool card visibly pulses while the call is
// in flight (replaces the static "⏳" emoji).
function ToolSpinner() {
  return (
    <svg
      className="w-3.5 h-3.5 animate-spin text-coral"
      viewBox="0 0 24 24"
      aria-hidden
    >
      <circle
        cx="12"
        cy="12"
        r="9"
        stroke="currentColor"
        strokeOpacity="0.25"
        strokeWidth="3"
        fill="none"
      />
      <path
        d="M21 12a9 9 0 0 0-9-9"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
        fill="none"
      />
    </svg>
  )
}

interface ToolCallCardProps {
  id: string
  name: string
  args: unknown
  status: ToolStatus
  preview?: string
  result?: unknown
}

export function ToolCallCard({ id, name, args, status, preview, result }: ToolCallCardProps) {
  const [expanded, setExpanded] = useState(false)
  const meta = STATUS_META[status]

  const isPending = status === 'pending'

  return (
    <div
      data-testid="tool-call-card"
      data-tool-status={status}
      className={cn(
        'rounded-lg border bg-surface text-[12px] overflow-hidden',
        status === 'error' || status === 'denied' ? 'border-red-500/40' : 'border-border-base',
        status === 'awaiting_confirmation' && 'border-amber-500/40',
        // Subtle outer ring while running so the card itself signals activity.
        isPending && 'border-coral/40 shadow-[0_0_0_1px_var(--color-coral-glow)]',
      )}
    >
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        data-testid="tool-call-card-toggle"
        className={cn(
          'w-full flex items-center gap-2 px-3 py-2 text-left',
          'hover:bg-surface-hi transition-colors duration-100',
          'focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-coral/50',
        )}
        aria-expanded={expanded}
      >
        <span
          className={cn('inline-flex items-center justify-center w-4 h-4', meta.tone)}
          aria-label={meta.label}
        >
          {isPending ? <ToolSpinner /> : <span className="text-[13px]">{meta.icon}</span>}
        </span>
        <span className={cn('font-mono', isPending ? 'text-coral' : 'text-text-base')}>
          {name}
        </span>
        {preview && (
          <span className="text-text-3 truncate flex-1" data-testid="tool-call-card-preview">
            {preview}
          </span>
        )}
        {isPending && !preview && (
          <span className="text-text-3 truncate flex-1 flex items-center gap-1">
            <span className="inline-block w-1 h-1 rounded-full bg-coral animate-pulse" />
            <span className="inline-block w-1 h-1 rounded-full bg-coral animate-pulse [animation-delay:120ms]" />
            <span className="inline-block w-1 h-1 rounded-full bg-coral animate-pulse [animation-delay:240ms]" />
          </span>
        )}
        <span className="text-text-4 text-[11px]">{expanded ? '▾' : '▸'}</span>
      </button>

      {expanded && (
        <div className="border-t border-border-base px-3 py-2 space-y-2" data-testid="tool-call-card-body">
          <Section title="args">
            <pre className="text-[11px] font-mono text-text-2 whitespace-pre-wrap break-words">
              {prettyJson(args)}
            </pre>
          </Section>
          {result !== undefined && (
            <Section title="result">
              <pre className="text-[11px] font-mono text-text-2 whitespace-pre-wrap break-words">
                {typeof result === 'string' ? result : prettyJson(result)}
              </pre>
            </Section>
          )}
        </div>
      )}

      {status === 'awaiting_confirmation' && <HitlControls toolCallId={id} />}
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-text-4 mb-1">{title}</div>
      {children}
    </div>
  )
}

function prettyJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

// ─── HitlControls ──────────────────────────────────────────────────────────
//
// Approve / Cancel buttons for awaiting_confirmation tool calls. We
// disable both while a respond() is in flight so the user can't fire
// confirm + cancel simultaneously.

function HitlControls({ toolCallId }: { toolCallId: string }) {
  const stream = useAgentStream()
  const [busy, setBusy] = useState(false)

  const handle = async (choiceId: 'confirm' | 'cancel') => {
    if (busy) return
    setBusy(true)
    try {
      await stream.respond(toolCallId, choiceId)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="border-t border-border-base px-3 py-2 flex items-center gap-2">
      <button
        type="button"
        disabled={busy}
        onClick={() => handle('confirm')}
        data-testid="tool-call-card-approve"
        className={cn(
          'px-2.5 py-1 rounded text-[11px] font-medium',
          'bg-emerald-500/15 text-emerald-300 border border-emerald-500/30',
          'hover:bg-emerald-500/25 transition-colors duration-100',
          'disabled:opacity-50 disabled:cursor-not-allowed',
        )}
      >
        Approve
      </button>
      <button
        type="button"
        disabled={busy}
        onClick={() => handle('cancel')}
        data-testid="tool-call-card-cancel"
        className={cn(
          'px-2.5 py-1 rounded text-[11px] font-medium',
          'bg-surface-hi text-text-2 border border-border-base',
          'hover:bg-surface transition-colors duration-100',
          'disabled:opacity-50 disabled:cursor-not-allowed',
        )}
      >
        Cancel
      </button>
    </div>
  )
}
