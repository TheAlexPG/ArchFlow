import { fireEvent, render } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { useUndoController } from './use-undo'

function Probe({ onUndo, onRedo = () => {} }: { onUndo: () => void; onRedo?: () => void }) {
  useUndoController({ diagramId: 'd1', onUndo, onRedo })
  return <input data-testid='input' />
}

describe('useUndoController', () => {
  it('fires onUndo when Cmd+Z pressed outside an input', () => {
    const onUndo = vi.fn()
    render(<Probe onUndo={onUndo} />)
    fireEvent.keyDown(document.body, { key: 'z', metaKey: true })
    expect(onUndo).toHaveBeenCalledOnce()
  })

  it('does NOT fire onUndo when focus is in an input', () => {
    const onUndo = vi.fn()
    const { getByTestId } = render(<Probe onUndo={onUndo} />)
    getByTestId('input').focus()
    fireEvent.keyDown(getByTestId('input'), { key: 'z', metaKey: true })
    expect(onUndo).not.toHaveBeenCalled()
  })
})
