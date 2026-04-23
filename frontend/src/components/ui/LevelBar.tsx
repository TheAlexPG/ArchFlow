import { cn } from '../../utils/cn'

// ─── Types ─────────────────────────────────────────────────────────────────

export interface LevelBarProps {
  level: 1 | 2 | 3 | 4
  className?: string
}

// ─── LevelBar ──────────────────────────────────────────────────────────────

export function LevelBar({ level, className }: LevelBarProps) {
  return (
    <span
      className={cn('inline-flex gap-[2px] items-center', className)}
      aria-label={`Level ${level} of 4`}
    >
      {([1, 2, 3, 4] as const).map((n) => (
        <i
          key={n}
          className={cn(
            'not-italic block w-[3px] h-[10px] rounded-[1px]',
            n <= level ? 'bg-coral' : 'bg-border-base',
          )}
        />
      ))}
    </span>
  )
}
