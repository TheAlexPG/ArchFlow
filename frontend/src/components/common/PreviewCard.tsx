import { cn } from '../../utils/cn'
import { StatusPill } from '../ui/Pill'
import type { PillVariant } from '../ui/Pill'
import { DiagramPreviewSvg } from './DiagramPreviewSvg'

// ─── Types ──────────────────────────────────────────────────────────────────

export interface PreviewCardProps {
  name: string
  typeLabel: string
  slug?: string
  updatedLabel?: string
  status?: Exclude<PillVariant, 'neutral'>
  isModified?: boolean
  onClick?: () => void
  className?: string
  /** Diagram id — when provided, the thumbnail renders the actual diagram
   *  nodes + connections (gated by IntersectionObserver). Without it we fall
   *  back to the pre-baked motif keyed by `diagramType`. */
  diagramId?: string
  /** C4 diagram type — used for the fallback motif while real data loads and
   *  for empty diagrams. Accepted as a plain string since some callers (the
   *  useDiagrams hook in particular) type it as `string` rather than the
   *  narrow `DiagramType` literal. */
  diagramType?: string
  /** Optional draft id, forwarded to the real-preview object/connection hooks
   *  so draft-only diagrams show their fork pool. */
  draftId?: string | null
}

// ─── PreviewCard ─────────────────────────────────────────────────────────────

export function PreviewCard({
  name,
  typeLabel,
  slug,
  updatedLabel,
  status,
  isModified,
  onClick,
  className,
  diagramId,
  diagramType,
  draftId,
}: PreviewCardProps) {
  return (
    <div
      onClick={onClick}
      className={cn(
        'bg-panel border border-border-base rounded-lg overflow-hidden',
        'hover:border-border-hi cursor-pointer transition-all duration-[120ms]',
        'flex flex-col',
        className,
      )}
    >
      {/* Thumbnail */}
      <div className="h-[90px] bg-bg border-b border-border-base flex items-center justify-center overflow-hidden">
        <DiagramPreviewSvg
          diagramId={diagramId}
          fallbackType={diagramType}
          draftId={draftId ?? null}
          className="opacity-80"
        />
      </div>

      {/* Footer */}
      <div className="p-3 flex flex-col gap-1.5">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="text-[13px] font-medium text-text-base truncate">
              {name}
              {isModified && (
                <span className="font-mono text-[10px] text-text-3 ml-1.5">(modified)</span>
              )}
            </div>
            {slug && (
              <div className="font-mono text-[10.5px] text-text-3 truncate mt-0.5">{slug}</div>
            )}
          </div>
          {status && <StatusPill status={status} className="flex-shrink-0">{status.toUpperCase()}</StatusPill>}
        </div>
        <div className="flex items-center justify-between">
          <span className="text-[11px] text-text-3">{typeLabel}</span>
          {updatedLabel && (
            <span className="font-mono text-[10.5px] text-text-3">{updatedLabel}</span>
          )}
        </div>
      </div>
    </div>
  )
}
