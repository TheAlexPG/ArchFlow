import { ArchflowLink } from './ArchflowLink'
import type { ArchflowLinkTarget } from '../../../lib/archflow-link'
import { cn } from '../../../utils/cn'

// ─── AppliedChangePill ──────────────────────────────────────────────────────
//
// Compact "✓ Created Service Foo" badge with an inline ArchflowLink to the
// affected entity. Server payload (spec §3.7):
//   { action: 'create' | 'update' | 'delete' | ..., target_type, target_id, name }

interface AppliedChangePillProps {
  action: string
  target_type: string
  target_id: string
  name?: string
}

const ACTION_VERBS: Record<string, string> = {
  create: 'Created',
  created: 'Created',
  update: 'Updated',
  updated: 'Updated',
  delete: 'Deleted',
  deleted: 'Deleted',
  move: 'Moved',
  moved: 'Moved',
  rename: 'Renamed',
  renamed: 'Renamed',
}

export function AppliedChangePill({ action, target_type, target_id, name }: AppliedChangePillProps) {
  const verb = ACTION_VERBS[action.toLowerCase()] ?? capitalize(action)
  const target = toArchflowTarget(target_type)
  const label = name ?? target_id

  return (
    <div
      data-testid="applied-change-pill"
      data-action={action}
      className={cn(
        'inline-flex items-center gap-1.5 px-2 py-1 rounded-md',
        'bg-emerald-500/10 border border-emerald-500/30',
        'text-[11px] text-emerald-300',
        'self-start',
      )}
    >
      <span aria-hidden="true">✓</span>
      <span>
        {verb} <span className="text-text-2">{target_type}</span>
      </span>
      {target ? (
        <ArchflowLink target={target} id={target_id}>
          {label}
        </ArchflowLink>
      ) : (
        <span className="font-mono text-text-base">{label}</span>
      )}
    </div>
  )
}

function capitalize(s: string): string {
  return s.length > 0 ? s[0].toUpperCase() + s.slice(1) : s
}

/** Map a tool target_type to an ArchflowLink target. Unknown types become null
 *  so the pill falls back to plain text instead of rendering a broken link. */
function toArchflowTarget(target_type: string): ArchflowLinkTarget | null {
  const lower = target_type.toLowerCase()
  if (lower === 'object' || lower.endsWith('_object')) return 'object'
  if (lower === 'diagram' || lower.endsWith('_diagram')) return 'diagram'
  if (lower === 'connection' || lower === 'edge') return 'connection'
  return null
}
