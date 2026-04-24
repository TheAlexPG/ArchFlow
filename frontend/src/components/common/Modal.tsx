import { useEffect, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

interface ModalProps {
  open: boolean
  onClose: () => void
  title: string
  children: ReactNode
  /** Rendered in the footer strip. Put action buttons here. */
  footer?: ReactNode
  width?: number
}

/** Minimal modal — dim backdrop, dark card, ESC to close. */
export function Modal({ open, onClose, title, children, footer, width = 440 }: ModalProps) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null
  // Portal to body so ancestor CSS `transform` (e.g. the canvas-left
  // FAB wrapper) can't break our `position: fixed; inset: 0` centring.
  return createPortal(
    <div
      onClick={onClose}
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 100,
        background: 'rgba(0, 0, 0, 0.65)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        backdropFilter: 'blur(3px)',
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width,
          background: '#171717',
          border: '1px solid #333',
          borderRadius: 10,
          boxShadow: '0 16px 48px rgba(0,0,0,0.6)',
          color: '#e5e5e5',
          display: 'flex',
          flexDirection: 'column',
          maxHeight: '85vh',
        }}
      >
        <div
          style={{
            padding: '14px 18px',
            borderBottom: '1px solid #262626',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <div style={{ fontSize: 14, fontWeight: 600 }}>{title}</div>
          <button
            onClick={onClose}
            style={{
              background: 'none',
              border: 'none',
              color: '#737373',
              cursor: 'pointer',
              fontSize: 18,
              lineHeight: 1,
            }}
            aria-label="Close"
          >
            ×
          </button>
        </div>
        <div style={{ padding: '18px', overflowY: 'auto' }}>{children}</div>
        {footer && (
          <div
            style={{
              padding: '12px 18px',
              borderTop: '1px solid #262626',
              display: 'flex',
              justifyContent: 'flex-end',
              gap: 8,
            }}
          >
            {footer}
          </div>
        )}
      </div>
    </div>,
    document.body,
  )
}
