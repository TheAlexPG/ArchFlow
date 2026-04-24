import { cn } from '../../utils/cn'

// ─── Types ─────────────────────────────────────────────────────────────────

export type PillVariant =
  | 'neutral'
  | 'done'
  | 'review'
  | 'processing'
  | 'input'
  | 'draft'
  | 'ai'

export interface PillDotProps {
  color: string
  className?: string
}

export interface PillProps {
  variant?: PillVariant
  dotColor?: string
  className?: string
  children?: React.ReactNode
}

// ─── Variant maps ──────────────────────────────────────────────────────────

const variantClasses: Record<PillVariant, string> = {
  neutral:    'bg-surface border-border-base text-text-2',
  done:       'bg-accent-green-glow border-accent-green/30 text-accent-green',
  review:     'bg-accent-purple-glow border-accent-purple/30 text-accent-purple',
  processing: 'bg-accent-blue-glow border-accent-blue/30 text-accent-blue',
  input:      'bg-accent-amber-glow border-accent-amber/30 text-accent-amber',
  draft:      'bg-coral-glow border-coral/35 text-coral',
  ai:         'bg-accent-pink-glow border-accent-pink/30 text-accent-pink',
}

const variantDotColors: Record<PillVariant, string> = {
  neutral:    'bg-text-3',
  done:       'bg-accent-green',
  review:     'bg-accent-purple',
  processing: 'bg-accent-blue',
  input:      'bg-accent-amber',
  draft:      'bg-coral',
  ai:         'bg-accent-pink',
}

// ─── PillDot ───────────────────────────────────────────────────────────────

export function PillDot({ color, className }: PillDotProps) {
  return (
    <span
      className={cn('inline-block w-[6px] h-[6px] rounded-full flex-shrink-0', className)}
      style={{ backgroundColor: color }}
    />
  )
}

// ─── Pill ──────────────────────────────────────────────────────────────────

export function Pill({ variant = 'neutral', dotColor, className, children }: PillProps) {
  const variantCls = variantClasses[variant]

  return (
    <span
      className={cn(
        'inline-flex items-center gap-[6px]',
        'px-2 py-[3px]',
        'border rounded-md',
        'font-mono text-[10.5px] tracking-[0.02em]',
        variantCls,
        className,
      )}
    >
      {dotColor && <PillDot color={dotColor} />}
      {!dotColor && variant !== 'neutral' && (
        <span
          className={cn(
            'inline-block w-[6px] h-[6px] rounded-full flex-shrink-0',
            variantDotColors[variant],
          )}
        />
      )}
      {children}
    </span>
  )
}

// ─── StatusPill convenience wrapper ────────────────────────────────────────

export interface StatusPillProps extends Omit<PillProps, 'variant'> {
  status: Exclude<PillVariant, 'neutral'>
}

export function StatusPill({ status, ...rest }: StatusPillProps) {
  return <Pill variant={status} {...rest} />
}
