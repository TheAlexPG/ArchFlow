import { cn } from '../../utils/cn'
import { StatusPill } from '../ui/Pill'
import type { PillVariant } from '../ui/Pill'

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
}

// ─── Canvas thumbnail SVG ────────────────────────────────────────────────────

function CanvasThumbnail() {
  return (
    <svg
      width="100%"
      height="100%"
      viewBox="0 0 200 90"
      preserveAspectRatio="xMidYMid meet"
      className="opacity-40"
      aria-hidden="true"
    >
      {/* Dotted grid pattern */}
      <defs>
        <pattern id="card-dots" x="0" y="0" width="16" height="16" patternUnits="userSpaceOnUse">
          <circle cx="0.5" cy="0.5" r="0.5" fill="#26262c"/>
        </pattern>
      </defs>
      <rect width="200" height="90" fill="url(#card-dots)"/>
      {/* Faint node rects */}
      <rect x="20" y="20" width="60" height="30" rx="3" stroke="#35353d" strokeWidth="1" fill="#16161a"/>
      <rect x="110" y="15" width="70" height="25" rx="3" stroke="#35353d" strokeWidth="1" fill="#16161a"/>
      <rect x="60" y="55" width="80" height="22" rx="3" stroke="#35353d" strokeWidth="1" fill="#16161a"/>
      {/* Faint lines */}
      <line x1="80" y1="35" x2="110" y2="28" stroke="#26262c" strokeWidth="1"/>
      <line x1="100" y1="45" x2="100" y2="55" stroke="#26262c" strokeWidth="1"/>
    </svg>
  )
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
        <CanvasThumbnail />
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
