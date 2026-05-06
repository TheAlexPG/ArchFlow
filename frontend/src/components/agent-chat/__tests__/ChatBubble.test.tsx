import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ChatBubble } from '../ChatBubble'
import { useAgentChatStore } from '../store'

// ─── jsdom shim: scrollIntoView is not implemented in jsdom ──────────────────
window.HTMLElement.prototype.scrollIntoView = vi.fn()

// ─── Mock useCurrentMemberAgentAccess ────────────────────────────────────────

let mockAgentAccess: 'full' | 'read_only' | 'none' = 'full'

vi.mock('../../../hooks/use-api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../hooks/use-api')>()
  return {
    ...actual,
    useCurrentMemberAgentAccess: () => mockAgentAccess,
  }
})

// ─── Mock useViewChange (it calls useNavigate which requires a Router) ───────

vi.mock('../hooks/use-view-change', () => ({
  useViewChange: () => undefined,
}))

// ─── Helpers ────────────────────────────────────────────────────────────────

function makeQueryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } })
}

function Wrapper({ children }: { children: ReactNode }) {
  return (
    <MemoryRouter>
      <QueryClientProvider client={makeQueryClient()}>
        {children}
      </QueryClientProvider>
    </MemoryRouter>
  )
}

function renderBubble() {
  return render(<ChatBubble />, { wrapper: Wrapper })
}

function resetStore() {
  useAgentChatStore.setState({
    bubbleState: 'closed',
    size: { width: 480, height: 640 },
    mode: 'read_only',
    activeSessionId: null,
  })
}

// ─── Mock matchMedia ─────────────────────────────────────────────────────────

function mockMatchMedia(mobileMatches: boolean) {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: mobileMatches,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  })
}

// ─── Suite ──────────────────────────────────────────────────────────────────

describe('ChatBubble', () => {
  beforeEach(() => {
    resetStore()
    // Default: desktop viewport
    mockMatchMedia(false)
    // Default: agent access enabled
    mockAgentAccess = 'full'
  })

  it('renders only the FAB button in closed state', () => {
    renderBubble()
    expect(screen.getByTestId('chat-bubble-fab')).toBeInTheDocument()
    expect(screen.queryByTestId('chat-panel')).not.toBeInTheDocument()
    expect(screen.queryByTestId('chat-header')).not.toBeInTheDocument()
  })

  it('clicking the FAB transitions to open state and renders the panel + header', () => {
    renderBubble()

    fireEvent.click(screen.getByTestId('chat-bubble-fab'))

    expect(useAgentChatStore.getState().bubbleState).toBe('open')
    // FAB disappears; panel appears
    expect(screen.queryByTestId('chat-bubble-fab')).not.toBeInTheDocument()
    expect(screen.getByTestId('chat-panel')).toBeInTheDocument()
    expect(screen.getByTestId('chat-header')).toBeInTheDocument()
    expect(screen.getByTestId('chat-panel')).toHaveAttribute('data-bubble-state', 'open')
  })

  it('clicking expand sets bubbleState to expanded and reflects on panel', () => {
    useAgentChatStore.setState({ bubbleState: 'open' })
    renderBubble()

    fireEvent.click(screen.getByTestId('btn-expand'))

    expect(useAgentChatStore.getState().bubbleState).toBe('expanded')
    expect(screen.getByTestId('chat-panel')).toHaveAttribute('data-bubble-state', 'expanded')
  })

  it('clicking close from open state hides the panel and shows FAB again', () => {
    useAgentChatStore.setState({ bubbleState: 'open' })
    renderBubble()

    fireEvent.click(screen.getByTestId('btn-close'))

    expect(useAgentChatStore.getState().bubbleState).toBe('closed')
    expect(screen.queryByTestId('chat-panel')).not.toBeInTheDocument()
    expect(screen.getByTestId('chat-bubble-fab')).toBeInTheDocument()
  })

  it('mode toggle changes mode in store', () => {
    useAgentChatStore.setState({ bubbleState: 'open', mode: 'read_only' })
    renderBubble()

    // Switch to Full
    fireEvent.click(screen.getByTestId('mode-toggle-full'))
    expect(useAgentChatStore.getState().mode).toBe('full')

    // Switch back to read_only
    fireEvent.click(screen.getByTestId('mode-toggle-read_only'))
    expect(useAgentChatStore.getState().mode).toBe('read_only')
  })

  it('mobile viewport (<768px) renders panel as bottom-sheet with no fixed width', () => {
    mockMatchMedia(true)
    useAgentChatStore.setState({ bubbleState: 'open' })

    renderBubble()

    const panel = screen.getByTestId('chat-panel')
    expect(panel).toBeInTheDocument()

    // Bottom-sheet positioning: inset-x-0 bottom-0 (no fixed pixel width from size)
    // The panel should NOT have an inline width style (mobile fills full width via CSS)
    expect(panel.style.width).toBe('')
  })

  // ── Agent access gate ──────────────────────────────────────────────────────

  it('renders null when current member agent_access is "none"', () => {
    mockAgentAccess = 'none'
    const { container } = renderBubble()

    // Nothing rendered — FAB and panel both absent
    expect(screen.queryByTestId('chat-bubble-fab')).not.toBeInTheDocument()
    expect(screen.queryByTestId('chat-panel')).not.toBeInTheDocument()
    expect(container.firstChild).toBeNull()
  })

  it('renders FAB when agent_access is "read_only"', () => {
    mockAgentAccess = 'read_only'
    renderBubble()

    expect(screen.getByTestId('chat-bubble-fab')).toBeInTheDocument()
  })

  it('renders FAB when agent_access is "full"', () => {
    mockAgentAccess = 'full'
    renderBubble()

    expect(screen.getByTestId('chat-bubble-fab')).toBeInTheDocument()
  })
})
