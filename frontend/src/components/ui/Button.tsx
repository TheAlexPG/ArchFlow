import { forwardRef } from 'react'
import { cn } from '../../utils/cn'

// ─── Types ─────────────────────────────────────────────────────────────────

export type ButtonVariant = 'default' | 'primary' | 'ghost'
export type ButtonSize = 'default' | 'sm' | 'icon'

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: ButtonSize
  leftIcon?: React.ReactNode
  rightIcon?: React.ReactNode
}

// ─── Variant maps ──────────────────────────────────────────────────────────

const variantClasses: Record<ButtonVariant, string> = {
  default:
    'bg-surface border-border-base text-text-2 ' +
    'hover:text-text-base hover:border-border-hi hover:bg-surface-hi',
  primary:
    'bg-coral border-coral text-bg font-medium ' +
    'hover:bg-coral-2 hover:border-coral-2',
  ghost:
    'bg-transparent border-transparent text-text-2 ' +
    'hover:bg-surface hover:border-border-base',
}

const sizeClasses: Record<ButtonSize, string> = {
  default: 'px-3 py-1.5 text-[12.5px]',
  sm:      'px-2 py-1 text-[11.5px]',
  icon:    'p-1 text-[12.5px]',
}

// ─── Button ────────────────────────────────────────────────────────────────

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'default', size = 'default', leftIcon, rightIcon, className, children, ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      className={cn(
        'inline-flex items-center gap-[6px]',
        'border rounded-md',
        'font-mono',
        'transition-all duration-[120ms] ease-[ease]',
        'cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed',
        'focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-coral/50',
        variantClasses[variant],
        sizeClasses[size],
        className,
      )}
      {...props}
    >
      {leftIcon && <span className="flex-shrink-0">{leftIcon}</span>}
      {children}
      {rightIcon && <span className="flex-shrink-0">{rightIcon}</span>}
    </button>
  )
})
