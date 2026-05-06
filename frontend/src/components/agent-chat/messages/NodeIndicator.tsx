import { useEffect, useRef, useState } from 'react'
import { cn } from '../../../utils/cn'

// ─── NodeIndicator ──────────────────────────────────────────────────────────
//
// Animated pill marking a graph-node entry — surfaced while an agent /
// sub-agent is running so the user sees "something is happening" between
// tool calls. Maps the raw LangGraph node name to a human label + emoji.
// Unknown nodes fall through to a neutral badge.
//
// Motion budget: one focal element. We previously stacked an
// animate-ping ring, an outer coral-glow shadow, and three pulsing dots
// — three competing motions that read as noise. The badge now uses a
// single ~1.6s coral-glow heartbeat plus a single coral status dot that
// breathes in lockstep. After ~2.4s without remount we drop the
// heartbeat to a calm steady glow so a stale node indicator doesn't
// keep nagging while the agent is busy elsewhere.
//
// Optional ``tools`` prop renders a row of small wrench icons to the
// right of the badge, one per tool the agent called inside this node
// run. Clicking the row opens a small dropdown listing the tool names
// (with truncated args preview) so the user can audit the agent's
// activity without scrolling through individual ToolCallCards.

const NODE_LABELS: Record<string, { emoji: string; label: string }> = {
  supervisor: { emoji: '🧭', label: 'Orchestrating' },
  planner: { emoji: '🧠', label: 'Planning' },
  plan: { emoji: '🧠', label: 'Planning' },
  reason: { emoji: '🧠', label: 'Reasoning' },
  act: { emoji: '🛠', label: 'Acting' },
  tool: { emoji: '🛠', label: 'Calling tool' },
  observe: { emoji: '👁', label: 'Observing' },
  research: { emoji: '🔍', label: 'Researching' },
  researcher: { emoji: '🔍', label: 'Researching' },
  diagram: { emoji: '🗺', label: 'Editing diagram' },
  critic: { emoji: '🧐', label: 'Reviewing' },
  explain: { emoji: '💬', label: 'Explaining' },
  explainer: { emoji: '💬', label: 'Explaining' },
  compact: { emoji: '📦', label: 'Compacting' },
  finalize: { emoji: '✓', label: 'Finalizing' },
}

export interface NodeToolEntry {
  /** Stable id from the SSE ``tool_call`` event — used as a React key. */
  id: string
  /** Tool name as reported by the runtime (e.g. ``read_diagram``). */
  name: string
  /** Raw args object/dict — rendered as a one-line preview in the popover. */
  args?: unknown
  /** ``ok`` / ``error`` / ``denied`` / ``pending`` — drives icon tint. */
  status?: string
}

interface NodeIndicatorProps {
  node: string
  /** Tools called by the agent during this node run, in arrival order.
   *  When non-empty, renders an icon row + popover to the right of the
   *  badge. Omit / empty array → no tool affordance. */
  tools?: NodeToolEntry[]
}

export function NodeIndicator({ node, tools }: NodeIndicatorProps) {
  const meta = NODE_LABELS[node.toLowerCase()] ?? { emoji: '•', label: node }

  // Calm down after ~2.4s — assume the agent has moved on to another
  // node or a tool call by then, so a static glow is plenty.
  const [calmed, setCalmed] = useState(false)
  useEffect(() => {
    const t = window.setTimeout(() => setCalmed(true), 2400)
    return () => window.clearTimeout(t)
  }, [node])

  return (
    <div className="flex items-center gap-1.5" data-testid="node-indicator" data-calmed={calmed ? 'true' : 'false'}>
      <div
        className={cn(
          'relative inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full',
          'bg-surface border border-coral/40',
          'text-[11px] text-text-1 font-mono',
        )}
        style={{
          animation: calmed
            ? undefined
            : 'archflow-node-glow 1.6s cubic-bezier(0.16, 1, 0.3, 1) infinite',
          boxShadow: calmed ? '0 0 0 1px var(--color-coral-glow)' : undefined,
        }}
      >
        <span
          aria-hidden
          className={cn(
            'inline-block w-1.5 h-1.5 rounded-full bg-coral',
            !calmed && 'shadow-[0_0_6px_var(--color-coral)]',
          )}
          style={
            calmed
              ? undefined
              : { animation: 'archflow-heartbeat 1.6s cubic-bezier(0.16, 1, 0.3, 1) infinite' }
          }
        />
        <span aria-hidden="true">{meta.emoji}</span>
        <span>{meta.label}</span>
      </div>
      {tools && tools.length > 0 && <NodeToolBadges tools={tools} />}
    </div>
  )
}

// ─── NodeToolBadges ─────────────────────────────────────────────────────────
//
// Compact icon row + click-to-open popover. One wrench icon per tool
// call the agent made under this node. We deliberately keep this inline
// (rather than a generic Popover primitive) because:
//   1. The project's UI primitive set doesn't ship a Popover yet.
//   2. SessionPicker.tsx already uses the same useState + click-outside
//      pattern — staying consistent avoids introducing a one-off API.
//
// The icon row is keyboard-focusable as a single button. The popover is
// a positioned absolute panel directly below it.

function NodeToolBadges({ tools }: { tools: NodeToolEntry[] }) {
  const [open, setOpen] = useState(false)
  const wrapRef = useRef<HTMLDivElement | null>(null)

  // Close when the user clicks anywhere outside the popover or the
  // trigger. Mirrors SessionPicker.tsx — keep the same pattern so future
  // maintainers don't have two click-outside flavors to reason about.
  useEffect(() => {
    if (!open) return
    function onMouseDown(e: MouseEvent) {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', onMouseDown)
    return () => document.removeEventListener('mousedown', onMouseDown)
  }, [open])

  // Cap visible icons so the row doesn't push the badge off-screen on a
  // chatty node (e.g. researcher with 8+ tool calls). We still list every
  // tool inside the popover.
  const MAX_ICONS = 5
  const visibleIcons = tools.slice(0, MAX_ICONS)
  const overflow = tools.length - visibleIcons.length

  return (
    <div className="relative" ref={wrapRef}>
      <button
        type="button"
        data-testid="node-tools-trigger"
        data-tool-count={tools.length}
        onClick={() => setOpen((v) => !v)}
        title={`${tools.length} tool ${tools.length === 1 ? 'call' : 'calls'}`}
        className={cn(
          'inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-full',
          'bg-surface border border-border-base',
          'text-text-3 hover:text-text-1 hover:border-coral/40',
          'transition-colors duration-100',
          'focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-coral/50',
        )}
        aria-expanded={open}
        aria-label={`${tools.length} tool ${tools.length === 1 ? 'call' : 'calls'}`}
      >
        {visibleIcons.map((t) => (
          <ToolIconDot key={t.id} status={t.status} />
        ))}
        {overflow > 0 && (
          <span className="text-[9px] font-mono text-text-3 ml-0.5">+{overflow}</span>
        )}
      </button>

      {open && (
        <div
          data-testid="node-tools-popover"
          role="dialog"
          className={cn(
            'absolute top-full left-0 mt-1 z-50',
            'min-w-[220px] max-w-[320px] rounded-md overflow-hidden',
            'bg-panel border border-border-base shadow-window',
            'py-1',
          )}
        >
          <div className="px-2.5 py-1.5 text-[10px] uppercase tracking-wide text-text-4 border-b border-border-base">
            Tools called
          </div>
          <ul className="max-h-[240px] overflow-y-auto py-1">
            {tools.map((t) => (
              <li
                key={t.id}
                data-testid="node-tools-item"
                className="px-2.5 py-1 flex flex-col gap-0.5 hover:bg-surface-hi"
              >
                <div className="flex items-center gap-1.5">
                  <ToolIconDot status={t.status} />
                  <span className="text-[11px] font-mono text-text-1 truncate">{t.name}</span>
                </div>
                {formatArgsPreview(t.args) && (
                  <div className="text-[10px] font-mono text-text-3 truncate pl-4">
                    {formatArgsPreview(t.args)}
                  </div>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

// Tiny wrench glyph for the icon row. Inline SVG so we don't pull in a
// new icon dependency — matches ToolCallCard's ad-hoc spinner pattern.
// Tinted by status: pending=coral, error/denied=red, ok/everything-else
// =default (text-2 → reads as "neutral").
function ToolIconDot({ status }: { status?: string }) {
  const tone = toneForStatus(status)
  return (
    <svg
      viewBox="0 0 24 24"
      className={cn('w-3 h-3 shrink-0', tone)}
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      {/* Wrench / spanner glyph — a recognisable "tool" without needing
          a separate icon library import. */}
      <path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.4-.6-.6-2.4 2.5-2.5z" />
    </svg>
  )
}

function toneForStatus(status: string | undefined): string {
  switch (status) {
    case 'pending':
    case undefined:
      return 'text-coral/80'
    case 'error':
    case 'failed':
    case 'denied':
    case 'forbidden':
      return 'text-red-400'
    case 'awaiting_confirmation':
    case 'requires_confirmation':
      return 'text-amber-400'
    default:
      return 'text-text-2'
  }
}

// One-line summary of the args dict — first 1-2 key=value pairs, capped
// at 60 chars. We deliberately don't pretty-print; the full args dump
// stays in <ToolCallCard> below the node row so the popover stays
// glanceable.
function formatArgsPreview(args: unknown): string {
  if (args == null) return ''
  if (typeof args === 'string') return truncate(args, 60)
  if (typeof args !== 'object') return truncate(String(args), 60)
  const entries = Object.entries(args as Record<string, unknown>)
  if (entries.length === 0) return ''
  const parts: string[] = []
  for (const [k, v] of entries.slice(0, 2)) {
    parts.push(`${k}=${formatScalar(v)}`)
  }
  return truncate(parts.join(', '), 60)
}

function formatScalar(v: unknown): string {
  if (v == null) return 'null'
  if (typeof v === 'string') return JSON.stringify(v)
  if (typeof v === 'number' || typeof v === 'boolean') return String(v)
  return '…'
}

function truncate(s: string, n: number): string {
  return s.length > n ? s.slice(0, n - 1) + '…' : s
}
