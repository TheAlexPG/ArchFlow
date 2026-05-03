/**
 * drafts-ux.test.tsx
 *
 * Test suite for agent-core-mvp-049:
 *   - WorkingInDropdown (in ChatHeader)
 *   - useViewChange hook
 *   - DraftCreatedBanner
 */

import { act, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ChatHeader } from '../ChatHeader'
import { DraftCreatedBanner } from '../DraftCreatedBanner'
import { useViewChange } from '../hooks/use-view-change'
import { useAgentChatStore } from '../store'
import type { AgentSSEEvent } from '../types'

// ─── Shared mutable mock state ────────────────────────────────────────────────

let mockCtxState: {
  kind: 'diagram' | 'object' | 'workspace' | 'none'
  id?: string
  draft_id?: string
  parent_diagram_id?: string
} = { kind: 'workspace', id: 'ws-1' }

let mockDrafts: { draft_id: string; draft_name: string; draft_status: string; source_diagram_id: string; forked_diagram_id: string }[] = []

let mockEvents: AgentSSEEvent[] = []

const mockNavigate = vi.fn()

// ─── Module mocks ─────────────────────────────────────────────────────────────

vi.mock('../hooks/use-chat-context', () => ({
  useChatContext: () => mockCtxState,
}))

vi.mock('../../../hooks/use-api', () => ({
  useDraftsForDiagram: (_id: string | undefined) => ({
    data: _id ? mockDrafts : undefined,
  }),
}))

vi.mock('../hooks/use-agent-stream', () => ({
  useAgentStream: () => ({
    events: mockEvents,
    isStreaming: false,
    lastError: null,
    sessionId: null,
    isReconnecting: false,
    connectionLost: false,
    startStream: vi.fn(),
    cancel: vi.fn(),
    respond: vi.fn(),
    retry: vi.fn(),
    reset: vi.fn(),
  }),
}))

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  }
})

// SessionPicker mock — avoids needing to stub its own hooks
vi.mock('../SessionPicker', () => ({
  SessionPicker: () => null,
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

function makeEvent(
  kind: AgentSSEEvent['kind'],
  payload: unknown,
  id = 1,
): AgentSSEEvent {
  return { id, kind, payload }
}

function renderInRouter(ui: ReactNode, path = '/') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="*" element={<>{ui}</>} />
      </Routes>
    </MemoryRouter>,
  )
}

function hookWrapper({ children }: { children: ReactNode }) {
  return (
    <MemoryRouter initialEntries={['/diagram/d1']}>
      <Routes>
        <Route path="*" element={<>{children}</>} />
      </Routes>
    </MemoryRouter>
  )
}

// ─── 1. WorkingInDropdown: shows "Live diagram" when no draft ─────────────────

describe('WorkingInDropdown', () => {
  beforeEach(() => {
    resetStore()
    vi.clearAllMocks()
    mockDrafts = []
    mockCtxState = { kind: 'diagram', id: 'diag-1', draft_id: undefined }
  })

  it('shows "Live diagram" option when no draft_id is set', () => {
    renderInRouter(<ChatHeader />)
    const select = screen.getByTestId('working-in-select')
    expect(select).toHaveValue('live')
    expect(screen.getByText('Live diagram')).toBeInTheDocument()
  })

  it('lists available drafts and selects the correct one', () => {
    mockDrafts = [
      {
        draft_id: 'draft-abc',
        draft_name: 'My Draft',
        draft_status: 'open',
        source_diagram_id: 'diag-1',
        forked_diagram_id: 'diag-fork-1',
      },
      {
        draft_id: 'draft-xyz',
        draft_name: 'Another Draft',
        draft_status: 'open',
        source_diagram_id: 'diag-1',
        forked_diagram_id: 'diag-fork-2',
      },
    ]
    mockCtxState = { kind: 'diagram', id: 'diag-1', draft_id: 'draft-abc' }

    renderInRouter(<ChatHeader />)
    const select = screen.getByTestId('working-in-select')
    expect(select).toHaveValue('draft-abc')
    expect(screen.getByText('My Draft')).toBeInTheDocument()
    expect(screen.getByText('Another Draft')).toBeInTheDocument()
  })

  it('clicking a draft option calls navigate with ?draft=<id>', () => {
    mockDrafts = [
      {
        draft_id: 'draft-abc',
        draft_name: 'My Draft',
        draft_status: 'open',
        source_diagram_id: 'diag-1',
        forked_diagram_id: 'diag-fork-1',
      },
    ]
    mockCtxState = { kind: 'diagram', id: 'diag-1', draft_id: undefined }

    renderInRouter(<ChatHeader />)
    const select = screen.getByTestId('working-in-select')

    fireEvent.change(select, { target: { value: 'draft-abc' } })
    expect(mockNavigate).toHaveBeenCalledWith('?draft=draft-abc')
  })

  it('selecting "live" calls navigate without draft query param', () => {
    mockDrafts = [
      {
        draft_id: 'draft-abc',
        draft_name: 'My Draft',
        draft_status: 'open',
        source_diagram_id: 'diag-1',
        forked_diagram_id: 'diag-fork-1',
      },
    ]
    mockCtxState = { kind: 'diagram', id: 'diag-1', draft_id: 'draft-abc' }

    renderInRouter(<ChatHeader />)
    const select = screen.getByTestId('working-in-select')

    fireEvent.change(select, { target: { value: 'live' } })
    // Should call navigate without a ?draft= param
    expect(mockNavigate).toHaveBeenCalled()
    const navArg: string = mockNavigate.mock.calls[0][0] as string
    expect(navArg).not.toContain('draft=')
  })

  it('is hidden when ctx.kind is not "diagram" or "object"', () => {
    mockCtxState = { kind: 'workspace', id: 'ws-1' }

    renderInRouter(<ChatHeader />)
    expect(screen.queryByTestId('working-in-dropdown')).not.toBeInTheDocument()
  })
})

// ─── 2. useViewChange: navigates on view_change event ─────────────────────────

describe('useViewChange', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockEvents = []
  })

  it('calls navigate when a view_change event targeting a diagram arrives', async () => {
    const { rerender } = renderHook(() => useViewChange(), { wrapper: hookWrapper })

    act(() => {
      mockEvents = [
        makeEvent('view_change', { reason: 'draft_created', to: { kind: 'diagram', id: 'd2', draft_id: 'dr-1' } }, 1),
      ]
    })

    rerender()

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/diagram/d2?draft=dr-1')
    })
  })

  it('navigates without draft param when no draft_id in view_change payload', async () => {
    const { rerender } = renderHook(() => useViewChange(), { wrapper: hookWrapper })

    act(() => {
      mockEvents = [
        makeEvent('view_change', { reason: 'context_switch', to: { kind: 'diagram', id: 'd3' } }, 2),
      ]
    })

    rerender()

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/diagram/d3')
    })
  })

  it('does not call navigate for non-view_change events', async () => {
    const { rerender } = renderHook(() => useViewChange(), { wrapper: hookWrapper })

    act(() => {
      mockEvents = [
        makeEvent('done', {}, 3),
      ]
    })

    rerender()

    await waitFor(() => {
      expect(mockNavigate).not.toHaveBeenCalled()
    })
  })
})

// ─── 3. DraftCreatedBanner ────────────────────────────────────────────────────

describe('DraftCreatedBanner', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockEvents = []
  })

  it('is hidden when no events', () => {
    renderInRouter(<DraftCreatedBanner />)
    expect(screen.queryByTestId('draft-created-banner')).not.toBeInTheDocument()
  })

  it('is hidden when view_change arrived but done has not', () => {
    mockEvents = [
      makeEvent('view_change', { reason: 'draft_created', to: { kind: 'diagram', id: 'd1', draft_id: 'dr-1' } }, 1),
    ]
    renderInRouter(<DraftCreatedBanner />)
    expect(screen.queryByTestId('draft-created-banner')).not.toBeInTheDocument()
  })

  it('appears after view_change(draft_created) + done', () => {
    mockEvents = [
      makeEvent('view_change', { reason: 'draft_created', to: { kind: 'diagram', id: 'd1', draft_id: 'dr-1' } }, 1),
      makeEvent('done', {}, 2),
    ]
    renderInRouter(<DraftCreatedBanner />)
    expect(screen.getByTestId('draft-created-banner')).toBeInTheDocument()
  })

  it('"Review & merge" link points to compare page', () => {
    mockEvents = [
      makeEvent('view_change', { reason: 'draft_created', to: { kind: 'diagram', id: 'd1', draft_id: 'dr-abc' } }, 1),
      makeEvent('done', {}, 2),
    ]
    renderInRouter(<DraftCreatedBanner />)
    const link = screen.getByTestId('draft-created-review-link')
    expect(link).toHaveAttribute('href', '/diagram/d1?draft=dr-abc&compare=1')
  })
})
