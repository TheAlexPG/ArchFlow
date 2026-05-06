import { useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAgentStream } from './use-agent-stream'

// ─── Inline toast ────────────────────────────────────────────────────────────
//
// The project has no global toast library. We emit a native CustomEvent that
// the DraftCreatedBanner (and future listeners) can intercept.  For view_change
// we also drop a transient DOM notification rather than polluting the deps with
// a library install.
//
// Implementation: inject a small absolutely-positioned div into document.body
// for 3 s then remove it. Works in jsdom (tests just assert the event) without
// any extra setup.

function showViewChangeToast(message: string) {
  if (typeof document === 'undefined') return
  const el = document.createElement('div')
  el.setAttribute('data-testid', 'view-change-toast')
  el.setAttribute('role', 'status')
  el.setAttribute('aria-live', 'polite')
  el.style.cssText = [
    'position:fixed',
    'bottom:80px',
    'right:16px',
    'z-index:9999',
    'background:#1c1c1c',
    'border:1px solid #333',
    'color:#e5e5e5',
    'font-size:13px',
    'padding:8px 14px',
    'border-radius:8px',
    'box-shadow:0 4px 12px rgba(0,0,0,.4)',
    'pointer-events:none',
    'transition:opacity .2s',
  ].join(';')
  el.textContent = message
  document.body.appendChild(el)
  const timer = setTimeout(() => {
    el.style.opacity = '0'
    const remove = setTimeout(() => el.remove(), 200)
    return remove
  }, 3000)
  // Safety: remove on unload
  const cleanup = () => {
    clearTimeout(timer)
    el.remove()
  }
  window.addEventListener('beforeunload', cleanup, { once: true })
}

// ─── Payload type ─────────────────────────────────────────────────────────────

interface ViewChangeTo {
  kind: 'diagram' | string
  id: string
  draft_id?: string
}

interface ViewChangePayload {
  reason?: string
  to: ViewChangeTo
}

// ─── Hook ─────────────────────────────────────────────────────────────────────

/**
 * Watches the agent stream for `view_change` events and navigates to the
 * indicated route when one arrives.  Wire inside ChatBubble so it runs
 * while the bubble is mounted.
 */
export function useViewChange() {
  const stream = useAgentStream()
  const navigate = useNavigate()
  // Track the last event id we already acted on so we don't fire twice if
  // the events array reference changes without a new view_change being added.
  const handledIdRef = useRef<number>(-1)

  useEffect(() => {
    if (stream.events.length === 0) return
    const last = stream.events[stream.events.length - 1]
    if (!last) return
    if (last.kind !== 'view_change') return
    if (last.id <= handledIdRef.current) return

    handledIdRef.current = last.id

    const payload = last.payload as ViewChangePayload
    const { to, reason } = payload
    if (!to) return

    if (to.kind === 'diagram') {
      const path = to.draft_id
        ? `/diagram/${to.id}?draft=${to.draft_id}`
        : `/diagram/${to.id}`
      navigate(path)
      const message =
        reason === 'draft_created' ? 'Switched to new draft' : 'Switched to draft'
      showViewChangeToast(message)
    }
  }, [stream.events, navigate])
}
