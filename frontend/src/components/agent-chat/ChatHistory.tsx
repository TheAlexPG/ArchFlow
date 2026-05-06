import { useEffect, useMemo, useRef } from 'react'
import { buildRenderItems, type RenderItem } from './build-render-items'
import { useAgentStream } from './hooks/use-agent-stream'
import { MagicPromptButtons } from './MagicPromptButtons'
import {
  AppliedChangePill,
  AssistantText,
  BudgetWarning,
  CompactionBanner,
  ErrorBubble,
  NodeIndicator,
  RequiresChoiceCard,
  UsageFootnote,
  UserMessage,
  type NodeToolEntry,
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

  // Group tool_call items under the most recent preceding ``node`` item so
  // each NodeIndicator can render an icon row with the agent's tool
  // activity. Computed here (not in build-render-items) because it's a
  // pure derived view over the same array — keeps the renderer
  // self-contained without growing the RenderItem schema.
  const toolsByNodeIdx = useMemo(() => groupToolsByNode(renderItems), [renderItems])

  // Empty fresh session → show the magic-prompt starters centered in the
  // history area. The starters use the SAME submit path as ChatComposer
  // (stream.startStream('general', …)) so clicking one is indistinguishable
  // from typing the prompt manually. Hides the moment the stream pushes
  // its optimistic user-message echo, transitioning into the live transcript.
  const isEmpty = stream.events.length === 0 && !stream.isStreaming

  return (
    <div data-testid="chat-history" className="flex-1 overflow-y-auto p-4 space-y-3 min-h-0 flex flex-col">
      {isEmpty && <MagicPromptButtons />}
      {/* Phase 1: only events from the current run are rendered.
          Persistence via GET /sessions/{id} comes in a later task. */}
      {renderItems.map((item, i) => (
        <RenderItem
          key={`${item.kind}-${i}`}
          item={item}
          tools={item.kind === 'node' ? toolsByNodeIdx.get(i) : undefined}
          onRetry={stream.retry}
        />
      ))}
      {stream.isStreaming && shouldShowThinking(renderItems) && <ThinkingIndicator />}
      <BottomScroller events={stream.events} />
    </div>
  )
}

// ─── Tool grouping ──────────────────────────────────────────────────────────
//
// Walks the projected RenderItems once and assigns every ``tool_call``
// item to the closest preceding ``node`` item, building a Map keyed by
// the node's index in ``renderItems``. Tool calls before any node go
// unassigned (the existing chronological cards still render them).
//
// We rely on the runtime emitting a ``node`` SSE event each time the
// LangGraph supervisor enters a sub-graph (researcher / planner / …),
// which is what build-render-items already projects as ``kind === 'node'``.

function groupToolsByNode(items: RenderItem[]): Map<number, NodeToolEntry[]> {
  const groups = new Map<number, NodeToolEntry[]>()
  let currentNodeIdx: number | null = null
  for (let i = 0; i < items.length; i++) {
    const it = items[i]
    if (it.kind === 'node') {
      currentNodeIdx = i
      continue
    }
    if (it.kind !== 'tool_call' || currentNodeIdx === null) continue
    const list = groups.get(currentNodeIdx) ?? []
    // ``args`` is the canonical key in the projected RenderItem (set by
    // build-render-items), but the raw SSE payload uses ``arguments`` when
    // the backend forwards LangGraph's openai-shape tool call. Read both
    // so we don't lose the args preview if the projection ever changes.
    const args = it.payload?.args ?? it.payload?.arguments
    list.push({
      id: String(it.payload?.id ?? `tc-${i}`),
      name: String(it.payload?.name ?? 'tool'),
      args,
      status: it.pairedToolResult?.status as string | undefined,
    })
    groups.set(currentNodeIdx, list)
  }
  return groups
}

// ─── RenderItem dispatch ───────────────────────────────────────────────────

function RenderItem({
  item,
  tools,
  onRetry,
}: {
  item: RenderItem
  tools?: NodeToolEntry[]
  onRetry: () => void
}) {
  switch (item.kind) {
    case 'user_message':
      return <UserMessage text={item.payload.text} />
    case 'assistant_text':
      return <AssistantText text={item.payload.text} />
    case 'node':
      return <NodeIndicator node={item.payload.node} tools={tools} />
    case 'tool_call':
      // Tool calls render as compact icons inside the parent NodeIndicator's
      // tool-badge row (see groupToolsByNode above + NodeToolBadges popover).
      // We deliberately do NOT render an inline ToolCallCard here — the icon
      // row is the only surface for tool activity in the transcript.
      return null
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

// Network/transient errors are retriable by default; auth/validation are not.
function isRetriableCode(code: string | undefined): boolean {
  if (!code) return false
  const retriable = ['network', 'timeout', 'rate_limited', 'unavailable', 'connection_lost']
  return retriable.includes(code.toLowerCase())
}

// ─── ThinkingIndicator ─────────────────────────────────────────────────────
//
// Bottom-of-history "agent is working" badge. We deliberately keep a
// single focal motion in the chat at any time:
//   - in-flight tool card → its own top-edge progress sweep is the focus
//   - active node indicator → its heartbeat glow is the focus
//   - otherwise → this pill (a single breathing dot + label)
// ``shouldShowThinking`` enforces that hierarchy so the user is never
// looking at three things pulsing at once.

function shouldShowThinking(items: RenderItem[]): boolean {
  if (items.length === 0) return true
  const last = items[items.length - 1]
  // Node indicator already carries the activity affordance.
  if (last.kind === 'node') return false
  // In-flight tool card has its own top-edge progress sweep.
  if (last.kind === 'tool_call' && !last.pairedToolResult) return false
  return true
}

function ThinkingIndicator() {
  return (
    <div className="flex justify-start" data-testid="thinking-indicator">
      <div
        className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-surface border border-coral/30 text-[11px] text-text-2 font-mono"
        style={{
          animation: 'archflow-heartbeat 1.6s cubic-bezier(0.16, 1, 0.3, 1) infinite',
        }}
      >
        <span
          aria-hidden
          className="inline-block w-1.5 h-1.5 rounded-full bg-coral shadow-[0_0_6px_var(--color-coral)]"
        />
        <span>Agent thinking</span>
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
