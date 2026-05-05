import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { ctxKey, useUndoStore } from '../../stores/undo-store'

vi.mock('../../hooks/use-undo', () => ({
  useDiagramHistory: () => ({ data: undefined }),
  useUndoTo: () => ({ mutate: vi.fn() }),
}))

import { HistoryPopover } from './HistoryPopover'

const ACTIVE_ENTRY = {
  id: 'e1',
  seq: 2,
  state: 'active' as const,
  target_type: 'object',
  target_id: 'obj1',
  forward_summary: 'Move system',
  created_at: '2026-05-04T00:00:00Z',
  updated_at: '2026-05-04T00:00:00Z',
  undone_at: null,
}

const UNDONE_ENTRY = {
  id: 'e2',
  seq: 1,
  state: 'undone' as const,
  target_type: 'object',
  target_id: 'obj1',
  forward_summary: 'Add actor',
  created_at: '2026-05-04T00:00:00Z',
  updated_at: '2026-05-04T00:00:00Z',
  undone_at: '2026-05-04T00:01:00Z',
}

describe('HistoryPopover', () => {
  it('renders entries from the store', () => {
    useUndoStore.getState().reset()
    useUndoStore.getState().setRecentEntries(ctxKey('d1'), [ACTIVE_ENTRY, UNDONE_ENTRY])

    render(<HistoryPopover diagramId="d1" onClose={vi.fn()} />)

    expect(screen.getByText(/Move system/)).toBeDefined()
    expect(screen.getByText(/Add actor/)).toBeDefined()
  })

  it('shows the cursor divider between active and undone entries', () => {
    useUndoStore.getState().reset()
    useUndoStore.getState().setRecentEntries(ctxKey('d1'), [ACTIVE_ENTRY, UNDONE_ENTRY])

    render(<HistoryPopover diagramId="d1" onClose={vi.fn()} />)

    expect(screen.getByTestId('history-cursor-divider')).toBeDefined()
  })

  it('does not show the divider when all entries are active', () => {
    useUndoStore.getState().reset()
    useUndoStore.getState().setRecentEntries(ctxKey('d1'), [ACTIVE_ENTRY])

    render(<HistoryPopover diagramId="d1" onClose={vi.fn()} />)

    expect(screen.queryByTestId('history-cursor-divider')).toBeNull()
  })

  it('renders the live diagram label when draftId is not set', () => {
    useUndoStore.getState().reset()

    render(<HistoryPopover diagramId="d1" onClose={vi.fn()} />)

    expect(screen.getByText(/live diagram/)).toBeDefined()
  })

  it('renders the draft label when draftId is provided', () => {
    useUndoStore.getState().reset()

    render(<HistoryPopover diagramId="d1" draftId="dr1" onClose={vi.fn()} />)

    expect(screen.getByText(/draft/)).toBeDefined()
  })
})
