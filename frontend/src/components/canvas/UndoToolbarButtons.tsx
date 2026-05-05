import { useState } from 'react'

import { ctxKey, useUndoStore } from '../../stores/undo-store'
import { useUndoMutation, useRedoMutation } from '../../hooks/use-undo'
import { HistoryPopover } from './HistoryPopover'

interface Props {
  diagramId: string
  draftId?: string | null
}

const UndoIcon = () => (
  <svg
    width="16"
    height="16"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
  >
    <path d="M3 7v6h6" />
    <path d="M21 17a9 9 0 0 0-15-6.7L3 13" />
  </svg>
)

const RedoIcon = () => (
  <svg
    width="16"
    height="16"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
  >
    <path d="M21 7v6h-6" />
    <path d="M3 17a9 9 0 0 1 15-6.7L21 13" />
  </svg>
)

const ChevronDownIcon = () => (
  <svg
    width="14"
    height="14"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
  >
    <path d="M6 9l6 6 6-6" />
  </svg>
)

export function UndoToolbarButtons({ diagramId, draftId }: Props) {
  const [popoverOpen, setPopoverOpen] = useState(false)
  const stack = useUndoStore((s) => s.getStackInfo(ctxKey(diagramId, draftId)))

  const undoMut = useUndoMutation(diagramId, draftId)
  const redoMut = useRedoMutation(diagramId, draftId)

  const canUndo = stack.undoCount > 0 && !stack.isInFlight
  const canRedo = stack.redoCount > 0 && !stack.isInFlight

  const topLabel = stack.recentEntries.find((e) => e.state === 'active')?.forward_summary ?? ''
  const topUndoneLabel =
    stack.recentEntries.find((e) => e.state === 'undone')?.forward_summary ?? ''

  return (
    <div className="relative flex items-center gap-1">
      <button
        aria-label="Undo"
        title={canUndo ? `Undo: ${topLabel}` : 'Nothing to undo'}
        disabled={!canUndo}
        onClick={() => undoMut.mutate()}
        className="rounded px-2 py-1 disabled:opacity-40 hover:bg-surface-hi text-text-base"
      >
        <UndoIcon />
      </button>
      <button
        aria-label="Show history"
        onClick={() => setPopoverOpen((v) => !v)}
        className="rounded px-1 py-1 hover:bg-surface-hi text-text-base"
      >
        <ChevronDownIcon />
      </button>
      <button
        aria-label="Redo"
        title={canRedo ? `Redo: ${topUndoneLabel}` : 'Nothing to redo'}
        disabled={!canRedo}
        onClick={() => redoMut.mutate()}
        className="rounded px-2 py-1 disabled:opacity-40 hover:bg-surface-hi text-text-base"
      >
        <RedoIcon />
      </button>
      {popoverOpen && (
        <HistoryPopover
          diagramId={diagramId}
          draftId={draftId}
          onClose={() => setPopoverOpen(false)}
        />
      )}
    </div>
  )
}
