import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'

import { ChatHistory } from '../ChatHistory'
import { buildRenderItems } from '../build-render-items'
import type { AgentSSEEvent } from '../types'

// ─── Mock useAgentStream ────────────────────────────────────────────────────
//
// Every consumer of useAgentStream gets the same `mockStream` reference. We
// mutate `mockStream.events` directly between renders to drive the test
// scenarios — there's a single render() per test, so React's normal
// useState dependency on equality holds.

const respondMock = vi.fn().mockResolvedValue(undefined)
const retryMock = vi.fn()

const mockStream = {
  events: [] as AgentSSEEvent[],
  isStreaming: false,
  lastError: null,
  sessionId: 'sess-1',
  isReconnecting: false,
  connectionLost: false,
  startStream: vi.fn(),
  cancel: vi.fn(),
  respond: respondMock,
  retry: retryMock,
  reset: vi.fn(),
}

vi.mock('../hooks/use-agent-stream', () => ({
  useAgentStream: () => mockStream,
}))

// ─── Mock canvas-store / workspace-store for ArchflowLink ───────────────────

vi.mock('../../../stores/canvas-store', () => ({
  useCanvasStore: (selector: (s: { selectNode: (id: string) => void; selectEdge: (id: string) => void }) => unknown) =>
    selector({ selectNode: vi.fn(), selectEdge: vi.fn() }),
}))

// ─── scrollIntoView mock (jsdom doesn't implement it) ──────────────────────

const scrollIntoViewMock = vi.fn()
beforeEach(() => {
  scrollIntoViewMock.mockClear()
  respondMock.mockClear()
  retryMock.mockClear()
  mockStream.events = []
  // Patch HTMLElement.prototype so any element gets the spy.
  Element.prototype.scrollIntoView = scrollIntoViewMock as unknown as Element['scrollIntoView']
})

// ─── Helpers ───────────────────────────────────────────────────────────────

function setEvents(events: AgentSSEEvent[]) {
  mockStream.events = events
}

let nextEventId = 1
function evt(kind: AgentSSEEvent['kind'], payload: unknown): AgentSSEEvent {
  return { id: nextEventId++, kind, payload }
}

function renderHistory(): ReturnType<typeof render> {
  const wrapper = ({ children }: { children: ReactNode }) => (
    <MemoryRouter>{children}</MemoryRouter>
  )
  return render(<ChatHistory />, { wrapper })
}

// ─── buildRenderItems unit tests (pure function) ───────────────────────────

describe('buildRenderItems', () => {
  it('collapses sequential token events into a single assistant_text item', () => {
    const items = buildRenderItems([
      evt('token', { delta: 'Hello ' }),
      evt('token', { delta: 'world' }),
      evt('token', { delta: '!' }),
    ])
    expect(items).toHaveLength(1)
    expect(items[0].kind).toBe('assistant_text')
    expect(items[0].payload.text).toBe('Hello world!')
  })

  it('pairs tool_call with matching tool_result by id', () => {
    const items = buildRenderItems([
      evt('tool_call', { id: 'tc-1', name: 'create_object', args: { name: 'svc' } }),
      evt('tool_result', { id: 'tc-1', status: 'ok', preview: 'created Service svc' }),
    ])
    expect(items).toHaveLength(1)
    expect(items[0].kind).toBe('tool_call')
    expect(items[0].pairedToolResult).toMatchObject({ status: 'ok', preview: 'created Service svc' })
  })

  it('keeps tool_call pending when no tool_result has arrived', () => {
    const items = buildRenderItems([
      evt('tool_call', { id: 'tc-1', name: 'slow_tool', args: {} }),
    ])
    expect(items).toHaveLength(1)
    expect(items[0].kind).toBe('tool_call')
    expect(items[0].pairedToolResult).toBeUndefined()
  })

  it('starts a new assistant_text after a non-token event interrupts', () => {
    const items = buildRenderItems([
      evt('token', { delta: 'one' }),
      evt('node', { name: 'planner' }),
      evt('token', { delta: 'two' }),
    ])
    expect(items.map((i) => i.kind)).toEqual(['assistant_text', 'node', 'assistant_text'])
    expect(items[0].payload.text).toBe('one')
    expect(items[2].payload.text).toBe('two')
  })
})

// ─── ChatHistory integration tests ─────────────────────────────────────────

describe('ChatHistory', () => {
  it('renders a UserMessage from a `message` event with role=user', () => {
    setEvents([evt('message', { role: 'user', text: 'Hello agent' })])
    renderHistory()
    const um = screen.getByTestId('user-message')
    expect(um).toHaveTextContent('Hello agent')
  })

  it('renders assistant tokens collapsed into one AssistantText', () => {
    setEvents([
      evt('token', { delta: 'Streaming ' }),
      evt('token', { delta: 'response' }),
    ])
    renderHistory()
    const blocks = screen.getAllByTestId('assistant-text')
    expect(blocks).toHaveLength(1)
    expect(blocks[0]).toHaveTextContent('Streaming response')
  })

  it('does NOT render inline tool-call cards — tool activity is surfaced via NodeIndicator icons only', () => {
    setEvents([
      evt('tool_call', { id: 'tc-1', name: 'create_object', args: { name: 'svc' } }),
      evt('tool_result', { id: 'tc-1', status: 'ok', preview: 'Created Service svc' }),
      evt('tool_call', { id: 'tc-2', name: 'slow_op', args: {} }),
    ])
    renderHistory()
    expect(screen.queryByTestId('tool-call-card')).toBeNull()
  })

  it('renders AppliedChangePill from applied_change event', () => {
    setEvents([
      evt('applied_change', {
        action: 'create',
        target_type: 'object',
        target_id: '11111111-2222-3333-4444-555555555555',
        name: 'PaymentService',
      }),
    ])
    renderHistory()
    const pill = screen.getByTestId('applied-change-pill')
    expect(pill).toHaveAttribute('data-action', 'create')
    expect(pill).toHaveTextContent('Created')
    expect(pill).toHaveTextContent('PaymentService')
  })

  it('renders CompactionBanner for compaction_applied event', () => {
    setEvents([
      evt('compaction_applied', {
        stage: 2,
        strategy: 'summarize_oldest',
        tokens_before: 12000,
        tokens_after: 6000,
      }),
    ])
    renderHistory()
    const banner = screen.getByTestId('compaction-banner')
    expect(banner).toHaveTextContent('Context compacted')
    expect(banner).toHaveTextContent('summarize_oldest')
    expect(banner).toHaveTextContent('50% saved')
  })

  it('renders BudgetWarning at >85% with correct percentage', () => {
    setEvents([
      evt('budget_warning', { used_usd: 0.86, limit_usd: 1.0, scope: 'session' }),
    ])
    renderHistory()
    const banner = screen.getByTestId('budget-warning')
    expect(banner).toHaveAttribute('data-scope', 'session')
    expect(banner).toHaveTextContent('86%')
    expect(banner).toHaveTextContent('$0.86 / $1.00')
  })

  it('RequiresChoiceCard renders options and clicking calls stream.respond', async () => {
    setEvents([
      evt('requires_choice', {
        kind: 'draft_choice',
        message: 'Where should I apply this change?',
        tool_call_id: 'tc-99',
        options: [
          { id: 'live', label: 'Edit live', description: 'Apply to live diagram' },
          { id: 'draft', label: 'Create draft', description: 'Spin up a fresh draft' },
        ],
      }),
    ])
    renderHistory()

    const card = screen.getByTestId('requires-choice-card')
    expect(card).toHaveAttribute('data-kind', 'draft_choice')
    expect(card).toHaveTextContent('Where should I apply this change?')

    fireEvent.click(screen.getByTestId('requires-choice-option-draft'))

    await waitFor(() => {
      expect(respondMock).toHaveBeenCalledWith('tc-99', 'draft')
    })
  })

  it('renders ErrorBubble for error event with retriable code and triggers retry', () => {
    setEvents([
      evt('error', { code: 'network', message: 'Connection dropped' }),
    ])
    renderHistory()
    const bubble = screen.getByTestId('error-bubble')
    expect(bubble).toHaveAttribute('data-error-code', 'network')
    expect(bubble).toHaveAttribute('data-retriable', 'true')

    const retryBtn = screen.getByTestId('error-bubble-retry')
    fireEvent.click(retryBtn)
    expect(retryMock).toHaveBeenCalled()
  })

  it('renders UsageFootnote at end on usage event', () => {
    setEvents([
      evt('token', { delta: 'final answer' }),
      evt('usage', { tokens_in: 1234, tokens_out: 567, cost_usd: 0.0123, duration_ms: 4200 }),
    ])
    renderHistory()
    const footnote = screen.getByTestId('usage-footnote')
    expect(footnote).toHaveTextContent('1,234 in / 567 out')
    expect(footnote).toHaveTextContent('$0.0123')
    expect(footnote).toHaveTextContent('4.20s')
  })

  it('BottomScroller calls scrollIntoView on new events', () => {
    setEvents([evt('token', { delta: 'first' })])
    renderHistory()
    expect(scrollIntoViewMock).toHaveBeenCalled()
  })
})
