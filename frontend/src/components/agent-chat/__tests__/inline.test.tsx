// Tests for inline AI popovers (agent-core-mvp-045).
// Covers: loading skeleton, result render, close on outside click,
// close on Esc, "Open in chat →" button, hidden when agent_access='none'.

import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { InlineExplainerPopover } from '../inline/InlineExplainerPopover'
import { InlineResearcherPopover } from '../inline/InlineResearcherPopover'
import { useAgentChatStore } from '../store'
import { ObjectContextMenu } from '../../common/ObjectContextMenu'
import type { ModelObject } from '../../../types/model'

// ─── Helpers ────────────────────────────────────────────────────────────────

function makeAnchorEl(): HTMLElement {
  const el = document.createElement('button')
  el.getBoundingClientRect = () => ({
    top: 100, left: 200, right: 300, bottom: 120,
    width: 100, height: 20, x: 200, y: 100,
    toJSON: () => ({}),
  })
  document.body.appendChild(el)
  return el
}

function makeQueryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } })
}

function Wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={makeQueryClient()}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

const FAKE_OBJECT: ModelObject = {
  id: 'obj-1',
  name: 'Auth Service',
  type: 'app',
  scope: 'internal',
  status: 'live',
  c4_level: 'container',
  description: null,
  icon: null,
  parent_id: null,
  technology_ids: null,
  tags: null,
  owner_team: null,
  external_links: null,
  metadata: null,
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
}

// ─── Mock streamAgent ────────────────────────────────────────────────────────

vi.mock('../../../lib/agent-stream', () => ({
  streamAgent: vi.fn(({ onEvent, onClose }: {
    onEvent: (e: { id: number; kind: string; payload: unknown }) => void
    onClose: () => void
  }) => {
    onEvent({ id: 1, kind: 'token', payload: { text: 'Streamed detail text.' } })
    onClose()
  }),
}))

// ─── Mock API hooks used by ObjectContextMenu ────────────────────────────────

let mockAgentAccess: string | undefined = 'full'
const mockMeId = 'user-1'

vi.mock('../../../hooks/use-api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../hooks/use-api')>()
  return {
    ...actual,
    useMe: () => ({ data: { id: mockMeId, email: 'test@test.com', name: 'Test' } }),
    useWorkspaceMembers: () => ({
      data: [{
        user_id: 'user-1',
        email: 'test@test.com',
        name: 'Test',
        role: 'editor',
        agent_access: mockAgentAccess,
      }],
    }),
    useObjectDiagrams: () => ({ data: [] }),
    useCreateObject: () => ({ mutate: vi.fn() }),
    useAddObjectToDiagram: () => ({ mutate: vi.fn() }),
    useDeleteObject: () => ({ mutate: vi.fn() }),
  }
})

vi.mock('../../../hooks/use-diagrams', () => ({
  useObjectDiagrams: () => ({ data: [] }),
}))

const mockCanvasState = {
  selectNode: vi.fn(),
  setDependenciesFocus: vi.fn(),
  selectedNodeId: null as string | null,
}

vi.mock('../../../stores/workspace-store', () => {
  const mockState = { currentWorkspaceId: 'ws-1' }
  const store = (selector?: (s: typeof mockState) => unknown) =>
    selector ? selector(mockState) : mockState
  store.getState = () => mockState
  return { useWorkspaceStore: store }
})

vi.mock('../../../stores/auth-store', () => {
  const mockState = { accessToken: 'test-token' }
  const store = (selector?: (s: typeof mockState) => unknown) =>
    selector ? selector(mockState) : mockState
  store.getState = () => mockState
  return { useAuthStore: store }
})

vi.mock('../../../stores/canvas-store', () => ({
  useCanvasStore: (selector?: (s: typeof mockCanvasState) => unknown) =>
    selector ? selector(mockCanvasState) : mockCanvasState,
}))

// ─── Suite ──────────────────────────────────────────────────────────────────

describe('InlineExplainerPopover', () => {
  let anchorEl: HTMLElement

  beforeEach(() => {
    anchorEl = makeAnchorEl()
    useAgentChatStore.setState({ bubbleState: 'closed' })
    // Default: fetch resolves with a result
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ final_message: 'This is the Auth Service explanation.' }),
    })
  })

  it('shows loading skeleton then renders result', async () => {
    render(
      <Wrapper>
        <InlineExplainerPopover objectId="obj-1" onClose={vi.fn()} anchorEl={anchorEl} />
      </Wrapper>,
    )

    // Loading skeleton is shown immediately
    expect(screen.getByTestId('inline-explainer-loading')).toBeInTheDocument()

    // After fetch resolves, result appears
    await waitFor(() => {
      expect(screen.queryByTestId('inline-explainer-loading')).not.toBeInTheDocument()
      expect(screen.getByTestId('inline-explainer-result')).toBeInTheDocument()
    })
    expect(screen.getByTestId('inline-explainer-result').innerHTML).toContain('Auth Service explanation')
  })

  it('closes when clicking outside', async () => {
    const onClose = vi.fn()
    render(
      <Wrapper>
        <InlineExplainerPopover objectId="obj-1" onClose={onClose} anchorEl={anchorEl} />
      </Wrapper>,
    )

    // Wait for popover to mount
    await waitFor(() => expect(screen.getByTestId('inline-explainer-popover')).toBeInTheDocument())

    act(() => {
      fireEvent.mouseDown(document.body)
    })

    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('closes on Esc key', async () => {
    const onClose = vi.fn()
    render(
      <Wrapper>
        <InlineExplainerPopover objectId="obj-1" onClose={onClose} anchorEl={anchorEl} />
      </Wrapper>,
    )

    await waitFor(() => expect(screen.getByTestId('inline-explainer-popover')).toBeInTheDocument())

    fireEvent.keyDown(window, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('"Open in chat →" opens the chat bubble and calls onClose', async () => {
    const onClose = vi.fn()
    render(
      <Wrapper>
        <InlineExplainerPopover objectId="obj-1" onClose={onClose} anchorEl={anchorEl} />
      </Wrapper>,
    )

    await waitFor(() => expect(screen.getByTestId('inline-explainer-open-chat')).toBeInTheDocument())

    fireEvent.click(screen.getByTestId('inline-explainer-open-chat'))

    expect(useAgentChatStore.getState().bubbleState).toBe('open')
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})

describe('InlineResearcherPopover', () => {
  let anchorEl: HTMLElement

  beforeEach(() => {
    anchorEl = makeAnchorEl()
    useAgentChatStore.setState({ bubbleState: 'closed' })
  })

  it('streams result text from token events', async () => {
    render(
      <Wrapper>
        <InlineResearcherPopover objectId="obj-1" onClose={vi.fn()} anchorEl={anchorEl} />
      </Wrapper>,
    )

    await waitFor(() => {
      expect(screen.getByTestId('inline-researcher-result')).toBeInTheDocument()
    })
    expect(screen.getByTestId('inline-researcher-result').innerHTML).toContain('Streamed detail text')
  })
})

describe('AI items hidden when agent_access=none', () => {
  beforeEach(() => {
    mockAgentAccess = 'none'
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ([]),
    })
  })

  it('does not render AI explain / Get details menu items', async () => {
    render(
      <Wrapper>
        <ObjectContextMenu object={FAKE_OBJECT} />
      </Wrapper>,
    )

    // Open the menu
    const btn = screen.getByTitle('More actions')
    fireEvent.click(btn)

    await waitFor(() => {
      expect(screen.getByText('View in model')).toBeInTheDocument()
    })

    expect(screen.queryByText('AI explain')).not.toBeInTheDocument()
    expect(screen.queryByText('Get details')).not.toBeInTheDocument()
  })
})
