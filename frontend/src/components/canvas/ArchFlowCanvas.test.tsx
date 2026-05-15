import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const h = vi.hoisted(() => ({
  reactFlowProps: null as null | Record<string, unknown>,
  backgroundProps: null as null | Record<string, unknown>,
  miniMapProps: null as null | Record<string, unknown>,
  commentComposeType: null as null | string,
  dependenciesFocusId: null as null | string,
  allObjects: [] as Array<{ id: string; name: string; type: string }>,
  diagramObjects: [] as Array<Record<string, unknown>>,
  connections: [] as Array<Record<string, unknown>>,
  currentNodes: [] as Array<{ id: string; data?: unknown }>,
  currentEdges: [] as Array<{ id: string; source?: string; target?: string; data?: unknown }>,
  setNodes: vi.fn(),
  setEdges: vi.fn(),
}))

vi.mock('@xyflow/react', () => ({
  ReactFlow: ({ children, ...props }: { children?: React.ReactNode }) => {
    h.reactFlowProps = props as Record<string, unknown>
    return <div data-testid="react-flow">{children}</div>
  },
  Background: (props: Record<string, unknown>) => {
    h.backgroundProps = props
    return <div data-testid="background" />
  },
  Controls: () => <div data-testid="controls" />,
  MiniMap: (props: Record<string, unknown>) => {
    h.miniMapProps = props
    return <div data-testid="minimap" />
  },
  ConnectionMode: { Loose: 'Loose' },
  MarkerType: { ArrowClosed: 'ArrowClosed' },
  useReactFlow: () => ({
    setNodes: h.setNodes,
    setEdges: h.setEdges,
    getNodes: () => h.currentNodes,
    getEdges: () => h.currentEdges,
    screenToFlowPosition: ({ x, y }: { x: number; y: number }) => ({ x, y }),
    fitView: vi.fn(),
  }),
}))

vi.mock('../../hooks/use-api', () => ({
  useConnections: () => ({ data: h.connections }),
  useCreateComment: () => ({ mutate: vi.fn() }),
  useCreateConnection: () => ({ mutate: vi.fn() }),
  useDeleteConnection: () => ({ mutate: vi.fn() }),
  useDiagramObjects: () => ({ data: h.diagramObjects }),
  useFlows: () => ({ data: [] }),
  useObjects: () => ({ data: h.allObjects }),
  useRemoveObjectFromDiagram: () => ({ mutate: vi.fn() }),
  useSaveDiagramPosition: () => ({ mutate: vi.fn() }),
  useUpdateObject: () => ({ mutate: vi.fn() }),
}))

vi.mock('../../hooks/use-diagrams', () => ({
  useDiagram: () => ({ data: null }),
}))

vi.mock('../../hooks/use-realtime', () => ({
  useDiagramSocket: () => ({
    cursors: {},
    selections: {},
    presence: [],
    sendCursor: vi.fn(),
    sendSelection: vi.fn(),
  }),
}))

vi.mock('../../hooks/use-undo', () => ({
  useUndoController: vi.fn(),
  useUndoMutation: () => ({ mutate: vi.fn() }),
  useRedoMutation: () => ({ mutate: vi.fn() }),
}))

vi.mock('../../lib/canvas-events', () => ({
  useFocusObjectListener: vi.fn(),
  useFocusConnectionListener: vi.fn(),
}))

vi.mock('../../stores/canvas-store', () => ({
  useCanvasStore: () => ({
    selectNode: vi.fn(),
    selectEdge: vi.fn(),
    dependenciesFocusId: h.dependenciesFocusId,
    setDependenciesFocus: vi.fn(),
    activeFilter: 'status',
    activeFilterValue: null,
    playingFlowId: null,
    playingStepIdx: 0,
    activeBranch: 'main',
    commentComposeType: h.commentComposeType,
    setCommentComposeType: vi.fn(),
    setRemoteNodeEditors: vi.fn(),
    setPresenceUsers: vi.fn(),
  }),
}))

vi.mock('./CanvasComments', () => ({
  CanvasComments: () => null,
}))

vi.mock('./CursorsOverlay', () => ({
  CursorsOverlay: () => null,
  RemoteSelectionsOverlay: () => null,
}))

vi.mock('./UndoToolbarButtons', () => ({
  UndoToolbarButtons: () => null,
}))

import { ArchFlowCanvas } from './ArchFlowCanvas'

describe('ArchFlowCanvas theming', () => {
  beforeEach(() => {
    h.reactFlowProps = null
    h.backgroundProps = null
    h.miniMapProps = null
    h.commentComposeType = null
    h.dependenciesFocusId = null
    h.allObjects = []
    h.diagramObjects = []
    h.connections = []
    h.currentNodes = []
    h.currentEdges = []
    h.setNodes.mockClear()
    h.setEdges.mockClear()
  })

  it('uses semantic theme variables for the canvas, grid, and minimap mask', () => {
    render(<ArchFlowCanvas diagramId="d1" />)

    expect(h.reactFlowProps?.style).toMatchObject({ background: 'var(--color-bg)' })
    expect(h.backgroundProps).toMatchObject({ color: 'var(--canvas-grid)' })
    expect(h.miniMapProps).toMatchObject({ maskColor: 'var(--minimap-mask)' })
  })

  it('uses semantic theme variables for floating canvas notices', () => {
    h.commentComposeType = 'risk'
    h.dependenciesFocusId = 'obj-1'
    h.allObjects = [{ id: 'obj-1', name: 'Checkout', type: 'system' }]

    render(<ArchFlowCanvas diagramId="d1" />)

    const composeNotice = screen.getByText('Click on the canvas to place a risk pin').closest('div')
    const dependencyNotice = screen.getByText(/Dependencies of/).closest('div')

    expect(composeNotice?.getAttribute('style')).toContain('background: var(--color-panel)')
    expect(composeNotice?.getAttribute('style')).toContain('border: 1px solid var(--color-accent-blue)')
    expect(composeNotice?.getAttribute('style')).toContain('color: var(--color-text-base)')
    expect(dependencyNotice?.getAttribute('style')).toContain('background: var(--color-panel)')
    expect(dependencyNotice?.getAttribute('style')).toContain('border: 1px solid var(--color-accent-blue)')
    expect(dependencyNotice?.getAttribute('style')).toContain('color: var(--color-text-base)')
  })

  it('prunes stale ReactFlow nodes when objects or placements disappear', () => {
    h.currentNodes = [
      { id: 'deleted-object', data: { object: { id: 'deleted-object', name: 'Deleted', type: 'system' } } },
    ]

    render(<ArchFlowCanvas diagramId="d1" />)

    expect(h.setNodes).toHaveBeenCalledWith([])
  })

  it('prunes stale ReactFlow edges when endpoint placements disappear', () => {
    h.currentEdges = [
      { id: 'stale:directed:a:b', source: 'a', target: 'b', data: { connId: 'stale' } },
    ]

    render(<ArchFlowCanvas diagramId="d1" />)

    expect(h.setEdges).toHaveBeenCalledWith([])
  })
})
