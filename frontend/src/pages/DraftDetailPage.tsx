import { ReactFlowProvider } from '@xyflow/react'
import { useNavigate, useParams } from 'react-router-dom'
import { AppSidebar } from '../components/nav/AppSidebar'
import { ArchFlowCanvas } from '../components/canvas/ArchFlowCanvas'
import {
  useApplyDraft,
  useDiscardDraft,
  useDraft,
} from '../hooks/use-api'
import { useDiagram } from '../hooks/use-diagrams'

/**
 * Side-by-side compare page: live source on the left, forked draft on the
 * right, both read-only. Apply commits the draft onto the source, Discard
 * throws the fork away.
 *
 * If the draft is already merged/discarded we just show the status; there
 * is no forked diagram to render anymore.
 */
export function DraftDetailPage() {
  const { draftId } = useParams<{ draftId: string }>()
  const navigate = useNavigate()
  const { data: draft } = useDraft(draftId || null)
  const { data: sourceDiagram } = useDiagram(draft?.source_diagram_id ?? undefined)
  const applyDraft = useApplyDraft()
  const discardDraft = useDiscardDraft()

  if (!draft) {
    return (
      <div className="flex h-screen bg-neutral-950 text-neutral-200">
        <AppSidebar />
        <div className="flex-1 p-8 text-sm text-neutral-500">Loading…</div>
      </div>
    )
  }

  const isOpen = draft.status === 'open'
  const canCompare = isOpen && !!draft.forked_diagram_id && !!draft.source_diagram_id

  const handleApply = () => {
    if (!confirm(`Apply "${draft.name}" to the source diagram?`)) return
    applyDraft.mutate(draft.id, {
      onSuccess: () => {
        if (draft.source_diagram_id) navigate(`/diagram/${draft.source_diagram_id}`)
        else navigate('/drafts')
      },
    })
  }

  const handleDiscard = () => {
    if (!confirm('Discard this draft? The forked diagram will be deleted.')) return
    discardDraft.mutate(draft.id)
  }

  return (
    <div className="flex h-screen bg-neutral-950 text-neutral-200">
      <AppSidebar />
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Header */}
        <div className="border-b border-neutral-800 p-4 flex items-start justify-between gap-4">
          <div>
            <button
              onClick={() => navigate('/drafts')}
              className="text-xs text-neutral-500 hover:text-neutral-200 mb-1"
            >
              ← All drafts
            </button>
            <div className="text-lg font-semibold">{draft.name}</div>
            {draft.description && (
              <div className="text-xs text-neutral-400 mt-0.5 max-w-2xl">
                {draft.description}
              </div>
            )}
          </div>
          {isOpen && (
            <div className="flex gap-2">
              {draft.forked_diagram_id && (
                <button
                  onClick={() => navigate(`/diagram/${draft.forked_diagram_id}`)}
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

        {canCompare ? (
          <div className="flex-1 grid grid-cols-2 gap-px bg-neutral-800 overflow-hidden">
            <CompareSide
              title={`Source · ${sourceDiagram?.name ?? 'live'}`}
              diagramId={draft.source_diagram_id!}
            />
            <CompareSide
              title={`Draft · ${draft.name}`}
              diagramId={draft.forked_diagram_id!}
              accent="#3b82f6"
            />
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
      </div>
    </div>
  )
}

function CompareSide({
  title,
  diagramId,
  accent,
}: {
  title: string
  diagramId: string
  accent?: string
}) {
  return (
    <div className="bg-neutral-950 flex flex-col relative">
      <div
        className="px-3 py-1.5 text-[11px] uppercase tracking-wide border-b border-neutral-800"
        style={{ color: accent || '#a3a3a3' }}
      >
        {title}
      </div>
      <div className="flex-1 relative">
        <ReactFlowProvider>
          <ArchFlowCanvas diagramId={diagramId} />
        </ReactFlowProvider>
      </div>
    </div>
  )
}
