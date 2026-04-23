import { cn } from '../../utils/cn'

// ─── Types ─────────────────────────────────────────────────────────────────

export type PulseColor = 'green' | 'coral' | 'blue'

export interface PulseProps {
  color?: PulseColor
  className?: string
}

// ─── Color maps ────────────────────────────────────────────────────────────

const colorClasses: Record<PulseColor, string> = {
  green: 'bg-accent-green',
  coral: 'bg-coral',
  blue:  'bg-accent-blue',
}

// ─── Pulse ─────────────────────────────────────────────────────────────────

export function Pulse({ color = 'green', className }: PulseProps) {
  return (
    <span
      className={cn(
        'inline-block w-2 h-2 rounded-full flex-shrink-0',
        'animate-pulse-dot',
        colorClasses[color],
        className,
      )}
    />
  )
}
