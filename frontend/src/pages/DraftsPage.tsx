import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AppSidebar } from '../components/nav/AppSidebar'
import {
  useCreateDraft,
  useDeleteDraft,
  useDrafts,
} from '../hooks/use-api'
import type { Draft, DraftStatus } from '../types/model'

const STATUS_STYLE: Record<DraftStatus, { color: string; label: string }> = {
  open: { color: '#3b82f6', label: 'Open' },
  merged: { color: '#22c55e', label: 'Merged' },
  discarded: { color: '#737373', label: 'Discarded' },
}

export function DraftsPage() {
  const { data: drafts = [], isLoading } = useDrafts()
  const createDraft = useCreateDraft()
  const deleteDraft = useDeleteDraft()
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const navigate = useNavigate()

  const handleCreate = () => {
    if (!name.trim()) return
    createDraft.mutate(
      { name: name.trim(), description: description.trim() || null },
      {
        onSuccess: (draft) => {
          setCreating(false)
          setName('')
          setDescription('')
          navigate(`/drafts/${draft.id}`)
        },
      },
    )
  }

  return (
    <div className="flex h-screen bg-neutral-950 text-neutral-200">
      <AppSidebar />
      <div className="flex-1 overflow-y-auto p-8">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-xl font-semibold">Drafts</h1>
          <button
            onClick={() => setCreating(true)}
            className="text-sm bg-blue-600 hover:bg-blue-500 text-white px-3 py-1.5 rounded"
          >
            + New draft
          </button>
        </div>

        <p className="text-xs text-neutral-500 mb-6 max-w-2xl">
          A draft is a named proposal of changes that doesn't touch the live
          model until you apply it. Compare proposed objects side-by-side with
          the current state, then merge or discard.
        </p>

        {creating && (
          <div className="bg-neutral-900 border border-neutral-800 rounded-lg p-4 mb-6 max-w-xl">
            <div className="text-sm font-medium mb-3">New draft</div>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoFocus
              placeholder="e.g. Rename billing services"
              onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
              className="w-full bg-neutral-800 border border-neutral-700 rounded px-3 py-1.5 text-sm outline-none mb-2"
            />
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={2}
              placeholder="Why is this change being proposed?"
              className="w-full bg-neutral-800 border border-neutral-700 rounded px-3 py-1.5 text-sm outline-none resize-none mb-3"
            />
            <div className="flex gap-2">
              <button
                onClick={handleCreate}
                disabled={!name.trim() || createDraft.isPending}
                className="text-sm bg-blue-600 hover:bg-blue-500 text-white px-3 py-1 rounded disabled:opacity-40"
              >
                Create
              </button>
              <button
                onClick={() => {
                  setCreating(false)
                  setName('')
                  setDescription('')
                }}
                className="text-sm text-neutral-400 border border-neutral-700 px-3 py-1 rounded"
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {isLoading && <div className="text-sm text-neutral-500">Loading…</div>}
        {!isLoading && drafts.length === 0 && !creating && (
          <div className="text-sm text-neutral-500 italic">No drafts yet.</div>
        )}

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {drafts.map((d) => (
            <DraftCard
              key={d.id}
              draft={d}
              onOpen={() => navigate(`/drafts/${d.id}`)}
              onDelete={() => {
                if (confirm(`Delete draft "${d.name}"?`)) deleteDraft.mutate(d.id)
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
  onDelete,
}: {
  draft: Draft
  onOpen: () => void
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
          style={{ color: meta.color, background: `${meta.color}22`, border: `1px solid ${meta.color}55` }}
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
        <span>{draft.items.length} change{draft.items.length === 1 ? '' : 's'}</span>
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
  )
}
