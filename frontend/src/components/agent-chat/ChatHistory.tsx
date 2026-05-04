import { useEffect, useMemo, useRef } from 'react'
import { buildRenderItems, type RenderItem } from './build-render-items'
import { useAgentStream } from './hooks/use-agent-stream'
import {
  AppliedChangePill,
  AssistantText,
  BudgetWarning,
  CompactionBanner,
  ErrorBubble,
  NodeIndicator,
  RequiresChoiceCard,
  ToolCallCard,
  UsageFootnote,
  UserMessage,
  type ToolStatus,
} from './messages'
import type { AgentSSEEvent } from './types'

// ─── ChatHistory ───────────────────────────────────────────────────────────
//
// Walks `events` once per render and projects each SSE event into a
// RenderItem. Sequential `token` events are collapsed into a single
// AssistantText block, and `tool_call` is paired with its matching
// `tool_result` (by `id`) so we render one ToolCallCard per tool turn.
//
// All state is derived from `events` — there is no local mutable buffer.
// useMemo on the events array means we only re-bucket when new frames
// land, not on unrelated re-renders.

export function ChatHistory() {
  const stream = useAgentStream()
  const renderItems = useMemo(() => buildRenderItems(stream.events), [stream.events])

  return (
    <div data-testid="chat-history" className="flex-1 overflow-y-auto p-4 space-y-3 min-h-0">
      {/* Phase 1: only events from the current run are rendered.
          Persistence via GET /sessions/{id} comes in a later task. */}
      {renderItems.map((item, i) => (
        <RenderItem key={`${item.kind}-${i}`} item={item} onRetry={stream.retry} />
      ))}
      {stream.isStreaming && shouldShowThinking(renderItems) && <ThinkingIndicator />}
      <BottomScroller events={stream.events} />
    </div>
  )
}

// ─── RenderItem dispatch ───────────────────────────────────────────────────

function RenderItem({ item, onRetry }: { item: RenderItem; onRetry: () => void }) {
  switch (item.kind) {
    case 'user_message':
      return <UserMessage text={item.payload.text} />
    case 'assistant_text':
      return <AssistantText text={item.payload.text} />
    case 'node':
      return <NodeIndicator node={item.payload.node} />
    case 'tool_call': {
      const status = deriveToolStatus(item.pairedToolResult)
      const preview = item.pairedToolResult?.preview as string | undefined
      const result = item.pairedToolResult?.result ?? item.pairedToolResult?.content
      return (
        <ToolCallCard
          id={item.payload.id}
          name={item.payload.name}
          args={item.payload.args}
          status={status}
          preview={preview}
          result={result}
        />
      )
    }
    case 'applied_change':
      return (
        <AppliedChangePill
          action={item.payload.action}
          target_type={item.payload.target_type}
          target_id={item.payload.target_id}
          name={item.payload.name}
        />
      )
    case 'compaction':
      return (
        <CompactionBanner
          stage={item.payload.stage}
          strategy={item.payload.strategy}
          tokens_before={item.payload.tokens_before}
          tokens_after={item.payload.tokens_after}
        />
      )
    case 'budget_warning':
      return (
        <BudgetWarning
          used={item.payload.used_usd ?? item.payload.used ?? 0}
          limit={item.payload.limit_usd ?? item.payload.limit ?? 0}
          scope={item.payload.scope ?? 'session'}
        />
      )
    case 'requires_choice':
      return (
        <RequiresChoiceCard
          kind={item.payload.kind}
          message={item.payload.message ?? ''}
          options={item.payload.options ?? []}
          tool_call_id={item.payload.tool_call_id}
        />
      )
    case 'error':
      return (
        <ErrorBubble
          code={item.payload.code ?? 'unknown'}
          message={item.payload.message ?? 'Unknown error'}
          retriable={item.payload.retriable === true || isRetriableCode(item.payload.code)}
          onRetry={onRetry}
        />
      )
    case 'usage':
      return (
        <UsageFootnote
          tokens_in={item.payload.tokens_in}
          tokens_out={item.payload.tokens_out}
          cost_usd={item.payload.cost_usd}
          duration_ms={item.payload.duration_ms}
        />
      )
  }
}

// ─── Tool status derivation ────────────────────────────────────────────────
//
// The server's `tool_result.status` field is the source of truth. When the
// result hasn't arrived yet we show the pending spinner.

function deriveToolStatus(result: { status?: string } | undefined): ToolStatus {
  if (!result) return 'pending'
  switch (result.status) {
    case 'ok':
    case 'success':
      return 'ok'
    case 'error':
    case 'failed':
      return 'error'
    case 'denied':
    case 'forbidden':
      return 'denied'
    case 'awaiting_confirmation':
    case 'requires_confirmation':
      return 'awaiting_confirmation'
    default:
      return 'pending'
  }
}

// Network/transient errors are retriable by default; auth/validation are not.
function isRetriableCode(code: string | undefined): boolean {
  if (!code) return false
  const retriable = ['network', 'timeout', 'rate_limited', 'unavailable', 'connection_lost']
  return retriable.includes(code.toLowerCase())
}

// ─── ThinkingIndicator ─────────────────────────────────────────────────────
//
// Bottom-of-history "agent is working" badge. Shown only while a stream is
// active and the latest render item isn't itself an in-flight signal
// (NodeIndicator or a pending tool card already convey activity). Ensures
// the user never sees a silent panel between SSE frames.

function shouldShowThinking(items: RenderItem[]): boolean {
  if (items.length === 0) return true
  const last = items[items.length - 1]
  if (last.kind === 'node') return false
  if (last.kind === 'tool_call' && !last.pairedToolResult) return false
  return true
}

function ThinkingIndicator() {
  return (
    <div className="flex justify-start" data-testid="thinking-indicator">
      <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-surface border border-coral/30 text-[11px] text-text-2 font-mono">
        <span className="inline-flex items-center gap-0.5" aria-hidden>
          <span className="w-1 h-1 rounded-full bg-coral animate-pulse" />
          <span className="w-1 h-1 rounded-full bg-coral animate-pulse [animation-delay:120ms]" />
          <span className="w-1 h-1 rounded-full bg-coral animate-pulse [animation-delay:240ms]" />
        </span>
        Agent thinking
      </div>
    </div>
  )
}

// ─── BottomScroller ────────────────────────────────────────────────────────
//
// Empty div placed at the bottom of the list. Whenever new events land we
// scroll it into view. Using a separate component avoids re-running the
// effect on parent re-renders that don't change the events array length.

function BottomScroller({ events }: { events: AgentSSEEvent[] }) {
  const ref = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    ref.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [events.length])

  return <div ref={ref} data-testid="chat-bottom-scroller" />
}
