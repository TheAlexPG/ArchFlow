import { cn } from '../../utils/cn'
import type { Technology } from '../../types/model'
import { TechIcon } from './TechIcon'

export interface TechBadgeProps {
  technology: Technology
  /** Hide the display name — useful for canvas badges where space is tight. */
  iconOnly?: boolean
  /** Render a compact dismiss (×) button; fires onRemove when clicked. */
  onRemove?: () => void
  className?: string
  size?: 'sm' | 'md'
}

/**
 * Pill-styled chip showing a technology. Pairs with `TechIcon` and matches the
 * `Pill` primitive's height + typography so a row of badges sits comfortably
 * alongside other pills in the sidebars.
 */
export function TechBadge({
  technology,
  iconOnly = false,
  onRemove,
  className,
  size = 'sm',
}: TechBadgeProps) {
  const iconPx = size === 'sm' ? 13 : 16
  const padY = size === 'sm' ? 'py-[2px]' : 'py-1'

  return (
    <span
      className={cn(
        'inline-flex items-center gap-[5px] px-[6px]',
        padY,
        'border border-border-base rounded-md bg-surface',
        'font-mono text-[10.5px] text-text-2',
        'leading-none',
        className,
      )}
      title={technology.name}
    >
      <TechIcon technology={technology} size={iconPx} />
      {!iconOnly && <span className="truncate max-w-[140px]">{technology.name}</span>}
      {onRemove && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation()
            onRemove()
          }}
          className="text-text-4 hover:text-text-base transition-colors -mr-1 ml-[2px]"
          aria-label={`Remove ${technology.name}`}
        >
          ×
        </button>
      )}
    </span>
  )
}

/** Render-or-skip helper — handy for table cells where `tech` might be undefined. */
export function TechBadgeFromId({
  technologyId,
  catalog,
  ...props
}: { technologyId: string | null; catalog: Technology[] } & Omit<
  TechBadgeProps,
  'technology'
>) {
  if (!technologyId) return null
  const tech = catalog.find((t) => t.id === technologyId)
  if (!tech) return null
  return <TechBadge technology={tech} {...props} />
}
