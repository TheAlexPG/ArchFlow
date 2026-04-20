import { ReactFlowProvider, type Viewport } from '@xyflow/react'
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { CompareCanvas } from '../components/drafts/CompareCanvas'
import { Modal } from '../components/common/Modal'
import { AppSidebar } from '../components/nav/AppSidebar'
import {
  useAddDiagramToDraft,
  useApplyDraft,
  useDiscardDraft,
  useDraft,
  useDraftConflicts,
  useDraftDiff,
  useRemoveDiagramFromDraft,
} from '../hooks/use-api'
import { useDiagrams } from '../hooks/use-diagrams'
import type { Conflict, ConflictReport, DraftDiagram, DraftDiffSummary, PerDiagramDiffEntry } from '../types/model'

const CONFLICT_TYPE_LABEL: Record<string, string> = {
  both_edited: 'both edited',
  main_deleted_fork_edited: 'deleted on main, edited in draft',
  fork_deleted_main_edited: 'edited on main, deleted in draft',
}

function ConflictBanner({ conflicts }: { conflicts: Conflict[] }) {
  return (
    <div className="border-b border-amber-800/60 bg-amber-950/40 px-4 py-3 flex-shrink-0">
      <div className="flex items-center gap-2 mb-1.5">
        <span className="text-amber-400 font-semibold text-sm">
          {conflicts.length} conflict{conflicts.length !== 1 ? 's' : ''} detected against main
        </span>
      </div>
      <ul className="flex flex-col gap-0.5">
        {conflicts.map((c) => (
          <li key={`${c.kind}-${c.id}`} className="text-xs text-amber-300/80">
            <span className="text-amber-500/60">[{c.kind}]</span>{' '}
            <span className="font-mono text-amber-300">{c.id}</span>{' '}
            <span className="text-amber-500/80">— {CONFLICT_TYPE_LABEL[c.type] ?? c.type}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function ForceApplyPanel({
  report,
  onForce,
  onDismiss,
  isPending,
}: {
  report: ConflictReport
  onForce: () => void
  onDismiss: () => void
  isPending: boolean
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70">
      <div className="bg-neutral-900 border border-amber-800/60 rounded-lg p-5 max-w-lg w-full shadow-xl">
        <div className="text-amber-400 font-semibold text-sm mb-2">
          Apply blocked — {report.conflicts.length} conflict{report.conflicts.length !== 1 ? 's' : ''}
        </div>
        <p className="text-xs text-neutral-400 mb-3">
          The following objects were modified on main while this draft was open. Force-applying will overwrite those main-branch changes.
        </p>
        <ul className="mb-4 flex flex-col gap-1">
          {report.conflicts.map((c) => (
            <li key={`${c.kind}-${c.id}`} className="text-xs text-amber-300/80">
              <span className="text-amber-500/60">[{c.kind}]</span>{' '}
              <span className="font-mono">{c.id}</span>{' '}
              — {CONFLICT_TYPE_LABEL[c.type] ?? c.type}
            </li>
          ))}
        </ul>
        <div className="flex justify-end gap-2">
          <button
            onClick={onDismiss}
            className="text-sm text-neutral-400 border border-neutral-700 hover:border-neutral-500 px-3 py-1.5 rounded"
          >
            Cancel
          </button>
          <button
            onClick={onForce}
            disabled={isPending}
            className="text-sm bg-amber-600 hover:bg-amber-500 text-white px-3 py-1.5 rounded disabled:opacity-40"
          >
            {isPending ? 'Applying…' : 'Force apply'}
          </button>
        </div>
      </div>
    </div>
  )
}

export function DraftDetailPage() {
  const { draftId } = useParams<{ draftId: string }>()
  const navigate = useNavigate()
  const { data: draft } = useDraft(draftId || null)
  const { data: diff } = useDraftDiff(
    draft?.status === 'open' ? (draftId || null) : null,
  )
  const { data: conflictsData } = useDraftConflicts(
    draft?.status === 'open' ? (draftId || null) : null,
  )
  const applyDraft = useApplyDraft()
  const discardDraft = useDiscardDraft()
  const [addModalOpen, setAddModalOpen] = useState(false)
  const [conflictReport, setConflictReport] = useState<ConflictReport | null>(null)

  if (!draft) {
    return (
      <div className="flex h-screen bg-neutral-950 text-neutral-200">
        <AppSidebar />
        <div className="flex-1 p-8 text-sm text-neutral-500">Loading…</div>
      </div>
    )
  }

  const isOpen = draft.status === 'open'
  const totalSummary = diff?.total_summary
  const conflicts = conflictsData?.conflicts ?? []

  const handleApply = () => {
    const n = draft.diagrams.length
    if (!confirm(`Apply "${draft.name}" — merges ${n} diagram fork${n !== 1 ? 's' : ''} into their source diagrams?`)) return
    applyDraft.mutate({ draftId: draft.id }, {
      onSuccess: () => navigate('/drafts'),
      onError: (err) => {
        const e = err as { response?: { status?: number; data?: ConflictReport } }
        if (e.response?.status === 409 && e.response.data) {
          setConflictReport(e.response.data)
        }
      },
    })
  }

  const handleForceApply = () => {
    applyDraft.mutate({ draftId: draft.id, force: true }, {
      onSuccess: () => navigate('/drafts'),
      onError: () => setConflictReport(null),
    })
  }

  const handleDiscard = () => {
    if (!confirm('Discard this feature? All forked diagrams will be deleted.')) return
    discardDraft.mutate(draft.id, {
      onSuccess: () => navigate('/drafts'),
    })
  }

  return (
    <div className="flex h-screen bg-neutral-950 text-neutral-200">
      {conflictReport && (
        <ForceApplyPanel
          report={conflictReport}
          onForce={handleForceApply}
          onDismiss={() => setConflictReport(null)}
          isPending={applyDraft.isPending}
        />
      )}
      <AppSidebar />
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Header */}
        <div className="border-b border-neutral-800 p-4 flex items-start justify-between gap-4 bg-neutral-950">
          <div className="min-w-0">
            <button
              onClick={() => navigate('/drafts')}
              className="text-xs text-neutral-500 hover:text-neutral-200 mb-1"
            >
              All features
            </button>
            <div className="text-lg font-semibold flex items-center gap-2">
              <span>{draft.name}</span>
              <span
                className="text-[10px] px-2 py-0.5 rounded"
                style={{
                  color: draft.status === 'open' ? '#3b82f6' : draft.status === 'merged' ? '#22c55e' : '#737373',
                  background: draft.status === 'open' ? '#3b82f622' : draft.status === 'merged' ? '#22c55e22' : '#73737322',
                  border: `1px solid ${draft.status === 'open' ? '#3b82f655' : draft.status === 'merged' ? '#22c55e55' : '#52525255'}`,
                }}
              >
                {draft.status}
              </span>
            </div>
            {draft.description && (
              <div className="text-xs text-neutral-400 mt-0.5 max-w-2xl">
                {draft.description}
              </div>
            )}
          </div>
          {isOpen && (
            <div className="flex gap-2 flex-shrink-0">
              <button
                onClick={handleDiscard}
                className="text-sm text-neutral-400 border border-neutral-700 hover:border-neutral-500 px-3 py-1.5 rounded"
              >
                Discard feature
              </button>
              <button
                onClick={handleApply}
                disabled={applyDraft.isPending}
                className="text-sm bg-green-600 hover:bg-green-500 text-white px-3 py-1.5 rounded disabled:opacity-40"
              >
                {applyDraft.isPending ? 'Applying…' : `Apply ${draft.diagrams.length} diagram${draft.diagrams.length !== 1 ? 's' : ''}`}
              </button>
            </div>
          )}
        </div>

        {/* Conflict banner — shown when open draft has conflicts against main */}
        {isOpen && conflicts.length > 0 && <ConflictBanner conflicts={conflicts} />}

        {/* Total summary strip */}
        {isOpen && totalSummary && <TotalSummaryStrip summary={totalSummary} diagramCount={draft.diagrams.length} />}

        <div className="flex-1 overflow-y-auto">
          {/* Add diagram button */}
          {isOpen && (
            <div className="px-6 pt-5 pb-2 flex items-center justify-between">
              <span className="text-sm font-medium text-neutral-300">
                Diagrams in this feature ({draft.diagrams.length})
              </span>
              <button
                onClick={() => setAddModalOpen(true)}
                className="text-xs border border-neutral-700 hover:border-neutral-500 text-neutral-300 hover:text-neutral-100 px-3 py-1.5 rounded"
              >
                + Add diagram to this feature
              </button>
            </div>
          )}

          {draft.diagrams.length === 0 ? (
            <div className="px-6 py-8 text-sm text-neutral-500 italic">
              {isOpen
                ? 'No diagrams in this feature yet. Add one using the button above.'
                : 'No diagrams were in this feature.'}
            </div>
          ) : (
            <div className="px-6 pb-6 flex flex-col gap-4 mt-2">
              {draft.diagrams.map((dd, idx) => {
                const perDiagramDiff = diff?.per_diagram.find(
                  (p) => p.source_diagram_id === dd.source_diagram_id && p.forked_diagram_id === dd.forked_diagram_id,
                )
                return (
                  <DiagramCard
                    key={dd.id}
                    draftDiagram={dd}
                    draftId={draft.id}
                    isOpen={isOpen}
                    perDiagramDiff={perDiagramDiff}
                    defaultExpanded={idx === 0}
                  />
                )
              })}
            </div>
          )}
        </div>

        {/* Legend */}
        {isOpen && draft.diagrams.length > 0 && (
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

      {addModalOpen && (
        <AddDiagramToFeatureModal
          draftId={draft.id}
          existingDraftDiagrams={draft.diagrams}
          onClose={() => setAddModalOpen(false)}
        />
      )}
    </div>
  )
}

// ─── Diagram card ─────────────────────────────────────────

function DiagramCard({
  draftDiagram,
  draftId,
  isOpen,
  perDiagramDiff,
  defaultExpanded,
}: {
  draftDiagram: DraftDiagram
  draftId: string
  isOpen: boolean
  perDiagramDiff: PerDiagramDiffEntry | undefined
  defaultExpanded: boolean
}) {
  const [expanded, setExpanded] = useState(defaultExpanded)
  const [viewport, setViewport] = useState<Viewport | null>(null)
  const [activeSide, setActiveSide] = useState<'source' | 'fork' | null>(null)
  const removeDiagram = useRemoveDiagramFromDraft()
  const navigate = useNavigate()

  const summary = perDiagramDiff?.summary

  const handleRemove = () => {
    if (!confirm(`Remove "${draftDiagram.source_diagram_name ?? 'this diagram'}" from the feature? The fork will be deleted.`)) return
    removeDiagram.mutate({ draftId, diagramId: draftDiagram.forked_diagram_id })
  }

  return (
    <div className="border border-neutral-800 rounded-lg overflow-hidden bg-neutral-950">
      {/* Card header */}
      <div
        className="flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-neutral-900"
        onClick={() => setExpanded((v) => !v)}
      >
        <span className="text-neutral-500 text-xs select-none">
          {expanded ? '▾' : '▸'}
        </span>
        <span className="text-sm font-medium flex-1">
          {draftDiagram.source_diagram_name ?? draftDiagram.source_diagram_id}
        </span>
        {summary && <SummaryChips summary={summary} />}
        {isOpen && (
          <div className="flex gap-2 ml-2" onClick={(e) => e.stopPropagation()}>
            <button
              onClick={() => navigate(`/diagram/${draftDiagram.forked_diagram_id}`)}
              className="text-xs text-neutral-400 hover:text-blue-400 border border-neutral-700 hover:border-neutral-500 px-2 py-1 rounded"
            >
              Edit fork
            </button>
            <button
              onClick={handleRemove}
              disabled={removeDiagram.isPending}
              className="text-xs text-neutral-500 hover:text-red-400 border border-neutral-700 hover:border-red-800 px-2 py-1 rounded disabled:opacity-40"
            >
              Remove
            </button>
          </div>
        )}
      </div>

      {/* Expanded compare canvases */}
      {expanded && (
        <div
          className="grid grid-cols-2 gap-px bg-neutral-800"
          style={{ height: 360 }}
        >
          <div
            className="bg-neutral-950 flex flex-col relative overflow-hidden"
            onMouseEnter={() => setActiveSide('source')}
            onMouseLeave={() => setActiveSide((s) => (s === 'source' ? null : s))}
          >
            <SideHeader
              label="Source (live)"
              name={draftDiagram.source_diagram_name ?? 'live'}
              color="#737373"
            />
            <div className="flex-1 relative">
              <ReactFlowProvider>
                <CompareCanvas
                  diagramId={draftDiagram.source_diagram_id}
                  side="source"
                  diff={perDiagramDiff}
                  draftId={null}
                  isActive={activeSide === 'source'}
                  viewport={viewport}
                  onViewportChange={setViewport}
                  movedOnFork={new Set(perDiagramDiff?.moved_on_fork ?? [])}
                  resizedOnFork={new Set(perDiagramDiff?.resized_on_fork ?? [])}
                />
              </ReactFlowProvider>
            </div>
          </div>
          <div
            className="bg-neutral-950 flex flex-col relative overflow-hidden"
            style={{ boxShadow: 'inset 0 0 0 2px rgba(59, 130, 246, 0.35)' }}
            onMouseEnter={() => setActiveSide('fork')}
            onMouseLeave={() => setActiveSide((s) => (s === 'fork' ? null : s))}
          >
            <SideHeader
              label="Draft (proposed)"
              name={draftDiagram.forked_diagram_name ?? 'fork'}
              color="#3b82f6"
            />
            <div className="flex-1 relative">
              <ReactFlowProvider>
                <CompareCanvas
                  diagramId={draftDiagram.forked_diagram_id}
                  side="fork"
                  diff={perDiagramDiff}
                  draftId={draftId}
                  isActive={activeSide === 'fork'}
                  viewport={viewport}
                  onViewportChange={setViewport}
                  movedOnFork={new Set(perDiagramDiff?.moved_on_fork ?? [])}
                  resizedOnFork={new Set(perDiagramDiff?.resized_on_fork ?? [])}
                />
              </ReactFlowProvider>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Add Diagram Modal ────────────────────────────────────

function AddDiagramToFeatureModal({
  draftId,
  existingDraftDiagrams,
  onClose,
}: {
  draftId: string
  existingDraftDiagrams: DraftDiagram[]
  onClose: () => void
}) {
  const { data: allDiagrams = [] } = useDiagrams()
  const addDiagram = useAddDiagramToDraft()
  const [search, setSearch] = useState('')

  const existingSourceIds = new Set(existingDraftDiagrams.map((d) => d.source_diagram_id))

  // Filter: exclude forks (draft_id !== null) and already-included sources
  const eligible = allDiagrams.filter((d) => {
    if (d.draft_id !== null) return false
    if (existingSourceIds.has(d.id)) return false
    if (search.trim()) {
      return d.name.toLowerCase().includes(search.trim().toLowerCase())
    }
    return true
  })

  const handlePick = (diagramId: string) => {
    addDiagram.mutate({ draftId, diagramId }, {
      onSuccess: onClose,
    })
  }

  return (
    <Modal
      open
      onClose={onClose}
      title="Add diagram to this feature"
      width={500}
    >
      <input
        autoFocus
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder="Search diagrams…"
        style={{
          width: '100%',
          padding: '8px 10px',
          fontSize: 13,
          background: '#0a0a0a',
          border: '1px solid #333',
          borderRadius: 6,
          color: '#f5f5f5',
          outline: 'none',
          marginBottom: 12,
          boxSizing: 'border-box',
        }}
      />
      <div style={{ maxHeight: 320, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 4 }}>
        {eligible.length === 0 && (
          <div style={{ fontSize: 12, color: '#737373', padding: '8px 0' }}>
            {search ? 'No diagrams match.' : 'No eligible diagrams available.'}
          </div>
        )}
        {eligible.map((d) => (
          <button
            key={d.id}
            onClick={() => handlePick(d.id)}
            disabled={addDiagram.isPending}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 10,
              padding: '8px 10px',
              background: '#0a0a0a',
              border: '1px solid #262626',
              borderRadius: 6,
              color: '#d4d4d4',
              cursor: addDiagram.isPending ? 'default' : 'pointer',
              fontSize: 13,
              textAlign: 'left',
              opacity: addDiagram.isPending ? 0.5 : 1,
            }}
          >
            <span style={{ flex: 1 }}>{d.name}</span>
            <span style={{ fontSize: 10, color: '#525252' }}>{d.type}</span>
          </button>
        ))}
      </div>
      {addDiagram.error && (
        <div
          style={{
            marginTop: 10,
            padding: '8px 10px',
            fontSize: 12,
            background: '#450a0a',
            border: '1px solid #7f1d1d',
            borderRadius: 6,
            color: '#fca5a5',
          }}
        >
          {(() => {
            const e = addDiagram.error as { response?: { data?: { detail?: string } }; message?: string }
            return e.response?.data?.detail ?? e.message ?? 'Failed to add diagram'
          })()}
        </div>
      )}
    </Modal>
  )
}

// ─── Helpers ─────────────────────────────────────────────

function TotalSummaryStrip({ summary, diagramCount }: { summary: DraftDiffSummary; diagramCount: number }) {
  const totalChanges =
    summary.added_objects +
    summary.modified_objects +
    summary.deleted_objects +
    summary.added_connections +
    summary.modified_connections +
    summary.deleted_connections +
    summary.moved_objects +
    summary.resized_objects
  return (
    <div
      className="flex items-center gap-4 px-4 py-1.5 border-b border-neutral-800 bg-neutral-950 text-[11px] flex-shrink-0"
      style={{ color: '#a3a3a3' }}
    >
      <span style={{ color: '#525252' }}>
        Across {diagramCount} diagram{diagramCount !== 1 ? 's' : ''}:
      </span>
      {totalChanges === 0 ? (
        <span>No differences.</span>
      ) : (
        <>
          <SummaryChip count={summary.added_objects} color="#22c55e" label="added" />
          <SummaryChip count={summary.modified_objects} color="#f59e0b" label="modified" />
          <SummaryChip count={summary.deleted_objects} color="#ef4444" label="deleted" />
          <span style={{ color: '#525252' }}>·</span>
          <SummaryChip count={summary.added_connections} color="#22c55e" label="new edges" />
          <SummaryChip count={summary.modified_connections} color="#f59e0b" label="edges changed" />
          <SummaryChip count={summary.deleted_connections} color="#ef4444" label="edges removed" />
          <span style={{ color: '#525252' }}>·</span>
          <SummaryChip count={summary.moved_objects} color="#f59e0b" label="moved" />
          <SummaryChip count={summary.resized_objects} color="#f59e0b" label="resized" />
        </>
      )}
    </div>
  )
}

function SummaryChips({ summary }: { summary: DraftDiffSummary }) {
  const chips = [
    { count: summary.added_objects + summary.added_connections, color: '#22c55e', label: 'added' },
    { count: summary.modified_objects + summary.modified_connections, color: '#f59e0b', label: 'modified' },
    { count: summary.deleted_objects + summary.deleted_connections, color: '#ef4444', label: 'deleted' },
  ].filter((c) => c.count > 0)
  if (chips.length === 0) {
    return <span style={{ fontSize: 10, color: '#525252' }}>No changes</span>
  }
  return (
    <div className="flex items-center gap-2">
      {chips.map((c) => (
        <span
          key={c.label}
          style={{
            fontSize: 10,
            padding: '1px 6px',
            borderRadius: 9999,
            background: `${c.color}22`,
            color: c.color,
            border: `1px solid ${c.color}55`,
          }}
        >
          {c.count} {c.label}
        </span>
      ))}
    </div>
  )
}

function SummaryChip({ count, color, label }: { count: number; color: string; label: string }) {
  if (count === 0) return null
  return (
    <span style={{ color }}>
      <b>{count}</b>{' '}
      <span style={{ color: '#737373' }}>{label}</span>
    </span>
  )
}

function SideHeader({ label, name, color }: { label: string; name: string; color: string }) {
  return (
    <div
      className="px-3 py-2 text-[11px] border-b border-neutral-800 flex items-center gap-2 bg-neutral-950 flex-shrink-0"
      style={{ color }}
    >
      <span style={{ textTransform: 'uppercase', letterSpacing: '0.08em' }}>{label}</span>
      <span style={{ color: '#525252' }}>·</span>
      <span style={{ color: '#d4d4d4', fontWeight: 500 }}>{name}</span>
    </div>
  )
}

function LegendDot({ color, label, dashed }: { color: string; label: string; dashed?: boolean }) {
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
