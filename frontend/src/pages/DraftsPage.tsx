import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AppSidebar } from '../components/nav/AppSidebar'
import { useDeleteDraft, useDrafts } from '../hooks/use-api'
import type { Draft, DraftStatus } from '../types/model'

const STATUS_STYLE: Record<DraftStatus, { color: string; label: string }> = {
  open: { color: '#3b82f6', label: 'Open' },
  merged: { color: '#22c55e', label: 'Merged' },
  discarded: { color: '#737373', label: 'Discarded' },
}

export function DraftsPage() {
  const { data: drafts = [], isLoading } = useDrafts()
  const deleteDraft = useDeleteDraft()
  const navigate = useNavigate()
  const [filter, setFilter] = useState<'all' | DraftStatus>('all')

  const visible = drafts.filter((d) => filter === 'all' || d.status === filter)

  return (
    <div className="flex h-screen bg-neutral-950 text-neutral-200">
      <AppSidebar />
      <div className="flex-1 overflow-y-auto p-8">
        <div className="flex items-center justify-between mb-4">
          <h1 className="text-xl font-semibold">Drafts</h1>
          <div className="flex gap-1">
            {(['all', 'open', 'merged', 'discarded'] as const).map((s) => (
              <button
                key={s}
                onClick={() => setFilter(s)}
                className={`text-xs px-3 py-1 rounded capitalize ${
                  filter === s
                    ? 'bg-neutral-700 text-neutral-100'
                    : 'text-neutral-500 hover:text-neutral-300'
                }`}
              >
                {s}
              </button>
            ))}
          </div>
        </div>

        <p className="text-xs text-neutral-500 mb-6 max-w-3xl">
          A draft is a forked copy of a diagram. Open any diagram → click{' '}
          <span className="text-neutral-300">✎ Draft</span> in the header → you
          get a private sandbox where you can redraw without touching the live
          model. When the feature is ready, hit <b>Apply</b> and the changes
          land on the source diagram.
        </p>

        {isLoading && <div className="text-sm text-neutral-500">Loading…</div>}
        {!isLoading && visible.length === 0 && (
          <div className="text-sm text-neutral-500 italic">
            No drafts yet. Start one from any diagram.
          </div>
        )}

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {visible.map((d) => (
            <DraftCard
              key={d.id}
              draft={d}
              // Clicking the card takes you to the compare view — that's
              // where the diff is visible. Editing the fork is a separate
              // action on the card for open drafts.
              onOpen={() => navigate(`/drafts/${d.id}`)}
              onEdit={
                d.status === 'open' && d.forked_diagram_id
                  ? () => navigate(`/diagram/${d.forked_diagram_id}`)
                  : undefined
              }
              onDelete={() => {
                if (confirm(`Delete draft "${d.name}" (and its fork)?`))
                  deleteDraft.mutate(d.id)
              }}
            />
          ))}
        </div>
      </div>
    </div>
  )
}

function DraftCard({
  draft,
  onOpen,
  onEdit,
  onDelete,
}: {
  draft: Draft
  onOpen: () => void
  onEdit?: () => void
  onDelete: () => void
}) {
  const meta = STATUS_STYLE[draft.status]
  return (
    <div
      onClick={onOpen}
      className="bg-neutral-900 border border-neutral-800 hover:border-neutral-700 rounded-lg p-4 cursor-pointer"
    >
      <div className="flex items-start justify-between mb-2">
        <div className="text-sm font-medium text-neutral-100 truncate flex-1">
          {draft.name}
        </div>
        <span
          className="text-[10px] px-2 py-0.5 rounded"
          style={{
            color: meta.color,
            background: `${meta.color}22`,
            border: `1px solid ${meta.color}55`,
          }}
        >
          {meta.label}
        </span>
      </div>
      {draft.description && (
        <div className="text-xs text-neutral-400 mb-2 line-clamp-2">
          {draft.description}
        </div>
      )}
      <div className="text-[10px] text-neutral-600 flex items-center justify-between">
        <span>
          {draft.status === 'open'
            ? 'Click to compare with source'
            : `Archived ${new Date(draft.updated_at).toLocaleDateString()}`}
        </span>
        <div className="flex items-center gap-2">
          {onEdit && (
            <button
              onClick={(e) => {
                e.stopPropagation()
                onEdit()
              }}
              className="text-neutral-400 hover:text-blue-400"
            >
              ✎ Edit fork
            </button>
          )}
          <button
            onClick={(e) => {
              e.stopPropagation()
              onDelete()
            }}
            className="text-neutral-600 hover:text-red-400"
          >
            Delete
          </button>
        </div>
      </div>
    </div>
  )
}
