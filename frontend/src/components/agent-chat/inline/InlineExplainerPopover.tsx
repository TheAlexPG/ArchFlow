// Inline AI-explain popover — one-shot, non-streaming.
// Mounts near `anchorEl` via manual getBoundingClientRect positioning.
// Max width 460px to stay compact on the canvas.

import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useAgentChatStore } from '../store'
import { useAuthStore } from '../../../stores/auth-store'
import { useWorkspaceStore } from '../../../stores/workspace-store'

interface Props {
  objectId: string
  onClose: () => void
  anchorEl: HTMLElement
}

interface ExplainResult {
  final_message?: string
  result?: string
  answer?: string
  content?: string
}

function buildHeaders(authToken: string | undefined, workspaceId: string | undefined): Record<string, string> {
  const h: Record<string, string> = { 'Content-Type': 'application/json' }
  if (authToken) h.Authorization = `Bearer ${authToken}`
  if (workspaceId) h['X-Workspace-ID'] = workspaceId
  return h
}

function extractMessage(data: ExplainResult): string {
  return data.final_message ?? data.result ?? data.answer ?? data.content ?? '(no response)'
}

// Simple markdown renderer — handles **bold**, `code`, and newlines.
// We deliberately avoid importing a heavy markdown lib for this small surface.
function renderMarkdown(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/`([^`]+)`/g, '<code style="background:rgba(255,255,255,0.1);padding:1px 4px;border-radius:3px;font-size:11px">$1</code>')
    .replace(/\n/g, '<br/>')
}

function computeCoords(anchorEl: HTMLElement): { top: number; left: number } {
  const rect = anchorEl.getBoundingClientRect()
  const width = 460
  let left = rect.right + 8
  let top = rect.top
  if (left + width > window.innerWidth - 8) {
    left = rect.left - width - 8
  }
  if (left < 8) left = 8
  if (top + 300 > window.innerHeight - 8) {
    top = window.innerHeight - 300 - 8
  }
  return { top, left }
}

export function InlineExplainerPopover({ objectId, onClose, anchorEl }: Props) {
  const [loading, setLoading] = useState(true)
  const [text, setText] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const popoverRef = useRef<HTMLDivElement>(null)
  const { open: openBubble } = useAgentChatStore()

  // Compute position synchronously from anchorEl — no effect needed.
  const coords = computeCoords(anchorEl)

  // Fetch on mount.
  useEffect(() => {
    const authToken = useAuthStore.getState().accessToken ?? undefined
    const workspaceId = useWorkspaceStore.getState().currentWorkspaceId ?? undefined
    const ctrl = new AbortController()

    fetch('/api/v1/agents/diagram-explainer/invoke', {
      method: 'POST',
      headers: buildHeaders(authToken, workspaceId),
      body: JSON.stringify({
        context: { kind: 'object', id: objectId },
        message: 'Explain this in 2 paragraphs.',
      }),
      signal: ctrl.signal,
      credentials: 'include',
    })
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const data = (await res.json()) as ExplainResult
        setText(extractMessage(data))
      })
      .catch((err: Error) => {
        if (err.name !== 'AbortError') setError(err.message)
      })
      .finally(() => setLoading(false))

    return () => ctrl.abort()
  }, [objectId])

  // Close on outside click.
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        onClose()
      }
    }
    setTimeout(() => window.addEventListener('mousedown', handler), 0)
    return () => window.removeEventListener('mousedown', handler)
  }, [onClose])

  // Close on Esc.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  const handleOpenInChat = () => {
    openBubble()
    onClose()
  }

  return createPortal(
    <div
      ref={popoverRef}
      data-testid="inline-explainer-popover"
      style={{
        position: 'fixed',
        top: coords.top,
        left: coords.left,
        width: 460,
        maxWidth: 'calc(100vw - 16px)',
        zIndex: 20000,
      }}
    >
      <div
        style={{
          background: '#1a1a1a',
          border: '1px solid #333',
          borderRadius: 8,
          boxShadow: '0 8px 32px rgba(0,0,0,0.6)',
          overflow: 'hidden',
        }}
      >
        {/* Header */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '10px 14px 8px',
            borderBottom: '1px solid #2a2a2a',
          }}
        >
          <span style={{ fontSize: 11, fontWeight: 600, color: '#a3a3a3', letterSpacing: '0.05em', textTransform: 'uppercase' }}>
            AI Explain
          </span>
          <button
            data-testid="inline-explainer-close"
            onClick={onClose}
            style={{ background: 'none', border: 'none', color: '#666', cursor: 'pointer', fontSize: 16, lineHeight: 1, padding: '0 2px' }}
            aria-label="Close"
          >
            ×
          </button>
        </div>

        {/* Body */}
        <div style={{ padding: '12px 14px', minHeight: 60 }}>
          {loading && (
            <div data-testid="inline-explainer-loading" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {[100, 80, 90].map((w, i) => (
                <div
                  key={i}
                  style={{
                    height: 12,
                    borderRadius: 4,
                    background: 'linear-gradient(90deg, #2a2a2a 25%, #333 50%, #2a2a2a 75%)',
                    backgroundSize: '200% 100%',
                    animation: 'shimmer 1.4s infinite',
                    width: `${w}%`,
                  }}
                />
              ))}
            </div>
          )}
          {error && (
            <div style={{ color: '#f87171', fontSize: 12 }}>
              Failed to load explanation: {error}
            </div>
          )}
          {text && !loading && (
            <div
              data-testid="inline-explainer-result"
              style={{ fontSize: 12, color: '#d4d4d4', lineHeight: 1.6 }}
              dangerouslySetInnerHTML={{ __html: renderMarkdown(text) }}
            />
          )}
        </div>

        {/* Footer */}
        {!loading && !error && (
          <div
            style={{
              padding: '8px 14px 10px',
              borderTop: '1px solid #2a2a2a',
              display: 'flex',
              justifyContent: 'flex-end',
            }}
          >
            <button
              data-testid="inline-explainer-open-chat"
              onClick={handleOpenInChat}
              style={{
                background: 'none',
                border: 'none',
                color: '#f97316',
                fontSize: 11,
                cursor: 'pointer',
                padding: '2px 0',
                fontWeight: 500,
              }}
            >
              Open in chat →
            </button>
          </div>
        )}
      </div>
      {/* Shimmer keyframe */}
      <style>{`@keyframes shimmer{0%{background-position:200% 0}100%{background-position:-200% 0}}`}</style>
    </div>,
    document.body,
  )
}
