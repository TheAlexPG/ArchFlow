import { render } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { ctxKey, useUndoStore } from '../../stores/undo-store'

vi.mock('../../hooks/use-undo', () => ({
  useUndoMutation: () => ({ mutate: vi.fn() }),
  useRedoMutation: () => ({ mutate: vi.fn() }),
}))

import { UndoToolbarButtons } from './UndoToolbarButtons'

describe('UndoToolbarButtons', () => {
  it('disables undo and redo when stack is empty', () => {
    useUndoStore.getState().reset()
    const { getByLabelText } = render(<UndoToolbarButtons diagramId="d1" />)
    expect(getByLabelText('Undo')).toBeDisabled()
    expect(getByLabelText('Redo')).toBeDisabled()
  })

  it('enables undo when undoCount > 0', () => {
    useUndoStore.getState().reset()
    useUndoStore.getState().setStackInfo(ctxKey('d1'), { undoCount: 3 })
    const { getByLabelText } = render(<UndoToolbarButtons diagramId="d1" />)
    expect(getByLabelText('Undo')).not.toBeDisabled()
  })

  it('enables redo when redoCount > 0', () => {
    useUndoStore.getState().reset()
    useUndoStore.getState().setStackInfo(ctxKey('d1'), { redoCount: 2 })
    const { getByLabelText } = render(<UndoToolbarButtons diagramId="d1" />)
    expect(getByLabelText('Redo')).not.toBeDisabled()
  })

  it('disables undo when isInFlight is true even if undoCount > 0', () => {
    useUndoStore.getState().reset()
    useUndoStore.getState().setStackInfo(ctxKey('d1'), { undoCount: 1, isInFlight: true })
    const { getByLabelText } = render(<UndoToolbarButtons diagramId="d1" />)
    expect(getByLabelText('Undo')).toBeDisabled()
  })

  it('uses draftId in context key when provided', () => {
    useUndoStore.getState().reset()
    useUndoStore.getState().setStackInfo(ctxKey('d1', 'dr1'), { undoCount: 1 })
    const { getByLabelText } = render(<UndoToolbarButtons diagramId="d1" draftId="dr1" />)
    expect(getByLabelText('Undo')).not.toBeDisabled()
  })

  it('Show history button is always enabled', () => {
    useUndoStore.getState().reset()
    const { getByLabelText } = render(<UndoToolbarButtons diagramId="d1" />)
    expect(getByLabelText('Show history')).not.toBeDisabled()
  })
})
