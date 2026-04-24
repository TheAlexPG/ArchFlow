import { cn } from '../../utils/cn'
import React from 'react'

// ─── Types ─────────────────────────────────────────────────────────────────

export type AvatarGradient =
  | 'coral-amber'
  | 'coral-purple'
  | 'blue-purple'
  | 'green-blue'

export type AvatarSize = 'xs' | 'sm' | 'md'

export interface AvatarProps {
  initials: string
  gradient?: AvatarGradient
  size?: AvatarSize
  className?: string
}

export interface AvatarStackProps {
  children?: React.ReactNode
  className?: string
}

// ─── Maps ──────────────────────────────────────────────────────────────────

const gradientClasses: Record<AvatarGradient, string> = {
  'coral-amber':  'from-coral to-accent-amber',
  'coral-purple': 'from-coral to-accent-purple',
  'blue-purple':  'from-accent-blue to-accent-purple',
  'green-blue':   'from-accent-green to-accent-blue',
}

const sizeClasses: Record<AvatarSize, { container: string; text: string }> = {
  xs: { container: 'w-5 h-5',  text: 'text-[9px]' },
  sm: { container: 'w-7 h-7',  text: 'text-[10px]' },
  md: { container: 'w-8 h-8',  text: 'text-[11px]' },
}

// ─── Avatar ────────────────────────────────────────────────────────────────

export function Avatar({
  initials,
  gradient = 'coral-amber',
  size = 'md',
  className,
}: AvatarProps) {
  const { container, text } = sizeClasses[size]
  const gradientCls = gradientClasses[gradient]

  return (
    <span
      className={cn(
        'inline-flex items-center justify-center rounded-full',
        'bg-gradient-to-br',
        'text-bg font-bold select-none flex-shrink-0',
        container,
        text,
        gradientCls,
        className,
      )}
      aria-label={`Avatar ${initials}`}
    >
      {initials.slice(0, 2).toUpperCase()}
    </span>
  )
}

// ─── AvatarStack ───────────────────────────────────────────────────────────

export function AvatarStack({ children, className }: AvatarStackProps) {
  return (
    <div
      className={cn(
        'flex items-center -space-x-1.5',
        className,
      )}
    >
      {React.Children.map(children, (child) => {
        if (!React.isValidElement(child)) return child
        // Ring on each child for separation on dark bg
        return React.cloneElement(child as React.ReactElement<{ className?: string }>, {
          className: cn(
            (child as React.ReactElement<{ className?: string }>).props.className,
            'ring-2 ring-panel',
          ),
        })
      })}
    </div>
  )
}
