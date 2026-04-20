import { useCallback, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ReactFlowProvider } from '@xyflow/react'
import { ArchFlowCanvas } from '../components/canvas/ArchFlowCanvas'
import { DiagramAccessModal } from '../components/diagram/DiagramAccessModal'
import { CreateDraftModal } from '../components/drafts/CreateDraftModal'
import { AddObjectToolbar } from '../components/toolbar/AddObjectToolbar'
import { FilterToolbar } from '../components/toolbar/FilterToolbar'
import { FlowPlaybackBar } from '../components/toolbar/FlowPlaybackBar'
import { FlowsPanel } from '../components/toolbar/FlowsPanel'
import { EdgeSidebar } from '../components/sidebar/EdgeSidebar'
import { ObjectSidebar } from '../components/sidebar/ObjectSidebar'
import { ObjectTree } from '../components/tree/ObjectTree'
import { SearchModal } from '../components/nav/SearchModal'
import { useDiagram, useDiagramBreadcrumbs } from '../hooks/use-diagrams'
import {
  useApplyDraft,
  useCreateDraftFromDiagram,
  useDiscardDraft,
  useDraft,
  useDraftsForDiagram,
  type DiagramDraftEntry,
} from '../hooks/use-api'
import { useAuthStore } from '../stores/auth-store'
import { useCanvasStore } from '../stores/canvas-store'

export function DiagramPage() {
  const { diagramId } = useParams<{ diagramId: string }>()
  const { data: diagram } = useDiagram(diagramId)
  const breadcrumbs = useDiagramBreadcrumbs(diagramId)
  const navigate = useNavigate()
  const { logout } = useAuthStore()
  const { selectedEdgeId, treeOpen, toggleTree } = useCanvasStore()
  const [searchOpen, setSearchOpen] = useState(false)
  const [draftModalOpen, setDraftModalOpen] = useState(false)
  const [draftsDropdownOpen, setDraftsDropdownOpen] = useState(false)
  const [accessModalOpen, setAccessModalOpen] = useState(false)

  const isForkedDiagram = !!diagram?.draft_id
  const isLiveDiagram = !!diagram && !diagram.draft_id

  // ── Draft context ──────────────────────────────────────────
  // This diagram is forked if it carries a draft_id. We fetch the draft
  // metadata to show the banner (name + Apply/Discard controls). For live
  // diagrams, we offer a "Draft" button that forks them into a new draft.
  const forkDraft = useCreateDraftFromDiagram()
  const applyDraft = useApplyDraft()
  const discardDraft = useDiscardDraft()
  const { data: currentDraft } = useDraft(diagram?.draft_id ?? null)
  // For live diagrams: fetch all open features that include this diagram as a source
  const { data: draftsForDiagram = [] } = useDraftsForDiagram(
    isLiveDiagram ? diagramId : undefined,
  )
  const openDraftsForThisDiagram = draftsForDiagram.filter((d) => d.draft_status === 'open')

  const handleStartDraft = () => {
    forkDraft.reset()
    setDraftModalOpen(true)
  }

  const submitDraft = (name: string, description: string | null) => {
    if (!diagramId) return
    forkDraft.mutate(
      { diagramId, name, description },
      {
        onSuccess: (draft) => {
          setDraftModalOpen(false)
          const forkedId = draft.diagrams[0]?.forked_diagram_id
          if (forkedId) {
            navigate(`/diagram/${forkedId}`)
          }
        },
      },
    )
  }

  // Surface backend errors inside the modal so the user isn't left
  // wondering why "Create draft" did nothing.
  const draftError = forkDraft.error
    ? (() => {
        const e = forkDraft.error as { response?: { data?: { detail?: string } }; message?: string }
        return e.response?.data?.detail || e.message || 'Failed to create draft'
      })()
    : null

  const handleApply = () => {
    if (!currentDraft) return
    if (!confirm(`Apply feature "${currentDraft.name}" — merges all diagram changes into their source diagrams?`)) return
    applyDraft.mutate(currentDraft.id, {
      onSuccess: () => navigate('/drafts'),
    })
  }

  const handleDiscard = () => {
    if (!currentDraft) return
    if (!confirm('Discard this feature? All forked diagrams will be deleted.')) return
    discardDraft.mutate(currentDraft.id, {
      onSuccess: () => navigate('/drafts'),
    })
  }

  const toggleSearch = useCallback(() => setSearchOpen((v) => !v), [])

  return (
    <ReactFlowProvider>
      <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: '#0a0a0a', color: '#f5f5f5' }}>
        {/* Top bar with breadcrumbs */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '8px 16px', borderBottom: '1px solid #262626', background: '#111',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <button
              onClick={() => navigate('/')}
              style={{
                background: 'none', border: 'none', color: '#a3a3a3', cursor: 'pointer',
                fontSize: 16, padding: '2px 6px',
              }}
              title="Home"
            >
              &#8962;
            </button>
            {breadcrumbs.length <= 1 ? (
              // No parent chain — simple "Home › <name>"
              <>
                <span style={{ color: '#333' }}>›</span>
                <span style={{ fontSize: 13, fontWeight: 500 }}>
                  {diagram?.name || 'Loading...'}
                </span>
              </>
            ) : (
              // Full C4 parent chain — all ancestors are clickable, current is plain text
              breadcrumbs.map((crumb, idx) => {
                const isLast = idx === breadcrumbs.length - 1
                return (
                  <span key={crumb.id} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ color: '#333' }}>›</span>
                    {isLast ? (
                      <span style={{ fontSize: 13, fontWeight: 500 }}>
                        {crumb.name}
                      </span>
                    ) : (
                      <button
                        onClick={() => navigate(`/diagram/${crumb.id}`)}
                        style={{
                          background: 'none', border: 'none', color: '#a3a3a3', cursor: 'pointer',
                          fontSize: 13, padding: '2px 6px',
                        }}
                      >
                        {crumb.name}
                      </button>
                    )}
                  </span>
                )
              })
            )}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <button
              onClick={toggleTree}
              style={{
                background: treeOpen ? '#333' : '#1a1a1a',
                border: '1px solid #333', borderRadius: 6,
                color: treeOpen ? '#f5f5f5' : '#737373',
                cursor: 'pointer', fontSize: 12, padding: '4px 10px',
              }}
              title="Toggle object tree"
            >
              ☰
            </button>
            <button
              onClick={toggleSearch}
              style={{
                background: '#1a1a1a', border: '1px solid #333', borderRadius: 6,
                color: '#737373', cursor: 'pointer', fontSize: 12, padding: '4px 10px',
                display: 'flex', alignItems: 'center', gap: 6,
              }}
            >
              🔍 Search
              <span style={{
                background: '#262626', borderRadius: 3, padding: '1px 4px',
                fontSize: 10, color: '#525252',
              }}>
                ⌘K
              </span>
            </button>
            {isLiveDiagram && (
              <button
                onClick={() => setAccessModalOpen(true)}
                style={{
                  background: '#1a1a1a', border: '1px solid #333', borderRadius: 6,
                  color: '#a3a3a3', cursor: 'pointer', fontSize: 12, padding: '4px 10px',
                }}
                title="Control which teams can see or edit this diagram"
              >
                🔒 Access
              </button>
            )}
            {isLiveDiagram && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 4, position: 'relative' }}>
                {openDraftsForThisDiagram.length > 0 && (
                  <div style={{ position: 'relative' }}>
                    <button
                      onClick={() => setDraftsDropdownOpen((v) => !v)}
                      style={{
                        background: '#1e3a5f', border: '1px solid #3b82f6', borderRadius: 6,
                        color: '#93c5fd', cursor: 'pointer', fontSize: 12, padding: '4px 10px',
                      }}
                      title="Open features that include this diagram"
                    >
                      Drafts ({openDraftsForThisDiagram.length}) ▾
                    </button>
                    {draftsDropdownOpen && (
                      <>
                        <div
                          style={{ position: 'fixed', inset: 0, zIndex: 49 }}
                          onClick={() => setDraftsDropdownOpen(false)}
                        />
                        <div style={{
                          position: 'absolute', top: '100%', right: 0, marginTop: 4,
                          background: '#171717', border: '1px solid #333', borderRadius: 8,
                          boxShadow: '0 8px 24px rgba(0,0,0,0.5)',
                          zIndex: 50, minWidth: 260, overflow: 'hidden',
                        }}>
                          {openDraftsForThisDiagram.map((d: DiagramDraftEntry) => (
                            <div key={d.draft_id} style={{
                              padding: '10px 14px',
                              borderBottom: '1px solid #262626',
                            }}>
                              <div style={{ fontSize: 12, fontWeight: 600, color: '#d4d4d4', marginBottom: 6 }}>
                                {d.draft_name}
                              </div>
                              <div style={{ display: 'flex', gap: 8 }}>
                                <button
                                  onClick={() => {
                                    setDraftsDropdownOpen(false)
                                    navigate(`/diagram/${d.forked_diagram_id}`)
                                  }}
                                  style={{
                                    fontSize: 11, padding: '3px 8px',
                                    background: 'transparent', border: '1px solid #3b82f6',
                                    borderRadius: 4, color: '#93c5fd', cursor: 'pointer',
                                  }}
                                >
                                  Open fork
                                </button>
                                <button
                                  onClick={() => {
                                    setDraftsDropdownOpen(false)
                                    navigate(`/drafts/${d.draft_id}`)
                                  }}
                                  style={{
                                    fontSize: 11, padding: '3px 8px',
                                    background: 'transparent', border: '1px solid #404040',
                                    borderRadius: 4, color: '#a3a3a3', cursor: 'pointer',
                                  }}
                                >
                                  Feature dashboard
                                </button>
                              </div>
                            </div>
                          ))}
                        </div>
                      </>
                    )}
                  </div>
                )}
                <button
                  onClick={handleStartDraft}
                  disabled={forkDraft.isPending}
                  style={{
                    background: '#1a1a1a', border: '1px solid #3b82f6', borderRadius: 6,
                    color: '#93c5fd', cursor: 'pointer', fontSize: 12, padding: '4px 10px',
                  }}
                  title="Start a new feature draft forked from this diagram"
                >
                  ✎ Draft new feature
                </button>
              </div>
            )}
            <button
              onClick={async () => {
                const { toPng } = await import('html-to-image')
                const el = document.querySelector('.react-flow') as HTMLElement
                if (!el) return
                const dataUrl = await toPng(el, { backgroundColor: '#0a0a0a' })
                const a = document.createElement('a')
                a.href = dataUrl
                a.download = `archflow-${new Date().toISOString().slice(0, 10)}.png`
                a.click()
              }}
              style={{
                background: '#1a1a1a', border: '1px solid #333', borderRadius: 6,
                color: '#737373', cursor: 'pointer', fontSize: 12, padding: '4px 10px',
              }}
              title="Export as PNG"
            >
              📷
            </button>
            <button
              onClick={logout}
              style={{
                background: 'none', border: 'none', color: '#525252', cursor: 'pointer',
                fontSize: 12,
              }}
            >
              Sign out
            </button>
          </div>
        </div>

        {/* Forked-diagram banner — live model is frozen; edits go to the draft */}
        {isForkedDiagram && currentDraft && (
          <div style={{
            background: 'linear-gradient(to right, #1e3a5f, #0a0a0a 80%)',
            borderBottom: '1px solid #3b82f6',
            padding: '6px 16px',
            display: 'flex',
            alignItems: 'center',
            gap: 12,
            fontSize: 12,
            color: '#93c5fd',
          }}>
            <span>✎</span>
            <span>
              Editing feature: <b style={{ color: '#f5f5f5' }}>{currentDraft.name}</b> —
              edits stay on the fork; Apply merges all feature changes into their source diagrams.
            </span>
            <span style={{ flex: 1 }} />
            <button
              onClick={() => navigate(`/drafts/${currentDraft.id}`)}
              style={{
                background: 'transparent', border: '1px solid #3b82f6',
                borderRadius: 4, color: '#93c5fd', cursor: 'pointer',
                fontSize: 11, padding: '3px 8px',
              }}
            >
              Compare
            </button>
            <button
              onClick={handleDiscard}
              style={{
                background: 'transparent', border: '1px solid #525252',
                borderRadius: 4, color: '#a3a3a3', cursor: 'pointer',
                fontSize: 11, padding: '3px 8px',
              }}
            >
              Discard
            </button>
            <button
              onClick={handleApply}
              disabled={applyDraft.isPending}
              style={{
                background: '#16a34a', border: '1px solid #16a34a',
                borderRadius: 4, color: 'white', cursor: 'pointer',
                fontSize: 11, padding: '3px 10px',
                opacity: applyDraft.isPending ? 0.5 : 1,
              }}
            >
              Apply feature changes to source diagrams
            </button>
          </div>
        )}

        {/* Canvas area */}
        <div style={{ display: 'flex', flex: 1, minHeight: 0, overflow: 'hidden' }}>
          {treeOpen && <ObjectTree diagramId={diagramId} />}
          <div
            style={{
              flex: 1,
              position: 'relative',
              minWidth: 0,
              // Visual "you're inside a fork" frame. The canvas fills the
              // inset so the user sees a tinted viewport boundary at all times.
              boxShadow: isForkedDiagram
                ? 'inset 0 0 0 3px rgba(59, 130, 246, 0.55)'
                : undefined,
            }}
          >
            <AddObjectToolbar diagramId={diagramId} />
            <div style={{ position: 'absolute', inset: 0 }}>
              <ArchFlowCanvas diagramId={diagramId} />
            </div>
            {isForkedDiagram && (
              <div
                style={{
                  position: 'absolute',
                  right: 14,
                  bottom: 14,
                  zIndex: 5,
                  pointerEvents: 'none',
                  fontSize: 44,
                  fontWeight: 800,
                  letterSpacing: '0.18em',
                  color: 'rgba(59, 130, 246, 0.08)',
                  textTransform: 'uppercase',
                  userSelect: 'none',
                }}
              >
                Draft
              </div>
            )}
            {diagramId && <FlowsPanel diagramId={diagramId} />}
            {diagramId && <FlowPlaybackBar diagramId={diagramId} />}
            <FilterToolbar />
          </div>
          {selectedEdgeId ? <EdgeSidebar /> : <ObjectSidebar />}
        </div>
      </div>

      <SearchModal open={searchOpen} onClose={toggleSearch} />
      <CreateDraftModal
        open={draftModalOpen}
        onClose={() => setDraftModalOpen(false)}
        onSubmit={submitDraft}
        submitting={forkDraft.isPending}
        sourceName={diagram?.name}
        errorMessage={draftError}
      />
      {accessModalOpen && diagramId && (
        <DiagramAccessModal
          diagramId={diagramId}
          onClose={() => setAccessModalOpen(false)}
        />
      )}
    </ReactFlowProvider>
  )
}
