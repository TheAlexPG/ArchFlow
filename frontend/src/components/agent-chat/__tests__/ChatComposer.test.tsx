import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ChatComposer } from '../ChatComposer'
import { useAgentChatStore } from '../store'

// ─── Mock useAgentStream ──────────────────────────────────────────────────────

const mockStartStream = vi.fn()
const mockReset = vi.fn()
const mockStreamState = {
  events: [],
  isStreaming: false,
  lastError: null,
  sessionId: null,
  isReconnecting: false,
  connectionLost: false,
  startStream: mockStartStream,
  cancel: vi.fn(),
  respond: vi.fn(),
  retry: vi.fn(),
  reset: mockReset,
}

vi.mock('../hooks/use-agent-stream', () => ({
  useAgentStream: () => mockStreamState,
}))

// ─── Mock useChatContext ──────────────────────────────────────────────────────

const mockCtx: { kind: string; id?: string } = { kind: 'workspace', id: 'ws-1' }

vi.mock('../hooks/use-chat-context', () => ({
  useChatContext: () => mockCtx,
}))

// ─── Mock react-router-dom (safety guard — useChatContext is mocked above) ───

vi.mock('react-router-dom', () => ({
  useParams: () => ({}),
  useSearchParams: () => [new URLSearchParams()],
}))

// ─── Helpers ─────────────────────────────────────────────────────────────────

function resetStore() {
  useAgentChatStore.setState({
    bubbleState: 'open',
    size: { width: 480, height: 640 },
    mode: 'read_only',
    activeSessionId: null,
  })
}

function typeInto(el: HTMLElement, value: string) {
  fireEvent.change(el, { target: { value } })
}

// ─── Suite ───────────────────────────────────────────────────────────────────

describe('ChatComposer', () => {
  beforeEach(() => {
    resetStore()
    vi.clearAllMocks()
    mockStreamState.isStreaming = false
    mockCtx.kind = 'workspace'
    mockCtx.id = 'ws-1'
  })

  it('renders textarea and send button', () => {
    render(<ChatComposer />)

    expect(screen.getByTestId('composer-textarea')).toBeInTheDocument()
    expect(screen.getByTestId('composer-send-btn')).toBeInTheDocument()
  })

  it('typing into textarea updates the draft', () => {
    render(<ChatComposer />)
    const textarea = screen.getByTestId('composer-textarea')

    typeInto(textarea, 'Hello world')

    expect(textarea).toHaveValue('Hello world')
  })

  it('⌘+Enter sends the message and clears the draft', () => {
    render(<ChatComposer />)
    const textarea = screen.getByTestId('composer-textarea')

    typeInto(textarea, 'Hello agent')
    fireEvent.keyDown(textarea, { key: 'Enter', metaKey: true })

    expect(mockStartStream).toHaveBeenCalledOnce()
    expect(mockStartStream).toHaveBeenCalledWith(
      'general',
      expect.objectContaining({ message: 'Hello agent' }),
    )
    expect(textarea).toHaveValue('')
  })

  it('Ctrl+Enter also sends the message (cross-platform shortcut)', () => {
    render(<ChatComposer />)
    const textarea = screen.getByTestId('composer-textarea')

    typeInto(textarea, 'Test ctrl')
    fireEvent.keyDown(textarea, { key: 'Enter', ctrlKey: true })

    expect(mockStartStream).toHaveBeenCalledOnce()
    expect(textarea).toHaveValue('')
  })

  it('Enter alone does NOT call startStream (allows newline)', () => {
    render(<ChatComposer />)
    const textarea = screen.getByTestId('composer-textarea')

    typeInto(textarea, 'Line one')
    fireEvent.keyDown(textarea, { key: 'Enter' })

    expect(mockStartStream).not.toHaveBeenCalled()
  })

  it('Esc calls store.close() to minimize the bubble', () => {
    render(<ChatComposer />)
    const textarea = screen.getByTestId('composer-textarea')

    fireEvent.keyDown(textarea, { key: 'Escape' })

    expect(useAgentChatStore.getState().bubbleState).toBe('closed')
  })

  it('textarea and send button are disabled when ctx.kind is "none"', () => {
    mockCtx.kind = 'none'
    delete mockCtx.id

    render(<ChatComposer />)

    expect(screen.getByTestId('composer-textarea')).toBeDisabled()
    expect(screen.getByTestId('composer-send-btn')).toBeDisabled()
  })

  it('/clear slash command calls stream.reset and does NOT call startStream', () => {
    render(<ChatComposer />)
    const textarea = screen.getByTestId('composer-textarea')

    typeInto(textarea, '/clear')
    fireEvent.keyDown(textarea, { key: 'Enter', metaKey: true })

    expect(mockReset).toHaveBeenCalledOnce()
    expect(mockStartStream).not.toHaveBeenCalled()
    expect(textarea).toHaveValue('')
  })

  it('shows red round cancel button while streaming and dispatches cancel on click', () => {
    mockStreamState.isStreaming = true

    render(<ChatComposer />)

    const cancelBtn = screen.getByTestId('composer-cancel-btn')
    expect(cancelBtn).toBeInTheDocument()
    expect(screen.queryByTestId('composer-send-btn')).not.toBeInTheDocument()

    fireEvent.click(cancelBtn)
    expect(mockStreamState.cancel).toHaveBeenCalledOnce()
  })
})
