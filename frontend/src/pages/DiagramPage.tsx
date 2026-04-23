import { useCallback, useMemo, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ReactFlowProvider } from '@xyflow/react'
import { ArchFlowCanvas } from '../components/canvas/ArchFlowCanvas'
import { DiagramAccessModal } from '../components/diagram/DiagramAccessModal'
import { CreateDraftModal } from '../components/drafts/CreateDraftModal'
import { AddObjectFAB } from '../components/canvas/AddObjectFAB'
import { FilterToolbar } from '../components/toolbar/FilterToolbar'
import { FlowPlaybackBar } from '../components/toolbar/FlowPlaybackBar'
import { FlowsPanel } from '../components/toolbar/FlowsPanel'
import { EdgeSidebar } from '../components/sidebar/EdgeSidebar'
import { ObjectSidebar } from '../components/sidebar/ObjectSidebar'
import { ObjectTree } from '../components/tree/ObjectTree'
import { SearchModal } from '../components/nav/SearchModal'
import { Avatar, AvatarStack, Button, Kbd, StatusPill, type AvatarGradient } from '../components/ui'
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

// Stable gradient + initials derivation so each user has a consistent
// avatar identity across the canvas / inspector / top bar. The cursor
// overlay already picks hues from user_id — gradients here are chosen
// from a short palette so we don't have to compute an HSL → gradient map.
const AVATAR_GRADIENTS: AvatarGradient[] = [
  'coral-amber',
  'coral-purple',
  'blue-purple',
  'green-blue',
]

function gradientForId(id: string): AvatarGradient {
  let h = 5381
  for (let i = 0; i < id.length; i++) h = ((h << 5) + h) ^ id.charCodeAt(i)
  return AVATAR_GRADIENTS[Math.abs(h) % AVATAR_GRADIENTS.length]
}

function initialsFromName(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return '?'
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (parts[0][0] + parts[1][0]).toUpperCase()
}

// ─── Top-bar icons (inline SVG, currentColor) ───────────────────────────

function ArrowLeftIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="m12 19-7-7 7-7" />
      <path d="M19 12H5" />
    </svg>
  )
}

function ChevronRightIcon() {
  return (
    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-text-4">
      <path d="m9 18 6-6-6-6" />
    </svg>
  )
}

function SearchIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="11" cy="11" r="8" />
      <path d="m21 21-4.35-4.35" />
    </svg>
  )
}

function LockIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <rect x="3" y="11" width="18" height="10" rx="2" />
      <path d="M7 11V7a5 5 0 0 1 10 0v4" />
    </svg>
  )
}

function PublishIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 19V5" />
      <path d="m5 12 7-7 7 7" />
    </svg>
  )
}

function TreeIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M3 6h18M3 12h12M3 18h18" />
    </svg>
  )
}

function CameraIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z" />
      <circle cx="12" cy="13" r="3.5" />
    </svg>
  )
}

export function DiagramPage() {
  const { diagramId } = useParams<{ diagramId: string }>()
  const { data: diagram } = useDiagram(diagramId)
  const breadcrumbs = useDiagramBreadcrumbs(diagramId)
  const navigate = useNavigate()
  const { logout } = useAuthStore()
  const { selectedEdgeId, treeOpen, toggleTree, presenceUsers } = useCanvasStore()
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
    applyDraft.mutate({ draftId: currentDraft.id }, {
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

  // Breadcrumb segments: prepend a synthetic "workspace" root if the C4
  // parent chain didn't already expose one, so the mono breadcrumb always
  // has at least two segments to separate with a chevron.
  const breadcrumbSegments = useMemo(() => {
    if (breadcrumbs.length === 0) {
      return diagram
        ? [{ id: diagram.id, name: diagram.name, clickable: false }]
        : []
    }
    return breadcrumbs.map((crumb, idx) => ({
      id: crumb.id,
      name: crumb.name,
      clickable: idx !== breadcrumbs.length - 1,
    }))
  }, [breadcrumbs, diagram])

  // Avatar stack: only show when >=2 users are online (self + 1 peer).
  const presenceAvatars = presenceUsers.length > 1 ? presenceUsers : []

  return (
    <ReactFlowProvider>
      <div className="flex flex-col h-screen bg-bg text-text-base">
        {/* ── Canvas top bar ───────────────────────────────────────────── */}
        <div className="flex items-center justify-between h-12 px-4 border-b border-border-base bg-panel shrink-0">
          {/* Left: back button + mono breadcrumb */}
          <div className="flex items-center gap-2 min-w-0">
            <Button
              variant="ghost"
              size="icon"
              onClick={() => navigate('/')}
              title="Back to workspace"
              aria-label="Back to workspace"
            >
              <ArrowLeftIcon />
            </Button>
            <span className="font-mono text-[10.5px] text-text-3 truncate">workspace</span>
            {breadcrumbSegments.map((seg) => (
              <span key={seg.id} className="flex items-center gap-2 min-w-0">
                <ChevronRightIcon />
                {seg.clickable ? (
                  <button
                    onClick={() => navigate(`/diagram/${seg.id}`)}
                    className="font-mono text-[10.5px] text-text-3 hover:text-text-base transition-colors truncate"
                  >
                    {seg.name}
                  </button>
                ) : (
                  <span className="text-[13px] font-medium text-text-base truncate">
                    {seg.name}
                  </span>
                )}
              </span>
            ))}
            {/* DRAFT · UNSAVED pill while editing a fork — the forked diagram
                IS the "draft · unsaved" state (edits stay on the fork until
                the feature is applied). */}
            {isForkedDiagram && currentDraft && (
              <StatusPill status="draft" className="ml-1 shrink-0">
                DRAFT · UNSAVED
              </StatusPill>
            )}
          </div>

          {/* Right: presence stack + actions */}
          <div className="flex items-center gap-2 shrink-0">
            {presenceAvatars.length > 0 && (
              <AvatarStack className="mr-1">
                {presenceAvatars.map((u) => (
                  <Avatar
                    key={u.user_id}
                    size="sm"
                    gradient={gradientForId(u.user_id)}
                    initials={initialsFromName(u.user_name)}
                    className="!w-6 !h-6 text-[9.5px]"
                  />
                ))}
              </AvatarStack>
            )}

            <Button
              size="sm"
              onClick={toggleTree}
              title="Toggle object tree"
              className={treeOpen ? '!text-text-base !border-border-hi' : ''}
            >
              <TreeIcon />
            </Button>

            <Button
              size="sm"
              onClick={toggleSearch}
              leftIcon={<SearchIcon />}
              rightIcon={<Kbd className="ml-1">⌘K</Kbd>}
            >
              Search
            </Button>

            {isLiveDiagram && (
              <Button
                size="sm"
                onClick={() => setAccessModalOpen(true)}
                leftIcon={<LockIcon />}
                title="Control which teams can see or edit this diagram"
              >
                Access
              </Button>
            )}

            {isLiveDiagram && openDraftsForThisDiagram.length > 0 && (
              <div className="relative">
                <Button
                  size="sm"
                  onClick={() => setDraftsDropdownOpen((v) => !v)}
                  title="Open features that include this diagram"
                >
                  Drafts ({openDraftsForThisDiagram.length})
                </Button>
                {draftsDropdownOpen && (
                  <>
                    <div
                      className="fixed inset-0 z-[49]"
                      onClick={() => setDraftsDropdownOpen(false)}
                    />
                    <div className="absolute top-full right-0 mt-1 min-w-[260px] bg-panel border border-border-base rounded-lg shadow-popup z-50 overflow-hidden">
                      {openDraftsForThisDiagram.map((d: DiagramDraftEntry) => (
                        <div key={d.draft_id} className="p-3 border-b border-border-base last:border-b-0">
                          <div className="text-[12px] font-semibold text-text-base mb-1.5">
                            {d.draft_name}
                          </div>
                          <div className="flex gap-2">
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => {
                                setDraftsDropdownOpen(false)
                                navigate(`/diagram/${d.forked_diagram_id}`)
                              }}
                              className="!text-coral !border-coral/40"
                            >
                              Open fork
                            </Button>
                            <Button
                              size="sm"
                              onClick={() => {
                                setDraftsDropdownOpen(false)
                                navigate(`/drafts/${d.draft_id}`)
                              }}
                            >
                              Feature dashboard
                            </Button>
                          </div>
                        </div>
                      ))}
                    </div>
                  </>
                )}
              </div>
            )}

            {isLiveDiagram && (
              <Button
                size="sm"
                onClick={handleStartDraft}
                disabled={forkDraft.isPending}
                title="Start a new feature draft forked from this diagram"
                className="!text-coral !border-coral/40"
              >
                Draft new feature
              </Button>
            )}

            {isForkedDiagram && currentDraft && (
              <Button
                size="sm"
                variant="primary"
                onClick={handleApply}
                disabled={applyDraft.isPending}
                leftIcon={<PublishIcon />}
                title="Apply feature changes to source diagrams"
              >
                Publish
              </Button>
            )}

            <Button
              size="sm"
              variant="ghost"
              onClick={async () => {
                const { toPng } = await import('html-to-image')
                const el = document.querySelector('.react-flow') as HTMLElement
                if (!el) return
                const dataUrl = await toPng(el, { backgroundColor: '#0a0a0b' })
                const a = document.createElement('a')
                a.href = dataUrl
                a.download = `archflow-${new Date().toISOString().slice(0, 10)}.png`
                a.click()
              }}
              title="Export as PNG"
              aria-label="Export as PNG"
            >
              <CameraIcon />
            </Button>

            <Button
              size="sm"
              variant="ghost"
              onClick={logout}
              className="!text-text-4 hover:!text-text-2"
            >
              Sign out
            </Button>
          </div>
        </div>

        {/* Forked-diagram banner — live model is frozen; edits go to the draft */}
        {isForkedDiagram && currentDraft && (
          <div
            className="flex items-center gap-3 px-4 py-1.5 border-b border-coral/30 text-[12px] text-coral shrink-0"
            style={{
              background:
                'linear-gradient(to right, rgba(255,107,53,0.12), rgba(10,10,11,0) 80%)',
            }}
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M12 20h9" />
              <path d="M16.5 3.5a2.121 2.121 0 1 1 3 3L7 19l-4 1 1-4 12.5-12.5z" />
            </svg>
            <span className="text-text-2">
              Editing feature: <b className="text-text-base">{currentDraft.name}</b> —
              edits stay on the fork; Apply merges all feature changes into their source diagrams.
            </span>
            <span className="flex-1" />
            <Button size="sm" onClick={() => navigate(`/drafts/${currentDraft.id}`)}>
              Compare
            </Button>
            <Button size="sm" variant="ghost" onClick={handleDiscard}>
              Discard
            </Button>
            <Button
              size="sm"
              variant="primary"
              onClick={handleApply}
              disabled={applyDraft.isPending}
            >
              Apply feature changes
            </Button>
          </div>
        )}

        {/* Canvas area */}
        <div className="flex flex-1 min-h-0 overflow-hidden">
          {treeOpen && <ObjectTree diagramId={diagramId} />}
          <div
            className="flex-1 relative min-w-0"
            style={{
              // Visual "you're inside a fork" frame. The canvas fills the
              // inset so the user sees a tinted viewport boundary at all times.
              boxShadow: isForkedDiagram
                ? 'inset 0 0 0 3px rgba(255,107,53,0.35)'
                : undefined,
            }}
          >
            <div className="absolute left-4 top-28 z-30">
              <AddObjectFAB diagramId={diagramId} />
            </div>
            <div className="absolute inset-0">
              <ArchFlowCanvas diagramId={diagramId} />
            </div>
            {isForkedDiagram && (
              <div
                className="absolute right-3.5 bottom-3.5 z-[5] pointer-events-none select-none uppercase font-mono"
                style={{
                  fontSize: 44,
                  fontWeight: 800,
                  letterSpacing: '0.18em',
                  color: 'rgba(255,107,53,0.07)',
                }}
              >
                Draft
              </div>
            )}
            {diagramId && <FlowsPanel diagramId={diagramId} />}
            {diagramId && <FlowPlaybackBar diagramId={diagramId} />}
            <FilterToolbar />
          </div>
          {selectedEdgeId ? <EdgeSidebar diagramId={diagramId} /> : <ObjectSidebar />}
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
