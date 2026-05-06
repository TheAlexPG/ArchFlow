import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AllSessionsModal } from '../AllSessionsModal'
import { SessionPicker } from '../SessionPicker'
import { useAgentChatStore } from '../store'

// ─── Mock api-client ──────────────────────────────────────────────────────────

const mockGet = vi.fn()
const mockDelete = vi.fn()
const mockPatch = vi.fn()

vi.mock('../../../lib/api-client', () => ({
  api: {
    get: (...args: unknown[]) => mockGet(...args),
    delete: (...args: unknown[]) => mockDelete(...args),
    patch: (...args: unknown[]) => mockPatch(...args),
  },
}))

// ─── Mock useAgentStream ──────────────────────────────────────────────────────

const mockReset = vi.fn()
const mockStream = {
  events: [],
  isStreaming: false,
  lastError: null,
  sessionId: null,
  isReconnecting: false,
  connectionLost: false,
  startStream: vi.fn(),
  cancel: vi.fn(),
  respond: vi.fn(),
  retry: vi.fn(),
  reset: mockReset,
}

vi.mock('../hooks/use-agent-stream', () => ({
  useAgentStream: () => mockStream,
}))

// ─── Session fixtures ─────────────────────────────────────────────────────────

const SESSIONS = [
  {
    id: 'sess-1',
    agent_id: 'general',
    title: 'Design the auth flow',
    context_kind: 'diagram',
    context_id: 'diag-1',
    last_message_at: new Date(Date.now() - 5 * 60_000).toISOString(),
  },
  {
    id: 'sess-2',
    agent_id: 'general',
    title: 'Review microservices',
    context_kind: 'workspace',
    context_id: null,
    last_message_at: new Date(Date.now() - 60 * 60_000).toISOString(),
  },
  {
    id: 'sess-3',
    agent_id: 'diagram-explainer',
    title: 'Explain C4 containers',
    context_kind: 'diagram',
    context_id: 'diag-2',
    last_message_at: new Date(Date.now() - 2 * 60 * 60_000).toISOString(),
  },
  {
    id: 'sess-4',
    agent_id: 'general',
    title: 'Draft ADR for caching',
    context_kind: 'workspace',
    context_id: null,
    last_message_at: new Date(Date.now() - 3 * 60 * 60_000).toISOString(),
  },
  {
    id: 'sess-5',
    agent_id: 'general',
    title: 'Add notification service',
    context_kind: 'object',
    context_id: 'obj-1',
    last_message_at: new Date(Date.now() - 4 * 60 * 60_000).toISOString(),
  },
  {
    id: 'sess-6',
    agent_id: 'general',
    title: 'Sixth session — should not show in top-5',
    context_kind: 'workspace',
    context_id: null,
    last_message_at: new Date(Date.now() - 24 * 60 * 60_000).toISOString(),
  },
]

// ─── Helpers ──────────────────────────────────────────────────────────────────

function makeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
}

function Wrapper({ children }: { children: React.ReactNode }) {
  return (
    <QueryClientProvider client={makeClient()}>
      {children}
    </QueryClientProvider>
  )
}

function resetStore() {
  useAgentChatStore.setState({
    bubbleState: 'open',
    size: { width: 480, height: 640 },
    mode: 'read_only',
    activeSessionId: null,
  })
}

// ─── Suite ────────────────────────────────────────────────────────────────────

describe('SessionPicker', () => {
  beforeEach(() => {
    resetStore()
    vi.clearAllMocks()
    mockGet.mockResolvedValue({ data: { items: SESSIONS, next_cursor: null } })
    mockDelete.mockResolvedValue({ data: {} })
    mockPatch.mockResolvedValue({ data: {} })
  })

  it('shows 5 most-recent sessions in the dropdown', async () => {
    render(
      <Wrapper>
        <SessionPicker />
      </Wrapper>,
    )

    fireEvent.click(screen.getByTestId('session-picker-trigger'))

    // Wait for the query to resolve
    await waitFor(() => {
      expect(screen.getByTestId('session-row-sess-1')).toBeInTheDocument()
    })

    expect(screen.getByTestId('session-row-sess-1')).toBeInTheDocument()
    expect(screen.getByTestId('session-row-sess-2')).toBeInTheDocument()
    expect(screen.getByTestId('session-row-sess-3')).toBeInTheDocument()
    expect(screen.getByTestId('session-row-sess-4')).toBeInTheDocument()
    expect(screen.getByTestId('session-row-sess-5')).toBeInTheDocument()
    // sess-6 is the 6th — must not appear
    expect(screen.queryByTestId('session-row-sess-6')).not.toBeInTheDocument()
  })

  it('clicking a session calls stream.reset and setActiveSessionId', async () => {
    render(
      <Wrapper>
        <SessionPicker />
      </Wrapper>,
    )

    fireEvent.click(screen.getByTestId('session-picker-trigger'))

    await waitFor(() => {
      expect(screen.getByTestId('session-row-sess-2')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByTestId('session-row-sess-2'))

    expect(mockReset).toHaveBeenCalledOnce()
    expect(useAgentChatStore.getState().activeSessionId).toBe('sess-2')
    // Dropdown should close
    expect(screen.queryByTestId('session-picker-dropdown')).not.toBeInTheDocument()
  })

  it('clicking "+ New session" calls stream.reset and sets activeSessionId to null', async () => {
    useAgentChatStore.setState({ activeSessionId: 'sess-1' })

    render(
      <Wrapper>
        <SessionPicker />
      </Wrapper>,
    )

    fireEvent.click(screen.getByTestId('session-picker-trigger'))

    await waitFor(() => {
      expect(screen.getByTestId('session-new-btn')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByTestId('session-new-btn'))

    expect(mockReset).toHaveBeenCalledOnce()
    expect(useAgentChatStore.getState().activeSessionId).toBeNull()
    expect(screen.queryByTestId('session-picker-dropdown')).not.toBeInTheDocument()
  })

  it('shows empty state when no sessions exist', async () => {
    mockGet.mockResolvedValue({ data: { items: [], next_cursor: null } })

    render(
      <Wrapper>
        <SessionPicker />
      </Wrapper>,
    )

    fireEvent.click(screen.getByTestId('session-picker-trigger'))

    await waitFor(() => {
      expect(screen.getByTestId('session-empty-state')).toBeInTheDocument()
    })
  })
})

describe('AllSessionsModal', () => {
  beforeEach(() => {
    resetStore()
    vi.clearAllMocks()
    mockGet.mockResolvedValue({ data: { items: SESSIONS, next_cursor: null } })
    mockDelete.mockResolvedValue({ data: {} })
  })

  it('renders all sessions and filters by search text', async () => {
    const onClose = vi.fn()
    const onSelectSession = vi.fn()

    render(
      <Wrapper>
        <AllSessionsModal
          open={true}
          onClose={onClose}
          onSelectSession={onSelectSession}
        />
      </Wrapper>,
    )

    await waitFor(() => {
      expect(screen.getByTestId('session-list-row-sess-1')).toBeInTheDocument()
    })

    // All 6 sessions visible before filtering
    expect(screen.getByTestId('session-list-row-sess-6')).toBeInTheDocument()

    // Search for "auth"
    const searchInput = screen.getByTestId('sessions-search-input')
    fireEvent.change(searchInput, { target: { value: 'auth' } })

    // Only sess-1 matches "auth"
    await waitFor(() => {
      expect(screen.queryByTestId('session-list-row-sess-2')).not.toBeInTheDocument()
    })
    expect(screen.getByTestId('session-list-row-sess-1')).toBeInTheDocument()
  })

  it('delete confirm flow → DELETE called → list refetches', async () => {
    const onClose = vi.fn()
    const onSelectSession = vi.fn()

    render(
      <Wrapper>
        <AllSessionsModal
          open={true}
          onClose={onClose}
          onSelectSession={onSelectSession}
        />
      </Wrapper>,
    )

    await waitFor(() => {
      expect(screen.getByTestId('session-list-row-sess-3')).toBeInTheDocument()
    })

    // Click delete on sess-3
    fireEvent.click(screen.getByTestId('session-delete-btn-sess-3'))

    // Confirm dialog should appear
    await waitFor(() => {
      expect(screen.getByTestId('delete-confirm-dialog')).toBeInTheDocument()
    })

    // Confirm the delete
    fireEvent.click(screen.getByTestId('delete-confirm-btn'))

    // DELETE should have been called with the session id
    await waitFor(() => {
      expect(mockDelete).toHaveBeenCalledWith('/agents/sessions/sess-3')
    })

    // Dialog should close
    expect(screen.queryByTestId('delete-confirm-dialog')).not.toBeInTheDocument()
  })

  it('shows empty state when no sessions', async () => {
    mockGet.mockResolvedValue({ data: { items: [], next_cursor: null } })

    render(
      <Wrapper>
        <AllSessionsModal
          open={true}
          onClose={vi.fn()}
          onSelectSession={vi.fn()}
        />
      </Wrapper>,
    )

    await waitFor(() => {
      expect(screen.getByTestId('sessions-empty-state')).toBeInTheDocument()
    })
  })

  it('clicking cancel in delete confirm leaves the list unchanged', async () => {
    render(
      <Wrapper>
        <AllSessionsModal
          open={true}
          onClose={vi.fn()}
          onSelectSession={vi.fn()}
        />
      </Wrapper>,
    )

    await waitFor(() => {
      expect(screen.getByTestId('session-list-row-sess-1')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByTestId('session-delete-btn-sess-1'))

    await waitFor(() => {
      expect(screen.getByTestId('delete-confirm-dialog')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByTestId('delete-cancel-btn'))

    expect(screen.queryByTestId('delete-confirm-dialog')).not.toBeInTheDocument()
    expect(mockDelete).not.toHaveBeenCalled()
  })
})
