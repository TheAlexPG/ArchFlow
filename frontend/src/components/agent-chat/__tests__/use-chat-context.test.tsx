import { renderHook } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useChatContext } from '../hooks/use-chat-context'

// ─── Mocks ──────────────────────────────────────────────────────────────────

// Mock canvas store — selectedNodeId defaults to null (no selection)
let mockSelectedNodeId: string | null = null

vi.mock('../../../stores/canvas-store', () => ({
  useCanvasStore: (selector: (s: { selectedNodeId: string | null }) => unknown) =>
    selector({ selectedNodeId: mockSelectedNodeId }),
}))

// Mock workspace store — currentWorkspaceId defaults to 'ws-id-123'
let mockWorkspaceId: string | null = 'ws-id-123'

vi.mock('../../../stores/workspace-store', () => ({
  useWorkspaceStore: (selector: (s: { currentWorkspaceId: string | null }) => unknown) =>
    selector({ currentWorkspaceId: mockWorkspaceId }),
}))

// ─── Helpers ────────────────────────────────────────────────────────────────

/** Renders the hook inside a MemoryRouter at `path`, matched by `route`. */
function renderInRoute(path: string, route: string) {
  const wrapper = ({ children }: { children: ReactNode }) => (
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path={route} element={<>{children}</>} />
      </Routes>
    </MemoryRouter>
  )
  return renderHook(() => useChatContext(), { wrapper })
}

// ─── Tests ──────────────────────────────────────────────────────────────────

beforeEach(() => {
  mockSelectedNodeId = null
  mockWorkspaceId = 'ws-id-123'
})

describe('useChatContext', () => {
  it('returns workspace context for / (authenticated overview)', () => {
    const { result } = renderInRoute('/', '/')
    expect(result.current).toEqual({ kind: 'workspace', id: 'ws-id-123' })
  })

  it('returns diagram context for /diagram/:diagramId', () => {
    const { result } = renderInRoute('/diagram/abc', '/diagram/:diagramId')
    expect(result.current).toEqual({ kind: 'diagram', id: 'abc', draft_id: undefined })
  })

  it('returns diagram context with draft_id for /diagram/:diagramId?draft=xyz', () => {
    const { result } = renderInRoute('/diagram/abc?draft=xyz', '/diagram/:diagramId')
    expect(result.current).toEqual({ kind: 'diagram', id: 'abc', draft_id: 'xyz' })
  })

  it('returns object context when canvas has a selected node on a diagram page', () => {
    mockSelectedNodeId = 'node-99'
    const { result } = renderInRoute('/diagram/abc', '/diagram/:diagramId')
    expect(result.current).toEqual({
      kind: 'object',
      id: 'node-99',
      parent_diagram_id: 'abc',
      draft_id: undefined,
    })
  })

  it('returns object context for /ws/:workspaceSlug/objects/:objectId (future route)', () => {
    const { result } = renderInRoute(
      '/ws/test/objects/obj1',
      '/ws/:workspaceSlug/objects/:objectId',
    )
    expect(result.current).toEqual({ kind: 'object', id: 'obj1' })
  })

  it('returns none when no workspace and no matching params', () => {
    mockWorkspaceId = null
    const { result } = renderInRoute('/login', '/login')
    expect(result.current).toEqual({ kind: 'none' })
  })

  // Regression: ChatBubble lives outside <Routes> so useParams returned {} and
  // every chat invocation reported context.kind = 'workspace' even when the
  // user was viewing a specific diagram. We now read the URL pathname directly.
  it('resolves diagram context when rendered OUTSIDE <Routes>', () => {
    const wrapper = ({ children }: { children: ReactNode }) => (
      <MemoryRouter initialEntries={['/diagram/base-system-id']}>
        {/* No <Routes> — mimics ChatBubble at App level. */}
        {children}
      </MemoryRouter>
    )
    const { result } = renderHook(() => useChatContext(), { wrapper })
    expect(result.current).toEqual({
      kind: 'diagram',
      id: 'base-system-id',
      draft_id: undefined,
    })
  })
})
