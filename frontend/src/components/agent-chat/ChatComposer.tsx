import { useEffect, useRef, useState } from 'react'
import { cn } from '../../utils/cn'
import { useChatContext } from './hooks/use-chat-context'
import { useAgentStream } from './hooks/use-agent-stream'
import { useAgentChatStore } from './store'
import type { ChatMode, ChatContext } from './types'
import type { UseAgentStreamResult } from './hooks/use-agent-stream'

// ─── Slash-command handler ────────────────────────────────────────────────────

interface SlashHelpers {
  startStream: UseAgentStreamResult['startStream']
  reset: UseAgentStreamResult['reset']
  ctx: ChatContext
  mode: ChatMode
}

function handleSlashCommand(text: string, helpers: SlashHelpers): boolean {
  const { startStream, reset, ctx, mode } = helpers

  // /clear — wipe transcript
  if (text === '/clear') {
    reset()
    return true
  }

  // /explain <id> — explain a specific object
  const explainMatch = text.match(/^\/explain\s+(\S+)/)
  if (explainMatch) {
    const id = explainMatch[1]
    startStream('diagram-explainer', {
      context: { kind: 'object', id },
      message: text,
      mode,
    })
    return true
  }

  // /research <query> — general research agent
  const researchMatch = text.match(/^\/research\s+(.+)/)
  if (researchMatch) {
    const query = researchMatch[1]
    startStream('researcher', {
      context: ctx,
      message: query,
      mode,
    })
    return true
  }

  return false
}

// ─── ChatComposer ─────────────────────────────────────────────────────────────

export function ChatComposer() {
  const [draft, setDraft] = useState('')
  const ref = useRef<HTMLTextAreaElement>(null)
  const stream = useAgentStream()
  const ctx = useChatContext()
  const mode = useAgentChatStore((s) => s.mode)

  // ── Autoresize: grow with content, cap at ~8 rows ─────────────────────────
  useEffect(() => {
    const el = ref.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 192)}px` // 192px ≈ 8 rows
  }, [draft])

  // ── Send ──────────────────────────────────────────────────────────────────
  const send = () => {
    const text = draft.trim()
    if (!text || stream.isStreaming) return

    if (text.startsWith('/')) {
      const handled = handleSlashCommand(text, {
        startStream: stream.startStream,
        reset: stream.reset,
        ctx,
        mode,
      })
      if (handled) {
        setDraft('')
        return
      }
    }

    stream.startStream('general', { context: ctx, message: text, mode })
    setDraft('')
  }

  const isDisabled = ctx.kind === 'none' || stream.isStreaming

  return (
    <div
      data-testid="chat-composer"
      className={cn(
        'flex-shrink-0 px-3 py-2',
        'border-t border-border-base',
        'bg-panel rounded-b-xl',
      )}
    >
      {ctx.kind === 'none' && (
        <p className="text-[11px] text-text-4 mb-1">Open a workspace to chat.</p>
      )}

      <div className="flex items-end gap-2">
        <textarea
          ref={ref}
          data-testid="composer-textarea"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
              e.preventDefault()
              send()
            }
            if (e.key === 'Escape') {
              useAgentChatStore.getState().close()
            }
          }}
          placeholder="Type a message… (⌘+Enter to send)"
          disabled={isDisabled}
          rows={1}
          style={{ resize: 'none', maxHeight: '12rem' }}
          className={cn(
            'flex-1 min-w-0',
            'bg-surface border border-border-base rounded-md',
            'px-3 py-1.5',
            'text-[13px] text-text-1 placeholder:text-text-4',
            'focus:outline-none focus:ring-1 focus:ring-coral/40 focus:border-coral/40',
            'transition-colors duration-100',
            'disabled:opacity-40 disabled:cursor-not-allowed',
            'leading-5 font-mono',
          )}
        />

        {stream.isStreaming ? (
          <button
            data-testid="composer-cancel-btn"
            onClick={() => {
              void stream.cancel()
            }}
            aria-label="Cancel generation"
            title="Cancel generation"
            className={cn(
              'relative flex-shrink-0',
              'w-9 h-9 rounded-full',
              'bg-red-500 text-white',
              'flex items-center justify-center',
              'hover:bg-red-600',
              'transition-colors duration-100',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-400/60',
            )}
          >
            {/* Pulsing ring around the button — "processing" indicator */}
            <span
              aria-hidden
              className="absolute inset-0 rounded-full ring-2 ring-red-500/40 animate-ping"
            />
            {/* Filled square = stop */}
            <svg
              viewBox="0 0 16 16"
              className="relative w-3 h-3 fill-current"
              aria-hidden
            >
              <rect x="3" y="3" width="10" height="10" rx="1" />
            </svg>
          </button>
        ) : (
          <button
            data-testid="composer-send-btn"
            onClick={send}
            disabled={!draft.trim() || ctx.kind === 'none'}
            aria-label="Send message"
            title="Send (⌘+Enter)"
            className={cn(
              'flex-shrink-0',
              'w-9 h-9 rounded-full',
              'bg-coral text-white',
              'flex items-center justify-center',
              'hover:bg-coral/80',
              'disabled:opacity-30 disabled:cursor-not-allowed',
              'transition-colors duration-100',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-coral/50',
            )}
          >
            <svg
              viewBox="0 0 16 16"
              className="w-4 h-4 fill-current"
              aria-hidden
            >
              <path d="M8 2.5l5 5h-3.25v6h-3.5v-6H3l5-5z" />
            </svg>
          </button>
        )}
      </div>
    </div>
  )
}
