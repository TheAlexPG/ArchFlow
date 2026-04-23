import { cn } from '../../utils/cn'

// ─── Types ─────────────────────────────────────────────────────────────────

export interface KbdProps {
  className?: string
  children?: React.ReactNode
}

// ─── Kbd ───────────────────────────────────────────────────────────────────

export function Kbd({ className, children }: KbdProps) {
  return (
    <kbd
      className={cn(
        'inline-flex items-center justify-center',
        'font-mono text-[10.5px]',
        'px-1.5 py-0.5',
        'bg-surface border border-border-base rounded',
        'text-text-3',
        className,
      )}
    >
      {children}
    </kbd>
  )
}
