import { Icon } from '@iconify/react'
import { cn } from '../../utils/cn'
import type { Technology } from '../../types/model'

export interface TechIconProps {
  /** Technology row from the catalog. When omitted, renders a neutral fallback. */
  technology?: Technology | null
  /** When you only have an Iconify name handy (e.g. picker preview). */
  iconifyName?: string
  size?: number
  className?: string
  /** Tint the background with the brand colour glow. Used by badge variants. */
  glow?: boolean
}

const FALLBACK = 'mdi:shape-outline'

/**
 * Thin wrapper around @iconify/react with an ArchFlow-friendly fallback.
 * Iconify lazy-loads the SVG from its CDN the first time a name is seen.
 */
export function TechIcon({
  technology,
  iconifyName,
  size = 16,
  className,
  glow = false,
}: TechIconProps) {
  const name = technology?.iconify_name || iconifyName || FALLBACK
  const color = technology?.color ?? undefined

  const label = technology?.name
  return (
    <span
      className={cn(
        'inline-flex items-center justify-center flex-shrink-0 rounded-[4px]',
        glow ? 'p-[3px]' : '',
        className,
      )}
      style={{
        width: glow ? size + 6 : size,
        height: glow ? size + 6 : size,
        background: glow && color ? `${color}1f` : undefined,
      }}
      title={label}
      aria-label={label}
    >
      <Icon icon={name} width={size} height={size} />
    </span>
  )
}
