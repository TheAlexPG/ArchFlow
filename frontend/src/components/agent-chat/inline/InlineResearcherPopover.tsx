// Inline AI-researcher popover — streaming via SSE.
// Uses the researcher/chat agent with useAgentStream()-like manual fetch.
// Mounts near `anchorEl` via manual getBoundingClientRect positioning.

import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useAgentChatStore } from '../store'
import { useAuthStore } from '../../../stores/auth-store'
import { useWorkspaceStore } from '../../../stores/workspace-store'
import { streamAgent } from '../../../lib/agent-stream'
import type { AgentSSEEvent } from '../types'

interface Props {
  objectId: string
  onClose: () => void
  anchorEl: HTMLElement
}

function buildInvokeBody(objectId: string) {
  return {
    context: { kind: 'object' as const, id: objectId },
    message: 'Research this component in detail — architecture, responsibilities, dependencies, and potential concerns.',
    mode: 'read_only' as const,
  }
}

// Accumulate token events into a running text buffer.
function accumulateTokens(events: AgentSSEEvent[]): string {
  return events
    .filter((e) => e.kind === 'token')
    .map((e) => {
      const p = e.payload as { text?: string; content?: string } | null
      return p?.text ?? p?.content ?? ''
    })
    .join('')
}

// Extract last message event text as fallback.
function extractLastMessage(events: AgentSSEEvent[]): string {
  const msgs = events.filter((e) => e.kind === 'message')
  if (msgs.length === 0) return ''
  const last = msgs[msgs.length - 1]
  const p = last.payload as { content?: string; text?: string; final_message?: string } | null
  return p?.final_message ?? p?.content ?? p?.text ?? ''
}

// Simple markdown renderer matching InlineExplainerPopover.
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
  if (top + 380 > window.innerHeight - 8) {
    top = window.innerHeight - 380 - 8
  }
  return { top, left }
}

export function InlineResearcherPopover({ objectId, onClose, anchorEl }: Props) {
  const [streaming, setStreaming] = useState(true)
  const [events, setEvents] = useState<AgentSSEEvent[]>([])
  const [error, setError] = useState<string | null>(null)
  const popoverRef = useRef<HTMLDivElement>(null)
  const bodyRef = useRef<HTMLDivElement>(null)
  const { open: openBubble } = useAgentChatStore()

  // Compute position synchronously from anchorEl — no effect needed.
  const coords = computeCoords(anchorEl)

  // Stream on mount.
  useEffect(() => {
    const authToken = useAuthStore.getState().accessToken ?? undefined
    const workspaceId = useWorkspaceStore.getState().currentWorkspaceId ?? undefined
    const ctrl = new AbortController()

    void streamAgent({
      url: '/api/v1/agents/researcher/chat',
      body: buildInvokeBody(objectId),
      authToken,
      workspaceId,
      signal: ctrl.signal,
      onEvent: (evt) => {
        if (evt.kind === 'ping') return
        setEvents((prev) => [...prev, evt])
      },
      onError: (err) => setError(err.message),
      onClose: () => setStreaming(false),
    })

    return () => ctrl.abort()
  }, [objectId])

  // Auto-scroll body on new tokens.
  useEffect(() => {
    if (bodyRef.current) {
      bodyRef.current.scrollTop = bodyRef.current.scrollHeight
    }
  }, [events])

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

  const tokenText = accumulateTokens(events)
  const displayText = tokenText || extractLastMessage(events)
  const hasContent = displayText.length > 0

  return createPortal(
    <div
      ref={popoverRef}
      data-testid="inline-researcher-popover"
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
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 11, fontWeight: 600, color: '#a3a3a3', letterSpacing: '0.05em', textTransform: 'uppercase' }}>
              Get Details
            </span>
            {streaming && (
              <span
                data-testid="inline-researcher-streaming"
                style={{
                  display: 'inline-block',
                  width: 6,
                  height: 6,
                  borderRadius: '50%',
                  background: '#f97316',
                  animation: 'pulse 1s ease-in-out infinite',
                }}
              />
            )}
          </div>
          <button
            data-testid="inline-researcher-close"
            onClick={onClose}
            style={{ background: 'none', border: 'none', color: '#666', cursor: 'pointer', fontSize: 16, lineHeight: 1, padding: '0 2px' }}
            aria-label="Close"
          >
            ×
          </button>
        </div>

        {/* Body */}
        <div
          ref={bodyRef}
          style={{ padding: '12px 14px', minHeight: 80, maxHeight: 280, overflowY: 'auto' }}
        >
          {!hasContent && streaming && (
            <div data-testid="inline-researcher-loading" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {[100, 75, 88, 65].map((w, i) => (
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
              Failed to load details: {error}
            </div>
          )}
          {hasContent && (
            <div
              data-testid="inline-researcher-result"
              style={{ fontSize: 12, color: '#d4d4d4', lineHeight: 1.6 }}
              dangerouslySetInnerHTML={{ __html: renderMarkdown(displayText) }}
            />
          )}
        </div>

        {/* Footer */}
        {!streaming && !error && (
          <div
            style={{
              padding: '8px 14px 10px',
              borderTop: '1px solid #2a2a2a',
              display: 'flex',
              justifyContent: 'flex-end',
            }}
          >
            <button
              data-testid="inline-researcher-open-chat"
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
      {/* Shimmer + pulse keyframes */}
      <style>{`
        @keyframes shimmer{0%{background-position:200% 0}100%{background-position:-200% 0}}
        @keyframes pulse{0%,100%{opacity:1}50%{opacity:0.3}}
      `}</style>
    </div>,
    document.body,
  )
}
