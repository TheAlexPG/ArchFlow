import { useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { AppSidebar } from '../components/nav/AppSidebar'
import {
  useAddDraftItem,
  useApplyDraft,
  useDeleteDraftItem,
  useDiscardDraft,
  useDraft,
  useObjects,
  useUpdateDraftItem,
} from '../hooks/use-api'
import { TYPE_ICONS, TYPE_LABELS } from '../components/canvas/node-utils'
import type { DraftItem, ModelObject, ObjectStatus, ObjectType } from '../types/model'

/**
 * Draft detail view.
 *
 * Shows draft metadata, list of proposed edits (draft items), and a
 * side-by-side diff (Live vs Proposed) for the currently selected item
 * where the proposed side is an editable form. Apply commits all
 * proposed states to live objects; Discard marks the draft discarded.
 */
export function DraftDetailPage() {
  const { draftId } = useParams<{ draftId: string }>()
  const navigate = useNavigate()
  const { data: draft } = useDraft(draftId || null)
  const { data: objects = [] } = useObjects()
  const [selectedItemId, setSelectedItemId] = useState<string | null>(null)
  const [picking, setPicking] = useState(false)
  const addItem = useAddDraftItem()
  const applyDraft = useApplyDraft()
  const discardDraft = useDiscardDraft()

  const objectMap = useMemo(() => new Map(objects.map((o) => [o.id, o])), [objects])

  if (!draft || !draftId) {
    return (
      <div className="flex h-screen bg-neutral-950 text-neutral-200">
        <AppSidebar />
        <div className="flex-1 p-8 text-sm text-neutral-500">Loading…</div>
      </div>
    )
  }

  const isReadOnly = draft.status !== 'open'
  const selectedItem = draft.items.find((i) => i.id === selectedItemId) ?? draft.items[0]

  const handleAddObject = (obj: ModelObject) => {
    addItem.mutate(
      {
        draftId,
        target_type: 'object',
        target_id: obj.id,
        proposed_state: {
          name: obj.name,
          type: obj.type,
          scope: obj.scope,
          status: obj.status,
          description: obj.description,
          technology: obj.technology,
          tags: obj.tags,
          owner_team: obj.owner_team,
        },
      },
      {
        onSuccess: (item) => {
          setSelectedItemId(item.id)
          setPicking(false)
        },
      },
    )
  }

  const handleApply = () => {
    if (!confirm(`Apply ${draft.items.length} change(s) to the live model?`)) return
    applyDraft.mutate(draftId, {
      onSuccess: () => navigate('/drafts'),
    })
  }

  const handleDiscard = () => {
    if (!confirm('Mark this draft as discarded? It will stay for reference but be read-only.')) return
    discardDraft.mutate(draftId)
  }

  const candidateObjects = objects.filter(
    (o) => !draft.items.some((i) => i.target_id === o.id),
  )

  return (
    <div className="flex h-screen bg-neutral-950 text-neutral-200">
      <AppSidebar />
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Header */}
        <div className="border-b border-neutral-800 p-6 flex items-start justify-between gap-4">
          <div>
            <button
              onClick={() => navigate('/drafts')}
              className="text-xs text-neutral-500 hover:text-neutral-200 mb-1"
            >
              ← All drafts
            </button>
            <h1 className="text-xl font-semibold flex items-center gap-2">
              {draft.name}
              <StatusPill status={draft.status} />
            </h1>
            {draft.description && (
              <p className="text-sm text-neutral-400 mt-1 max-w-3xl">
                {draft.description}
              </p>
            )}
          </div>
          {!isReadOnly && (
            <div className="flex gap-2">
              <button
                onClick={handleDiscard}
                disabled={discardDraft.isPending}
                className="text-sm text-neutral-400 border border-neutral-700 hover:border-neutral-500 px-3 py-1.5 rounded"
              >
                Discard
              </button>
              <button
                onClick={handleApply}
                disabled={draft.items.length === 0 || applyDraft.isPending}
                className="text-sm bg-green-600 hover:bg-green-500 text-white px-3 py-1.5 rounded disabled:opacity-40"
              >
                Apply ({draft.items.length})
              </button>
            </div>
          )}
        </div>

        <div className="flex flex-1 overflow-hidden">
          {/* Changes list */}
          <div className="w-72 border-r border-neutral-800 overflow-y-auto p-3">
            <div className="flex items-center justify-between mb-2">
              <div className="text-xs text-neutral-500 uppercase tracking-wide">
                Changes
              </div>
              {!isReadOnly && (
                <button
                  onClick={() => setPicking((v) => !v)}
                  className="text-xs text-blue-400 hover:text-blue-300"
                >
                  {picking ? 'Cancel' : '+ Add'}
                </button>
              )}
            </div>

            {picking && (
              <div className="mb-3 max-h-64 overflow-y-auto bg-neutral-900 border border-neutral-800 rounded">
                {candidateObjects.length === 0 ? (
                  <div className="text-xs text-neutral-600 p-2">
                    All objects are already in this draft.
                  </div>
                ) : (
                  candidateObjects.map((o) => (
                    <button
                      key={o.id}
                      onClick={() => handleAddObject(o)}
                      className="w-full text-left text-xs px-2 py-1.5 text-neutral-300 hover:bg-neutral-800 flex items-center gap-2"
                    >
                      <span className="opacity-50">{TYPE_ICONS[o.type]}</span>
                      <span className="truncate">{o.name}</span>
                    </button>
                  ))
                )}
              </div>
            )}

            {draft.items.length === 0 ? (
              <div className="text-xs text-neutral-500 italic p-2">
                {isReadOnly
                  ? 'No changes in this draft.'
                  : 'No changes yet. Click + Add to pick an object to edit.'}
              </div>
            ) : (
              draft.items.map((item) => {
                const obj = item.target_id ? objectMap.get(item.target_id) : null
                const proposedName = (item.proposed_state.name as string) || obj?.name || '(new)'
                const baselineName = (item.baseline?.name as string | undefined) || obj?.name
                const renamed = baselineName && baselineName !== proposedName
                const isSelected = selectedItem?.id === item.id
                return (
                  <button
                    key={item.id}
                    onClick={() => setSelectedItemId(item.id)}
                    className={`w-full text-left p-2 rounded mb-1 border ${
                      isSelected
                        ? 'bg-neutral-800 border-blue-500'
                        : 'border-transparent hover:bg-neutral-900'
                    }`}
                  >
                    <div className="text-xs font-medium text-neutral-200 truncate">
                      {proposedName}
                      {renamed && (
                        <span className="text-neutral-500 ml-1">
                          (was {baselineName})
                        </span>
                      )}
                    </div>
                    <div className="text-[10px] text-neutral-500">
                      {item.target_id ? 'Edit object' : 'New object'}
                    </div>
                  </button>
                )
              })
            )}
          </div>

          {/* Side-by-side diff */}
          <div className="flex-1 overflow-y-auto p-6">
            {selectedItem ? (
              <DiffPanel
                draftId={draftId}
                item={selectedItem}
                liveObject={
                  selectedItem.target_id
                    ? objectMap.get(selectedItem.target_id) ?? null
                    : null
                }
                readOnly={isReadOnly}
              />
            ) : (
              <div className="text-sm text-neutral-500 italic">
                Pick a change on the left to compare it with the live model.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function StatusPill({ status }: { status: 'open' | 'merged' | 'discarded' }) {
  const colors = { open: '#3b82f6', merged: '#22c55e', discarded: '#737373' }[status]
  return (
    <span
      className="text-[10px] px-2 py-0.5 rounded uppercase"
      style={{ color: colors, background: `${colors}22`, border: `1px solid ${colors}55` }}
    >
      {status}
    </span>
  )
}

// ── Side-by-side diff panel ─────────────────────────────────

const DIFF_FIELDS: { key: keyof DiffState; label: string }[] = [
  { key: 'name', label: 'Name' },
  { key: 'type', label: 'Type' },
  { key: 'status', label: 'Status' },
  { key: 'scope', label: 'Scope' },
  { key: 'description', label: 'Description' },
  { key: 'technology', label: 'Technology' },
  { key: 'tags', label: 'Tags' },
  { key: 'owner_team', label: 'Owner team' },
]

interface DiffState {
  name?: string
  type?: ObjectType
  status?: ObjectStatus
  scope?: string
  description?: string | null
  technology?: string[] | null
  tags?: string[] | null
  owner_team?: string | null
}

function DiffPanel({
  draftId,
  item,
  liveObject,
  readOnly,
}: {
  draftId: string
  item: DraftItem
  liveObject: ModelObject | null
  readOnly: boolean
}) {
  const updateItem = useUpdateDraftItem()
  const deleteItem = useDeleteDraftItem()
  const proposed = item.proposed_state as DiffState
  const baseline = (item.baseline as DiffState) || (liveObject as unknown as DiffState) || {}

  const [local, setLocal] = useState<DiffState>(proposed)

  // Keep local form synced when switching between items.
  useMemo(() => {
    setLocal(proposed)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item.id])

  const handleSave = () => {
    updateItem.mutate({
      draftId,
      itemId: item.id,
      proposed_state: local as Record<string, unknown>,
    })
  }

  const handleDelete = () => {
    if (!confirm('Remove this change from the draft?')) return
    deleteItem.mutate({ draftId, itemId: item.id })
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div>
          <div className="text-xs text-neutral-500 uppercase">Side-by-side</div>
          <div className="text-sm text-neutral-200">
            {liveObject?.name || (local.name as string) || 'Unnamed'}
          </div>
        </div>
        {!readOnly && (
          <div className="flex gap-2">
            <button
              onClick={handleDelete}
              className="text-xs text-red-400 border border-red-900/60 hover:bg-red-900/20 px-2 py-1 rounded"
            >
              Remove from draft
            </button>
            <button
              onClick={handleSave}
              disabled={updateItem.isPending}
              className="text-xs bg-blue-600 hover:bg-blue-500 text-white px-3 py-1 rounded"
            >
              Save changes
            </button>
          </div>
        )}
      </div>

      <div className="grid grid-cols-2 gap-6">
        <div>
          <div className="text-[10px] text-neutral-500 uppercase mb-2">Current (live)</div>
          <div className="bg-neutral-900 border border-neutral-800 rounded p-3 space-y-2">
            {DIFF_FIELDS.map(({ key, label }) => (
              <DisplayField key={key} label={label} value={baseline[key]} />
            ))}
          </div>
        </div>
        <div>
          <div className="text-[10px] uppercase mb-2" style={{ color: '#3b82f6' }}>
            Proposed (draft)
          </div>
          <div className="bg-neutral-900 border border-blue-900/50 rounded p-3 space-y-2">
            {DIFF_FIELDS.map(({ key, label }) => (
              <EditableField
                key={key}
                label={label}
                currentValue={baseline[key]}
                value={local[key]}
                readOnly={readOnly}
                onChange={(v) =>
                  setLocal((prev) => ({ ...prev, [key]: v }))
                }
                fieldKey={key}
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

function DisplayField({ label, value }: { label: string; value: unknown }) {
  return (
    <div>
      <div className="text-[10px] text-neutral-600 uppercase">{label}</div>
      <div className="text-xs text-neutral-300">{formatValue(value)}</div>
    </div>
  )
}

function EditableField({
  label,
  currentValue,
  value,
  readOnly,
  onChange,
  fieldKey,
}: {
  label: string
  currentValue: unknown
  value: unknown
  readOnly: boolean
  onChange: (v: unknown) => void
  fieldKey: keyof DiffState
}) {
  const changed = JSON.stringify(currentValue ?? null) !== JSON.stringify(value ?? null)

  const input = (() => {
    if (fieldKey === 'type') {
      return (
        <select
          value={String(value ?? 'system')}
          onChange={(e) => onChange(e.target.value)}
          disabled={readOnly}
          className="w-full bg-neutral-800 border border-neutral-700 rounded px-2 py-1 text-xs text-neutral-200"
        >
          {Object.entries(TYPE_LABELS).map(([k, l]) => (
            <option key={k} value={k}>
              {l}
            </option>
          ))}
        </select>
      )
    }
    if (fieldKey === 'status') {
      return (
        <select
          value={String(value ?? 'live')}
          onChange={(e) => onChange(e.target.value)}
          disabled={readOnly}
          className="w-full bg-neutral-800 border border-neutral-700 rounded px-2 py-1 text-xs text-neutral-200"
        >
          {['live', 'future', 'deprecated', 'removed'].map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      )
    }
    if (fieldKey === 'scope') {
      return (
        <select
          value={String(value ?? 'internal')}
          onChange={(e) => onChange(e.target.value)}
          disabled={readOnly}
          className="w-full bg-neutral-800 border border-neutral-700 rounded px-2 py-1 text-xs text-neutral-200"
        >
          <option value="internal">Internal</option>
          <option value="external">External</option>
        </select>
      )
    }
    if (fieldKey === 'technology' || fieldKey === 'tags') {
      const arr = Array.isArray(value) ? value : []
      return (
        <input
          value={arr.join(', ')}
          onChange={(e) =>
            onChange(
              e.target.value
                .split(',')
                .map((s) => s.trim())
                .filter(Boolean),
            )
          }
          disabled={readOnly}
          placeholder="comma, separated"
          className="w-full bg-neutral-800 border border-neutral-700 rounded px-2 py-1 text-xs text-neutral-200"
        />
      )
    }
    if (fieldKey === 'description') {
      return (
        <textarea
          value={String(value ?? '')}
          onChange={(e) => onChange(e.target.value)}
          disabled={readOnly}
          rows={3}
          className="w-full bg-neutral-800 border border-neutral-700 rounded px-2 py-1 text-xs text-neutral-200 resize-none"
        />
      )
    }
    // name / owner_team
    return (
      <input
        value={String(value ?? '')}
        onChange={(e) => onChange(e.target.value || null)}
        disabled={readOnly}
        className="w-full bg-neutral-800 border border-neutral-700 rounded px-2 py-1 text-xs text-neutral-200"
      />
    )
  })()

  return (
    <div>
      <div className="flex items-center gap-1">
        <div className="text-[10px] text-neutral-600 uppercase">{label}</div>
        {changed && (
          <span className="text-[9px] text-blue-400" title="Differs from live">
            ● changed
          </span>
        )}
      </div>
      {input}
    </div>
  )
}

function formatValue(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—'
  if (Array.isArray(v)) return v.length === 0 ? '—' : v.join(', ')
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}
