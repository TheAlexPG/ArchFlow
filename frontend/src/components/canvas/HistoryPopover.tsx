import { useEffect } from 'react'

import { ctxKey, useUndoStore, type HistoryEntry } from '../../stores/undo-store'
import { useDiagramHistory, useUndoTo } from '../../hooks/use-undo'

interface Props {
  diagramId: string
  draftId?: string | null
  onClose: () => void
}

export function HistoryPopover({ diagramId, draftId, onClose }: Props) {
  const ctx = ctxKey(diagramId, draftId)
  const stack = useUndoStore((s) => s.getStackInfo(ctx))
  useDiagramHistory(diagramId, draftId, true)
  const undoTo = useUndoTo(diagramId, draftId)

  useEffect(() => {
    const onEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onEsc)
    return () => window.removeEventListener('keydown', onEsc)
  }, [onClose])

  const entries = stack.recentEntries
  // entries are reverse-seq sorted from the backend (newest first).
  // cursorIndex is the boundary: items above are 'active' (will be undone),
  // items below are 'undone' (will be redone). The first 'undone' index =
  // boundary; -1 means everything is active (no redo).
  const cursorIndex = entries.findIndex((e) => e.state === 'undone')
  const boundary = cursorIndex === -1 ? entries.length : cursorIndex

  const handleClick = (entry: HistoryEntry, indexFromTop: number) => {
    // pathLength = absolute distance from the cursor to the click target.
    // Active above the boundary: distance = boundary - indexFromTop
    // Undone below the boundary: distance = indexFromTop - boundary + 1
    const pathLength =
      entry.state === 'active'
        ? boundary - indexFromTop
        : indexFromTop - boundary + 1
    undoTo.mutate({ entryId: entry.id, expectedPathLength: Math.abs(pathLength) })
  }

  return (
    <div
      role="menu"
      aria-label="My history"
      className="absolute top-full mt-2 w-80 rounded border border-border-base bg-panel shadow-lg z-50"
    >
      <div className="px-3 py-2 border-b border-border-base text-sm font-medium text-text-base">
        My history · {draftId ? 'draft' : 'live diagram'}
      </div>
      <ul className="max-h-96 overflow-y-auto">
        {entries.map((e, i) => (
          <li key={e.id}>
            {i === cursorIndex && i !== 0 && (
              <div
                data-testid="history-cursor-divider"
                className="border-t border-dashed border-border-hi my-1 mx-3"
              />
            )}
            <button
              onClick={() => handleClick(e, i)}
              className={`w-full text-left px-3 py-1.5 text-sm hover:bg-surface-hi ${
                e.state === 'undone' ? 'text-text-3' : 'text-text-base'
              }`}
            >
              {e.state === 'active' ? '↻ ' : '↶ '}
              {e.forward_summary}
            </button>
          </li>
        ))}
      </ul>
      <div className="px-3 py-2 border-t border-border-base text-xs text-text-3">
        Entries older than 3 days expire
      </div>
    </div>
  )
}
