import { render, screen, fireEvent } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ChatStatusBar } from '../ChatStatusBar'

// ─── Mock useAgentStream ─────────────────────────────────────────────────────

const mockCancel = vi.fn()

const mockStreamState = {
  events: [] as Array<{ id: number; kind: string; payload: unknown }>,
  isStreaming: false,
  lastError: null,
  sessionId: null,
  isReconnecting: false,
  connectionLost: false,
  startStream: vi.fn(),
  cancel: mockCancel,
  respond: vi.fn(),
  retry: vi.fn(),
  reset: vi.fn(),
}

vi.mock('../hooks/use-agent-stream', () => ({
  useAgentStream: () => mockStreamState,
}))

// ─── Helpers ─────────────────────────────────────────────────────────────────

function nodeEvent(id: number) {
  return { id, kind: 'node', payload: null }
}

function usageEvent(id: number, tokens_in: number, tokens_out: number, cost_usd: number) {
  return { id, kind: 'usage', payload: { tokens_in, tokens_out, cost_usd } }
}

function compactionEvent(id: number, stage: number, strategy = 'summarise') {
  return { id, kind: 'compaction_applied', payload: { stage, strategy } }
}

function budgetWarningEvent(id: number, used: number, limit: number) {
  return { id, kind: 'budget_warning', payload: { used, limit } }
}

// ─── Suite ───────────────────────────────────────────────────────────────────

describe('ChatStatusBar', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockStreamState.events = []
    mockStreamState.isStreaming = false
  })

  it('is hidden when idle with no events', () => {
    mockStreamState.events = []
    mockStreamState.isStreaming = false

    render(<ChatStatusBar />)

    expect(screen.queryByTestId('chat-status-bar')).not.toBeInTheDocument()
  })

  it('shows turns count from node events', () => {
    mockStreamState.isStreaming = true
    mockStreamState.events = [nodeEvent(1), nodeEvent(2), nodeEvent(3)]

    render(<ChatStatusBar />)

    expect(screen.getByTestId('status-turns')).toHaveTextContent('Turns: 3/200')
  })

  it('shows cost and tokens from the latest usage event', () => {
    mockStreamState.isStreaming = true
    mockStreamState.events = [
      nodeEvent(1),
      usageEvent(2, 1000, 500, 0.034),
    ]

    render(<ChatStatusBar />)

    expect(screen.getByTestId('status-cost')).toHaveTextContent('$0.034/$1.00')
  })

  it('shows compaction indicator when a compaction_applied event is present', () => {
    mockStreamState.isStreaming = true
    mockStreamState.events = [nodeEvent(1), compactionEvent(2, 2, 'summarise')]

    render(<ChatStatusBar />)

    const indicator = screen.getByTestId('status-compaction')
    expect(indicator).toBeInTheDocument()
    expect(indicator).toHaveTextContent('Compacted (2/4)')
    expect(indicator).toHaveAttribute('title', 'Compacted via summarise')
  })

  it('shows budget warning style when used > 85% of limit', () => {
    mockStreamState.isStreaming = true
    mockStreamState.events = [
      nodeEvent(1),
      budgetWarningEvent(2, 0.90, 1.00),
    ]

    render(<ChatStatusBar />)

    const warning = screen.getByTestId('status-budget-warning')
    expect(warning).toBeInTheDocument()
    expect(warning).toHaveClass('text-orange-500')
  })

  it('does NOT show budget warning when used <= 85% of limit', () => {
    mockStreamState.isStreaming = true
    mockStreamState.events = [
      nodeEvent(1),
      budgetWarningEvent(2, 0.80, 1.00),
    ]

    render(<ChatStatusBar />)

    expect(screen.queryByTestId('status-budget-warning')).not.toBeInTheDocument()
  })

  it('shows cancel button when streaming and calls stream.cancel on click', () => {
    mockStreamState.isStreaming = true
    mockStreamState.events = [nodeEvent(1)]

    render(<ChatStatusBar />)

    const cancelBtn = screen.getByTestId('status-cancel')
    expect(cancelBtn).toBeInTheDocument()

    fireEvent.click(cancelBtn)

    expect(mockCancel).toHaveBeenCalledOnce()
  })

  it('does not show cancel button when not streaming', () => {
    // Has events but isStreaming is false (e.g. after done)
    mockStreamState.isStreaming = false
    mockStreamState.events = [nodeEvent(1)]

    render(<ChatStatusBar />)

    // Status bar is visible (has events) but cancel is absent.
    expect(screen.queryByTestId('status-cancel')).not.toBeInTheDocument()
  })
})
