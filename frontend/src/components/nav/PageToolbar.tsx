import { useState } from 'react'
import { Button } from '../ui/Button'
import { Kbd } from '../ui/Kbd'
import { SearchModal } from './SearchModal'

// ─── Types ──────────────────────────────────────────────────────────────────

export interface PageToolbarProps {
  /** e.g. ['alex / personal', 'Overview'] — last element rendered bold/light */
  breadcrumb?: string[]
  /** Optional h2 title rendered below the breadcrumb row */
  title?: string
  /** Optional subtitle rendered beneath the title (12.5px, text-text-2) */
  subtitle?: string
  /** Right-side slot for action buttons */
  actions?: React.ReactNode
}

// ─── Chevron SVG ────────────────────────────────────────────────────────────

function ChevronRight() {
  return (
    <svg
      width="10"
      height="10"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      className="text-text-4 flex-shrink-0"
      aria-hidden="true"
    >
      <path d="m9 18 6-6-6-6"/>
    </svg>
  )
}

// ─── SearchButton ────────────────────────────────────────────────────────────
/**
 * Convenience helper — renders the "Search ⌘K" button and owns the
 * SearchModal state. Pass an `onClick` to override (e.g. to lift state up).
 */
export function SearchButton({ onClick }: { onClick?: () => void }) {
  const [localOpen, setLocalOpen] = useState(false)

  const open = onClick ? undefined : localOpen
  const toggle = onClick ?? (() => setLocalOpen((v) => !v))
  const close = onClick ? () => {} : () => setLocalOpen(false)

  return (
    <>
      <Button
        onClick={toggle}
        leftIcon={
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="11" cy="11" r="8"/>
            <path d="m21 21-4.35-4.35"/>
          </svg>
        }
        rightIcon={<Kbd>⌘K</Kbd>}
      >
        Search
      </Button>
      {/* Only render our own modal if onClick is not provided (uncontrolled mode) */}
      {onClick == null && (
        <SearchModal open={open!} onClose={close} />
      )}
    </>
  )
}

// ─── PageToolbar ─────────────────────────────────────────────────────────────

export function PageToolbar({
  breadcrumb = [],
  title,
  subtitle,
  actions,
}: PageToolbarProps) {
  return (
    <div className="px-8 py-4 border-b border-border-base flex items-start justify-between gap-4 flex-shrink-0">
      {/* Left: breadcrumb + optional title/subtitle */}
      <div>
        {breadcrumb.length > 0 && (
          <div className="flex items-center gap-1.5 flex-wrap">
            {breadcrumb.map((crumb, i) => {
              const isLast = i === breadcrumb.length - 1
              return (
                <span key={i} className="flex items-center gap-1.5">
                  {i > 0 && <ChevronRight />}
                  <span
                    className={
                      isLast
                        ? 'text-[13px] font-medium text-text-base'
                        : 'font-mono text-[11px] text-text-3'
                    }
                  >
                    {crumb}
                  </span>
                </span>
              )
            })}
          </div>
        )}
        {title && (
          <h2 className="text-[22px] font-semibold tracking-tight text-text-base mt-1">
            {title}
          </h2>
        )}
        {subtitle && (
          <p className="text-[12.5px] text-text-2 mt-0.5">{subtitle}</p>
        )}
      </div>

      {/* Right: actions slot */}
      {actions && (
        <div className="flex items-center gap-2 flex-shrink-0 self-center">
          {actions}
        </div>
      )}
    </div>
  )
}
