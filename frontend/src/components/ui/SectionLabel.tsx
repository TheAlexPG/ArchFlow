import { cn } from '../../utils/cn'

// ─── Types ─────────────────────────────────────────────────────────────────

export interface SectionLabelProps {
  counter?: string | number
  className?: string
  children?: React.ReactNode
}

// ─── SectionLabel ──────────────────────────────────────────────────────────

export function SectionLabel({ counter, className, children }: SectionLabelProps) {
  return (
    <div
      className={cn(
        'flex items-center justify-between',
        className,
      )}
    >
      <span
        className={cn(
          'font-mono text-[10.5px] uppercase tracking-[0.08em] text-text-3',
        )}
      >
        {children}
      </span>
      {counter !== undefined && (
        <span className="font-mono text-[10.5px] text-text-4">
          {counter}
        </span>
      )}
    </div>
  )
}
