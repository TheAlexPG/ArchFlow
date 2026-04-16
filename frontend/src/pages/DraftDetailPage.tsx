import { ReactFlowProvider, type Viewport } from '@xyflow/react'
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { CompareCanvas } from '../components/drafts/CompareCanvas'
import { AppSidebar } from '../components/nav/AppSidebar'
import {
  useApplyDraft,
  useDiscardDraft,
  useDraft,
  useDraftDiff,
} from '../hooks/use-api'
import { useDiagram } from '../hooks/use-diagrams'

/**
 * Side-by-side compare page. Left: the live source. Right: the forked draft.
 * Both canvases are read-only, their pan/zoom are synchronised, and every
 * node/edge is outlined by its diff status (new / modified / deleted).
 *
 * The user acts on the diff from here: Apply merges the fork into the
 * source, Discard throws the fork away, Edit fork jumps to the editable
 * draft canvas.
 */
export function DraftDetailPage() {
  const { draftId } = useParams<{ draftId: string }>()
  const navigate = useNavigate()
  const { data: draft } = useDraft(draftId || null)
  const { data: sourceDiagram } = useDiagram(draft?.source_diagram_id ?? undefined)
  const { data: diff } = useDraftDiff(
    draft?.status === 'open' ? draft.id : null,
  )
  const applyDraft = useApplyDraft()
  const discardDraft = useDiscardDraft()

  // Shared viewport across both compare canvases. Whichever side the mouse
  // is currently over becomes the "driver" and the other follows. Null
  // until the first pan/zoom — before that, both sides fit independently.
  const [viewport, setViewport] = useState<Viewport | null>(null)
  const [activeSide, setActiveSide] = useState<'source' | 'fork' | null>(null)

  if (!draft) {
    return (
      <div className="flex h-screen bg-neutral-950 text-neutral-200">
        <AppSidebar />
        <div className="flex-1 p-8 text-sm text-neutral-500">Loading…</div>
      </div>
    )
  }

  const isOpen = draft.status === 'open'
  const canCompare =
    isOpen && !!draft.forked_diagram_id && !!draft.source_diagram_id

  const handleApply = () => {
    if (!confirm(`Apply "${draft.name}" to the source diagram?`)) return
    applyDraft.mutate(draft.id, {
      onSuccess: () => {
        if (draft.source_diagram_id)
          navigate(`/diagram/${draft.source_diagram_id}`)
        else navigate('/drafts')
      },
    })
  }

  const handleDiscard = () => {
    if (!confirm('Discard this draft? The forked diagram will be deleted.'))
      return
    discardDraft.mutate(draft.id)
  }

  return (
    <div className="flex h-screen bg-neutral-950 text-neutral-200">
      <AppSidebar />
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Header */}
        <div className="border-b border-neutral-800 p-4 flex items-start justify-between gap-4 bg-neutral-950">
          <div className="min-w-0">
            <button
              onClick={() => navigate('/drafts')}
              className="text-xs text-neutral-500 hover:text-neutral-200 mb-1"
            >
              ← All drafts
            </button>
            <div className="text-lg font-semibold flex items-center gap-2">
              <span>{draft.name}</span>
              {draft.status !== 'open' && (
                <span
                  className="text-[10px] px-2 py-0.5 rounded"
                  style={{
                    color: draft.status === 'merged' ? '#22c55e' : '#737373',
                    background:
                      draft.status === 'merged' ? '#22c55e22' : '#73737322',
                    border: `1px solid ${draft.status === 'merged' ? '#22c55e55' : '#52525255'}`,
                  }}
                >
                  {draft.status}
                </span>
              )}
            </div>
            {draft.description && (
              <div className="text-xs text-neutral-400 mt-0.5 max-w-2xl">
                {draft.description}
              </div>
            )}
          </div>
          {isOpen && (
            <div className="flex gap-2 flex-shrink-0">
              {draft.forked_diagram_id && (
                <button
                  onClick={() =>
                    navigate(`/diagram/${draft.forked_diagram_id}`)
                  }
                  className="text-sm bg-neutral-800 hover:bg-neutral-700 text-neutral-200 px-3 py-1.5 rounded border border-neutral-700"
                >
                  ✎ Edit fork
                </button>
              )}
              <button
                onClick={handleDiscard}
                className="text-sm text-neutral-400 border border-neutral-700 hover:border-neutral-500 px-3 py-1.5 rounded"
              >
                Discard
              </button>
              <button
                onClick={handleApply}
                disabled={applyDraft.isPending}
                className="text-sm bg-green-600 hover:bg-green-500 text-white px-3 py-1.5 rounded disabled:opacity-40"
              >
                Apply to source
              </button>
            </div>
          )}
        </div>

        {/* Summary strip — only when there's a diff to show */}
        {canCompare && diff && <DiffSummaryStrip diff={diff} />}

        {canCompare ? (
          <div
            className="flex-1 grid grid-cols-2 gap-px bg-neutral-800 overflow-hidden"
            style={{ position: 'relative' }}
          >
            <div
              className="bg-neutral-950 flex flex-col relative overflow-hidden"
              onMouseEnter={() => setActiveSide('source')}
              onMouseLeave={() =>
                setActiveSide((s) => (s === 'source' ? null : s))
              }
            >
              <SideHeader
                label="Source (live)"
                name={sourceDiagram?.name ?? 'live'}
                color="#737373"
              />
              <div className="flex-1 relative">
                <ReactFlowProvider>
                  <CompareCanvas
                    diagramId={draft.source_diagram_id!}
                    side="source"
                    diff={diff}
                    draftId={null}
                    isActive={activeSide === 'source'}
                    viewport={viewport}
                    onViewportChange={setViewport}
                    movedOnFork={new Set(diff?.moved_on_fork ?? [])}
                    resizedOnFork={new Set(diff?.resized_on_fork ?? [])}
                  />
                </ReactFlowProvider>
              </div>
            </div>
            <div
              className="bg-neutral-950 flex flex-col relative overflow-hidden"
              onMouseEnter={() => setActiveSide('fork')}
              onMouseLeave={() =>
                setActiveSide((s) => (s === 'fork' ? null : s))
              }
              style={{
                boxShadow: 'inset 0 0 0 2px rgba(59, 130, 246, 0.35)',
              }}
            >
              <SideHeader
                label="Draft (proposed)"
                name={draft.name}
                color="#3b82f6"
              />
              <div className="flex-1 relative">
                <ReactFlowProvider>
                  <CompareCanvas
                    diagramId={draft.forked_diagram_id!}
                    side="fork"
                    diff={diff}
                    draftId={draft.id}
                    isActive={activeSide === 'fork'}
                    viewport={viewport}
                    onViewportChange={setViewport}
                    movedOnFork={new Set(diff?.moved_on_fork ?? [])}
                    resizedOnFork={new Set(diff?.resized_on_fork ?? [])}
                  />
                </ReactFlowProvider>
              </div>
            </div>
          </div>
        ) : (
          <div className="flex-1 p-8">
            <div className="text-sm text-neutral-400">
              {draft.status === 'merged'
                ? 'This draft was applied. The fork has been removed.'
                : draft.status === 'discarded'
                  ? 'This draft was discarded. The fork has been removed.'
                  : 'No forked diagram available.'}
            </div>
          </div>
        )}

        {canCompare && (
          <div className="border-t border-neutral-800 bg-neutral-950 px-4 py-2 text-[11px] text-neutral-500 flex items-center gap-4 flex-shrink-0">
            <LegendDot color="#22c55e" label="New" />
            <LegendDot color="#f59e0b" label="Modified" />
            <LegendDot color="#ef4444" label="Deleted" />
            <LegendDot color="#f59e0b" dashed label="Moved / resized" />
            <div className="flex-1" />
            <span>Hovered side drives pan/zoom; the other follows.</span>
          </div>
        )}
      </div>
    </div>
  )
}

function SideHeader({
  label,
  name,
  color,
}: {
  label: string
  name: string
  color: string
}) {
  return (
    <div
      className="px-3 py-2 text-[11px] border-b border-neutral-800 flex items-center gap-2 bg-neutral-950 flex-shrink-0"
      style={{ color }}
    >
      <span style={{ textTransform: 'uppercase', letterSpacing: '0.08em' }}>
        {label}
      </span>
      <span style={{ color: '#525252' }}>·</span>
      <span style={{ color: '#d4d4d4', fontWeight: 500 }}>{name}</span>
    </div>
  )
}

function DiffSummaryStrip({
  diff,
}: {
  diff: import('../types/model').DraftDiff
}) {
  const s = diff.summary
  const totalChanges =
    s.added_objects +
    s.modified_objects +
    s.deleted_objects +
    s.added_connections +
    s.modified_connections +
    s.deleted_connections +
    s.moved_objects +
    s.resized_objects
  return (
    <div
      className="flex items-center gap-4 px-4 py-1.5 border-b border-neutral-800 bg-neutral-950 text-[11px] flex-shrink-0"
      style={{ color: '#a3a3a3' }}
    >
      {totalChanges === 0 ? (
        <span>No differences between source and draft.</span>
      ) : (
        <>
          <SummaryChip count={s.added_objects} color="#22c55e" label="added" />
          <SummaryChip
            count={s.modified_objects}
            color="#f59e0b"
            label="modified"
          />
          <SummaryChip
            count={s.deleted_objects}
            color="#ef4444"
            label="deleted"
          />
          <span style={{ color: '#525252' }}>·</span>
          <SummaryChip
            count={s.added_connections}
            color="#22c55e"
            label="new edges"
          />
          <SummaryChip
            count={s.modified_connections}
            color="#f59e0b"
            label="edges changed"
          />
          <SummaryChip
            count={s.deleted_connections}
            color="#ef4444"
            label="edges removed"
          />
          <span style={{ color: '#525252' }}>·</span>
          <SummaryChip count={s.moved_objects} color="#f59e0b" label="moved" />
          <SummaryChip
            count={s.resized_objects}
            color="#f59e0b"
            label="resized"
          />
        </>
      )}
    </div>
  )
}

function SummaryChip({
  count,
  color,
  label,
}: {
  count: number
  color: string
  label: string
}) {
  if (count === 0) return null
  return (
    <span style={{ color }}>
      <b>{count}</b>{' '}
      <span style={{ color: '#737373' }}>{label}</span>
    </span>
  )
}

function LegendDot({
  color,
  label,
  dashed,
}: {
  color: string
  label: string
  dashed?: boolean
}) {
  return (
    <span className="flex items-center gap-1.5">
      <span
        style={{
          width: 12,
          height: 12,
          borderRadius: 3,
          border: `2px ${dashed ? 'dashed' : 'solid'} ${color}`,
        }}
      />
      {label}
    </span>
  )
}
