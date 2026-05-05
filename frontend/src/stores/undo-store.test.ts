import { beforeEach, describe, expect, it } from 'vitest'
import { useUndoStore } from './undo-store'

const ctx = 'diagram-A:live'

describe('undo-store', () => {
  beforeEach(() => useUndoStore.getState().reset())

  it('starts empty for any context', () => {
    const s = useUndoStore.getState().getStackInfo(ctx)
    expect(s.cursorSeq).toBeNull()
    expect(s.undoCount).toBe(0)
    expect(s.redoCount).toBe(0)
  })

  it('setStackInfo merges fields without clobbering', () => {
    useUndoStore.getState().setStackInfo(ctx, { undoCount: 5 })
    useUndoStore.getState().setStackInfo(ctx, { redoCount: 2 })
    const s = useUndoStore.getState().getStackInfo(ctx)
    expect(s.undoCount).toBe(5)
    expect(s.redoCount).toBe(2)
  })

  it('applyUserUndoEvent updates cursor and counts', () => {
    useUndoStore.getState().applyUserUndoEvent(ctx, {
      cursor_seq: 12,
      redo_count: 3,
    })
    const s = useUndoStore.getState().getStackInfo(ctx)
    expect(s.cursorSeq).toBe(12)
    expect(s.redoCount).toBe(3)
  })
})
