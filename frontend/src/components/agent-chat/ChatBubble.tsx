import { useEffect, useState } from 'react'
import { cn } from '../../utils/cn'
import { useCurrentMemberAgentAccess } from '../../hooks/use-api'
import { ChatComposer } from './ChatComposer'
import { ChatHeader } from './ChatHeader'
import { ChatHistory } from './ChatHistory'
import { ChatStatusBar } from './ChatStatusBar'
import { DraftCreatedBanner } from './DraftCreatedBanner'
import { AgentStreamProvider, useAgentStream } from './hooks/use-agent-stream'
import { useAgentSession } from './hooks/use-agent-sessions'
import { useAppliedChangeSync } from './hooks/use-applied-change-sync'
import { useViewChange } from './hooks/use-view-change'
import { useAgentChatStore } from './store'

// ─── Session history loader ─────────────────────────────────────────────────
//
// When the user picks a past session from SessionPicker, ``activeSessionId``
// flips to a real id while ``stream.sessionId`` is still null (the picker
// only resets the stream and updates the store). We watch for that delta,
// fetch the session detail, and seed the transcript with its messages so
// the bubble shows the historical conversation immediately.
//
// We DO NOT load history when the stream already owns this session id
// (i.e. the user just sent a message and got a session frame back) — that
// would clobber the live events with a stale snapshot.

function useSessionHistoryLoader(): void {
  const stream = useAgentStream()
  const activeSessionId = useAgentChatStore((s) => s.activeSessionId)
  const { data, isFetched } = useAgentSession(activeSessionId)

  useEffect(() => {
    if (!activeSessionId || !data || !isFetched) return
    if (stream.sessionId === activeSessionId) return
    // Only seed user/assistant turns into the visible transcript —
    // system / tool / compacted rows belong to LLM context, not the
    // user-facing history. ``content_text`` is the canonical field on
    // the wire (see backend MessageRead model).
    const visible = data.messages
      .filter(
        (m): m is typeof m & { role: 'user' | 'assistant' } =>
          (m.role === 'user' || m.role === 'assistant') &&
          typeof m.content_text === 'string' &&
          m.content_text.trim().length > 0,
      )
      .map((m) => ({ role: m.role, content: m.content_text as string }))
    stream.loadHistory(visible, activeSessionId)
    // We deliberately re-run only when the session detail or selection
    // changes — stream identity is stable across renders.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeSessionId, data, isFetched])
}

// ─── Breakpoint hook ────────────────────────────────────────────────────────

function useIsMobile(): boolean {
  const [isMobile, setIsMobile] = useState(() => {
    if (typeof window === 'undefined') return false
    return window.matchMedia('(max-width: 767px)').matches
  })

  useEffect(() => {
    const mq = window.matchMedia('(max-width: 767px)')
    const handler = (e: MediaQueryListEvent) => setIsMobile(e.matches)
    mq.addEventListener('change', handler)
    return () => mq.removeEventListener('change', handler)
  }, [])

  return isMobile
}

// ─── ChatBody — renders the streaming transcript ───────────────────────────
//
// Thin wrapper over <ChatHistory>. Kept as its own component (rather than
// inlining ChatHistory in the panel JSX) so the data-testid="chat-body"
// hook still resolves for existing layout tests.

function ChatBody() {
  return (
    <div data-testid="chat-body" className="flex-1 flex flex-col min-h-0">
      <ChatHistory />
    </div>
  )
}

// ─── ChatBubble ──────────────────────────────────────────────────────────────

export function ChatBubble() {
  const bubbleState = useAgentChatStore((s) => s.bubbleState)
  const open = useAgentChatStore((s) => s.open)
  const agentAccess = useCurrentMemberAgentAccess()

  // ── Agent access gate — hide entirely when disabled ──────────────────────
  if (agentAccess === 'none') return null

  // ── Closed: floating action button ────────────────────────────────────────
  if (bubbleState === 'closed') {
    return (
      <button
        data-testid="chat-bubble-fab"
        aria-label="Open ArchFlow Agent"
        onClick={open}
        className={cn(
          'fixed bottom-4 right-4 z-50',
          'w-12 h-12 rounded-full',
          'bg-panel border border-border-hi',
          'text-xl',
          'flex items-center justify-center',
          'shadow-window',
          'hover:bg-surface-hi hover:border-coral/40 hover:shadow-coral-glow',
          'transition-all duration-150',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-coral/50',
          // Subtle pulse animation using the existing fab-ring keyframe
          'animate-[fab-ring_3s_ease-in-out_infinite]',
        )}
      >
        <span aria-hidden="true">🤖</span>
      </button>
    )
  }

  // The panel + its stream context — provider lives here so every child sees
  // the same `events`/`isStreaming`/etc. instead of each useAgentStream() call
  // creating its own isolated state.
  return (
    <AgentStreamProvider>
      <ChatBubblePanel />
    </AgentStreamProvider>
  )
}

function ChatBubblePanel() {
  const bubbleState = useAgentChatStore((s) => s.bubbleState)
  const size = useAgentChatStore((s) => s.size)
  const isMobile = useIsMobile()

  // Wire view_change handler — navigates + shows toast whenever the agent
  // emits a view_change event. Must run inside the AgentStreamProvider tree.
  useViewChange()
  // Refresh canvas / object / connection caches whenever the agent applied
  // a mutation, so the live diagram updates without a page reload.
  useAppliedChangeSync()
  // Hydrate transcript when the user picks a past session from the picker.
  useSessionHistoryLoader()

  const isExpanded = bubbleState === 'expanded'

  // Mobile: full bottom-sheet regardless of open/expanded
  if (isMobile) {
    return (
      <div
        data-testid="chat-panel"
        data-bubble-state={bubbleState}
        className={cn(
          'fixed inset-x-0 bottom-0 z-50',
          'flex flex-col',
          'bg-panel border border-border-base border-b-0',
          'rounded-t-xl',
          // Animate in from the bottom
          'animate-[popup-in_0.22s_cubic-bezier(0.16,1,0.3,1)_forwards]',
        )}
        style={{
          height: isExpanded ? '85vh' : '70vh',
          boxShadow: 'var(--shadow-window)',
        }}
      >
        <ChatHeader />
        <ChatBody />
        <DraftCreatedBanner />
        <ChatStatusBar />
        <ChatComposer />
      </div>
    )
  }

  // Desktop: floating panel anchored bottom-right
  const panelWidth = isExpanded ? Math.min(window.innerWidth * 0.6, 1024) : size.width
  const panelHeight = isExpanded ? Math.min(window.innerHeight * 0.8, window.innerHeight * 0.8) : size.height

  return (
    <div
      data-testid="chat-panel"
      data-bubble-state={bubbleState}
      className={cn(
        'fixed bottom-4 right-4 z-50',
        'flex flex-col',
        'bg-panel border border-border-base',
        'rounded-xl',
        'animate-[popup-in_0.22s_cubic-bezier(0.16,1,0.3,1)_forwards]',
      )}
      style={{
        width: panelWidth,
        height: panelHeight,
        boxShadow: 'var(--shadow-window)',
      }}
    >
      <ChatHeader />
      <ChatBody />
      <DraftCreatedBanner />
      <ChatStatusBar />
      <ChatComposer />
    </div>
  )
}
