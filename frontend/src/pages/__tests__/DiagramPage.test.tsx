/**
 * DiagramPage tests — back-button navigation up the C4 hierarchy.
 *
 * Spec: clicking the back-arrow should navigate to the *parent* diagram
 * when the current diagram is part of a C4 chain (system → container →
 * component). Only when no parent exists (top-level diagram or breadcrumbs
 * not yet loaded) should the button fall back to the workspace overview.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// ─── Hoisted mock state ──────────────────────────────────────────────────────
//
// `vi.mock` factories run before any module-level code, so any state they
// reference must live inside the factory or be hoisted via `vi.hoisted`.
const h = vi.hoisted(() => ({
  navigate: vi.fn(),
  breadcrumbs: [] as Array<{ id: string; name: string; type: string }>,
  diagram: null as null | { id: string; name: string; type: string; draft_id: null },
}))

// ─── Mock react-router-dom ───────────────────────────────────────────────────

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>()
  return {
    ...actual,
    useNavigate: () => h.navigate,
    useParams: () => ({ diagramId: 'd-current' }),
  }
})

// ─── Mock data hooks ─────────────────────────────────────────────────────────

vi.mock('../../hooks/use-diagrams', () => ({
  useDiagram: () => ({ data: h.diagram }),
  useDiagramBreadcrumbs: () => h.breadcrumbs,
}))

vi.mock('../../hooks/use-api', () => ({
  useApplyDraft: () => ({ mutate: vi.fn(), isPending: false }),
  useCreateDraftFromDiagram: () => ({ mutate: vi.fn(), reset: vi.fn(), isPending: false, error: null }),
  useDiscardDraft: () => ({ mutate: vi.fn(), isPending: false }),
  useDraft: () => ({ data: null }),
  useDraftsForDiagram: () => ({ data: [] }),
}))

// ─── Stub heavy children — none of them are exercised here ───────────────────

vi.mock('../../components/canvas/ArchFlowCanvas', () => ({
  ArchFlowCanvas: () => <div data-testid="canvas-stub" />,
}))
vi.mock('../../components/diagram/DiagramAccessModal', () => ({
  DiagramAccessModal: () => null,
}))
vi.mock('../../components/drafts/CreateDraftModal', () => ({
  CreateDraftModal: () => null,
}))
vi.mock('../../components/canvas/AddObjectFAB', () => ({
  AddObjectFAB: () => null,
}))
vi.mock('../../components/toolbar/FilterToolbar', () => ({
  FilterToolbar: () => null,
}))
vi.mock('../../components/toolbar/FlowPlaybackBar', () => ({
  FlowPlaybackBar: () => null,
}))
vi.mock('../../components/toolbar/FlowsPanel', () => ({
  FlowsPanel: () => null,
}))
vi.mock('../../components/sidebar/EdgeSidebar', () => ({
  EdgeSidebar: () => null,
}))
vi.mock('../../components/sidebar/ObjectSidebar', () => ({
  ObjectSidebar: () => null,
}))
vi.mock('../../components/tree/ObjectTree', () => ({
  ObjectTree: () => null,
}))
vi.mock('../../components/nav/SearchModal', () => ({
  SearchModal: () => null,
}))

// ─── Stub stores ─────────────────────────────────────────────────────────────

vi.mock('../../stores/auth-store', () => ({
  useAuthStore: () => ({ logout: vi.fn() }),
}))

vi.mock('../../stores/canvas-store', () => ({
  useCanvasStore: () => ({
    selectedEdgeId: null,
    treeOpen: false,
    toggleTree: vi.fn(),
    presenceUsers: [],
  }),
}))

// ─── Import after mocks ──────────────────────────────────────────────────────

import { DiagramPage } from '../DiagramPage'

// ─── Helpers ─────────────────────────────────────────────────────────────────

function wrap(children: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/diagram/d-current']}>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

// ─── Tests ───────────────────────────────────────────────────────────────────

describe('DiagramPage back button', () => {
  beforeEach(() => {
    h.navigate.mockReset()
    h.diagram = { id: 'd-current', name: 'Components', type: 'component', draft_id: null }
    h.breadcrumbs = []
  })

  it('navigates to the parent diagram when the current diagram has a parent in the C4 chain', () => {
    h.breadcrumbs = [
      { id: 'd-system', name: 'System', type: 'system_landscape' },
      { id: 'd-container', name: 'Container', type: 'container' },
      { id: 'd-current', name: 'Components', type: 'component' },
    ]

    render(wrap(<DiagramPage />))
    fireEvent.click(screen.getByRole('button', { name: /back to parent diagram/i }))

    expect(h.navigate).toHaveBeenCalledWith('/diagram/d-container')
  })

  it('falls back to the workspace overview when there is no parent diagram', () => {
    h.breadcrumbs = [
      { id: 'd-current', name: 'Top Level', type: 'system_landscape' },
    ]

    render(wrap(<DiagramPage />))
    fireEvent.click(screen.getByRole('button', { name: /back to workspace/i }))

    expect(h.navigate).toHaveBeenCalledWith('/')
  })

  it('falls back to the workspace overview when breadcrumbs have not yet loaded (deep link)', () => {
    h.breadcrumbs = []

    render(wrap(<DiagramPage />))
    fireEvent.click(screen.getByRole('button', { name: /back to workspace/i }))

    expect(h.navigate).toHaveBeenCalledWith('/')
  })
})
