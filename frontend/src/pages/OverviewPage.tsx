import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AppSidebar } from '../components/nav/AppSidebar'
import { PageToolbar, SearchButton } from '../components/nav/PageToolbar'
import { SearchModal } from '../components/nav/SearchModal'
import { NewDiagramModal } from '../components/diagram/NewDiagramModal'
import {
  useDeleteDiagram,
  useDiagrams,
  useUpdateDiagram,
  type Diagram,
} from '../hooks/use-diagrams'
import { useConnections, useObjects, useGlobalActivity, useMe } from '../hooks/use-api'
import {
  Avatar,
  SectionLabel,
  StatusPill,
  type PillVariant,
} from '../components/ui'
import { DiagramPreviewSvg } from '../components/common/DiagramPreviewSvg'

// ─── Constants ────────────────────────────────────────────────────────────────

const DIAGRAM_TYPE_LABELS: Record<string, string> = {
  system_landscape: 'L1 · SYSTEM',
  system_context:   'L1 · CONTEXT',
  container:        'L2 · CONTAINER',
  component:        'L3 · COMPONENT',
  custom:           'CUSTOM',
}

const DIAGRAM_TYPE_LEVEL: Record<string, number> = {
  system_landscape: 1,
  system_context:   1,
  container:        2,
  component:        3,
  custom:           0,
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatDate(date: Date): string {
  return date.toLocaleDateString('en-US', {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
  }).replace(',', ' ·')
}

function timeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  return `${days}d ago`
}

function greeting(): string {
  const h = new Date().getHours()
  if (h < 12) return 'Good morning'
  if (h < 17) return 'Good afternoon'
  return 'Good evening'
}

/** Returns count of diagrams created within the last 7 days */
function thisWeekCount(items: { created_at: string }[]): number {
  const cutoff = Date.now() - 7 * 24 * 60 * 60 * 1000
  return items.filter((i) => new Date(i.created_at).getTime() > cutoff).length
}

/** Get first name from email-derived display name */
function firstNameFromEmail(email: string): string {
  const local = email.split('@')[0]
  const parts = local.split(/[._\-+]/)
  const first = parts[0] ?? local
  return first.charAt(0).toUpperCase() + first.slice(1)
}

/** First name from the authenticated user's profile (falls back gracefully). */
function useDisplayName(): string {
  const { data: me } = useMe()
  if (me?.name) {
    const first = me.name.trim().split(/\s+/)[0]
    if (first) return first.charAt(0).toUpperCase() + first.slice(1)
  }
  if (me?.email) return firstNameFromEmail(me.email)
  return 'there'
}

// ─── PreviewCard ───────────────────────────────────────────────────────────────

type DiagramStatusVariant = 'draft' | 'review' | 'done' | 'processing' | 'input'

function diagramStatusVariant(diagram: Diagram): DiagramStatusVariant {
  if (diagram.draft_id) return 'draft'
  return 'done'
}

function diagramStatusLabel(diagram: Diagram): string {
  if (diagram.draft_id) return 'DRAFT'
  return 'LIVE'
}

function PreviewCard({
  diagram,
  onClick,
  onDelete,
  onPinToggle,
}: {
  diagram: Diagram
  onClick: () => void
  onDelete: () => void
  onPinToggle: () => void
}) {
  const [menuOpen, setMenuOpen] = useState(false)
  const level = DIAGRAM_TYPE_LEVEL[diagram.type] ?? 0
  const levelStr = level > 0 ? `LVL ${level}` : 'LVL —'
  const typeStr = DIAGRAM_TYPE_LABELS[diagram.type] ?? diagram.type.toUpperCase()
  const ago = timeAgo(diagram.updated_at)
  const variant = diagramStatusVariant(diagram)
  const label = diagramStatusLabel(diagram)

  return (
    <div
      onClick={onClick}
      className="group relative bg-surface border border-border-base rounded-lg overflow-hidden cursor-pointer transition-all duration-150 hover:border-border-hi hover:-translate-y-0.5 hover:shadow-card-hover"
    >
      {/* Thumbnail */}
      <div className="h-[140px] canvas-bg relative flex items-center justify-center overflow-hidden">
        <DiagramPreviewSvg
          diagramId={diagram.id}
          fallbackType={diagram.type}
          draftId={diagram.draft_id}
          className="absolute inset-0"
        />
      </div>

      {/* Footer */}
      <div className="p-4 border-t border-border-base">
        <div className="flex items-center justify-between mb-2 gap-2">
          <div className="text-[14px] font-medium text-text-base truncate min-w-0">
            {diagram.name}
          </div>
          <StatusPill status={variant}>{label}</StatusPill>
        </div>
        <div className="flex items-center gap-1.5 font-mono text-[10.5px] text-text-3">
          <span>{levelStr}</span>
          <span>·</span>
          <span>{typeStr}</span>
          <span>·</span>
          <span>{ago}</span>
        </div>
      </div>

      {/* 3-dot menu — visible on group hover */}
      <div
        className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          onClick={() => setMenuOpen((v) => !v)}
          className="w-6 h-6 rounded bg-surface/80 backdrop-blur flex items-center justify-center text-text-3 hover:text-text-base border border-border-base hover:border-border-hi"
          title="Options"
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
            <circle cx="12" cy="5" r="1.5" /><circle cx="12" cy="12" r="1.5" /><circle cx="12" cy="19" r="1.5" />
          </svg>
        </button>
        {menuOpen && (
          <div className="absolute right-0 top-7 z-10 bg-panel border border-border-base rounded-lg shadow-popup py-1 min-w-[120px]">
            <button
              onClick={() => { setMenuOpen(false); onPinToggle() }}
              className="w-full text-left px-3 py-1.5 text-[12px] text-text-2 hover:bg-surface-hi hover:text-text-base"
            >
              {diagram.pinned ? 'Unpin' : 'Pin to overview'}
            </button>
            <button
              onClick={() => { setMenuOpen(false); onDelete() }}
              className="w-full text-left px-3 py-1.5 text-[12px] text-accent-pink hover:bg-surface-hi"
            >
              Delete
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

// ─── OverviewPage ──────────────────────────────────────────────────────────────

export function OverviewPage() {
  const { data: diagrams = [] } = useDiagrams()
  const { data: objects = [] } = useObjects()
  const { data: connections = [] } = useConnections()
  const deleteDiagram = useDeleteDiagram()
  const updateDiagram = useUpdateDiagram()
  const navigate = useNavigate()
  const firstName = useDisplayName()

  // TODO(redesign): wire real activity feed — useGlobalActivity returns backend log
  const { data: activityLog = [] } = useGlobalActivity({ limit: 5 })

  const [createOpen, setCreateOpen] = useState(false)
  const [searchOpen, setSearchOpen] = useState(false)
  const toggleSearch = useCallback(() => setSearchOpen((v) => !v), [])

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        setSearchOpen((v) => !v)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  const recent = useMemo(
    () =>
      [...diagrams]
        .sort(
          (a, b) =>
            new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
        )
        .slice(0, 6),
    [diagrams],
  )

  const drafts = useMemo(() => diagrams.filter((d) => d.draft_id), [diagrams])

  // "This week" deltas — diagrams created in the last 7 days
  const diagramsThisWeek = useMemo(() => thisWeekCount(diagrams), [diagrams])

  // Computed date string e.g. "Wednesday · April 23"
  const formattedDate = useMemo(() => formatDate(new Date()), [])

  // TODO(redesign): sharedToday — no hook exists for "diagrams shared by teammates since yesterday"
  // Placeholder subtext uses drafts count only.
  const subheadText = useMemo(() => {
    const draftCount = drafts.length
    if (draftCount === 0) {
      return 'No drafts pending. Everything looks good.'
    }
    return (
      <>
        You have{' '}
        <span className="font-mono text-[13px] text-text-base">{draftCount} draft{draftCount !== 1 ? 's' : ''}</span>{' '}
        waiting for review.
      </>
    )
  }, [drafts.length])

  // Activity items derived from activityLog; fall back to synthetic entries
  // TODO(redesign): wire real user names from activity log — ActivityLogEntry only has user_id, no display name
  const activityItems = useMemo(() => {
    if (activityLog.length > 0) {
      return activityLog.slice(0, 4).map((entry) => {
        const resolvedName =
          entry.target_type === 'diagram'
            ? diagrams.find((d) => d.id === entry.target_id)?.name
            : entry.target_type === 'object'
            ? objects.find((o) => o.id === entry.target_id)?.name
            : entry.target_type === 'connection'
            ? connections.find((c) => c.id === entry.target_id)?.label
            : undefined
        const typeLabel =
          entry.target_type === 'diagram'
            ? 'diagram'
            : entry.target_type === 'object'
            ? 'object'
            : 'connection'
        const objectOrDiagram = resolvedName
          ? resolvedName
          : `deleted ${typeLabel}`
        const actionLabel =
          entry.action === 'created' ? 'created' : entry.action === 'deleted' ? 'deleted' : 'edited'
        const pillVariant: PillVariant =
          entry.action === 'created'
            ? 'done'
            : entry.action === 'updated'
            ? 'processing'
            : 'input'
        const pillText =
          entry.action === 'created' ? 'NEW' : entry.action === 'updated' ? 'MOD' : 'DEL'
        return {
          id: entry.id,
          initials: '?',
          gradient: 'blue-purple' as const,
          text: (
            <>
              <span className="text-text-2">{actionLabel} </span>
              <span className="font-mono text-coral">{objectOrDiagram}</span>
            </>
          ),
          time: timeAgo(entry.created_at),
          pillVariant,
          pillText,
        }
      })
    }
    // Fallback: synthetic entries from recent diagrams
    return recent.slice(0, 2).map((d, i) => ({
      id: d.id,
      initials: firstName.slice(0, 2).toUpperCase(),
      gradient: 'coral-amber' as const,
      text: (
        <>
          <span className="text-text-2">created diagram </span>
          <span className="font-mono text-coral">{d.name}</span>
        </>
      ),
      time: timeAgo(d.created_at),
      pillVariant: 'done' as const,
      pillText: i === 0 ? 'NEW' : 'NEW',
    }))
  }, [activityLog, diagrams, objects, connections, recent, firstName])

  return (
    <div className="flex h-screen bg-bg text-text-base">
      <AppSidebar />
      <div className="flex-1 flex flex-col overflow-hidden">
        <PageToolbar
          breadcrumb={['Overview']}
          actions={
            <>
              <SearchButton onClick={toggleSearch} />
              <button
                onClick={() => setCreateOpen(true)}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-coral border border-coral text-bg text-[12.5px] font-medium hover:bg-coral-2 hover:border-coral-2 transition-colors"
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                  <path d="M12 5v14M5 12h14" />
                </svg>
                New diagram
              </button>
            </>
          }
        />

        {/* Main scrollable content */}
        <div className="flex-1 overflow-y-auto p-8">

          {/* ── Hero row ── */}
          <div className="flex items-end justify-between mb-10">
            <div>
              <SectionLabel className="mb-3">{formattedDate}</SectionLabel>
              <h1 className="text-[32px] leading-tight tracking-tight font-semibold">
                {greeting()}, {firstName}{' '}
                <span className="font-serif italic text-coral">—</span>
              </h1>
              <p className="text-[14px] text-text-2 mt-2 max-w-lg">
                {subheadText}
              </p>
            </div>
            {/* TODO(redesign): workspace presence count — no global presence hook exposed outside DiagramSocket.
                Show pill only when we have real data. Hidden for now. */}
          </div>

          {/* ── Stats grid ── */}
          <div className="grid grid-cols-4 gap-3 mb-10">
            {/* Total diagrams */}
            <div className="bg-surface border border-border-base rounded-lg p-5 hover:border-border-hi hover:bg-surface-hi hover:-translate-y-px transition-all duration-150 cursor-default">
              <SectionLabel>Total diagrams</SectionLabel>
              <div className="flex items-baseline gap-2 mt-2">
                <div className="text-[28px] font-semibold tracking-tight text-text-base">
                  {diagrams.length}
                </div>
                {diagramsThisWeek > 0 && (
                  <div className="font-mono text-[11px] text-accent-green">
                    +{diagramsThisWeek} this week
                  </div>
                )}
              </div>
            </div>

            {/* Model objects */}
            <div className="bg-surface border border-border-base rounded-lg p-5 hover:border-border-hi hover:bg-surface-hi hover:-translate-y-px transition-all duration-150 cursor-default">
              <SectionLabel>Model objects</SectionLabel>
              <div className="flex items-baseline gap-2 mt-2">
                <div className="text-[28px] font-semibold tracking-tight text-text-base">
                  {objects.length}
                </div>
                <div className="font-mono text-[11px] text-text-3">objects</div>
              </div>
            </div>

            {/* Connections */}
            <div className="bg-surface border border-border-base rounded-lg p-5 hover:border-border-hi hover:bg-surface-hi hover:-translate-y-px transition-all duration-150 cursor-default">
              <SectionLabel>Connections</SectionLabel>
              <div className="flex items-baseline gap-2 mt-2">
                <div className="text-[28px] font-semibold tracking-tight text-text-base">
                  {connections.length}
                </div>
                <div className="font-mono text-[11px] text-text-3">traced</div>
              </div>
            </div>

            {/* Drafts awaiting — pink accented */}
            <div
              className="rounded-lg p-5 hover:-translate-y-px transition-all duration-150 cursor-default"
              style={{
                border: '1px solid rgba(244,114,182,0.25)',
                background:
                  'linear-gradient(to bottom right, rgba(244,114,182,0.05), transparent)',
              }}
            >
              <SectionLabel className="[&>span]:text-accent-pink">
                Drafts awaiting
              </SectionLabel>
              <div className="flex items-baseline gap-2 mt-2">
                <div
                  className="text-[28px] font-semibold tracking-tight"
                  style={{ color: 'var(--color-accent-pink)' }}
                >
                  {drafts.length}
                </div>
                <div className="font-mono text-[11px] text-text-2">
                  {drafts.length === 0 ? 'none pending' : 'needs input'}
                </div>
              </div>
            </div>
          </div>

          {/* ── Recent diagrams ── */}
          <div className="mb-10">
            <div className="flex items-end justify-between mb-4">
              <div>
                <SectionLabel className="mb-1">Recent / last edited</SectionLabel>
                <div className="text-[15px] font-medium text-text-base">
                  Continue where you left off
                </div>
              </div>
              <button
                onClick={() => navigate('/diagrams')}
                className="font-mono text-[11px] text-text-3 hover:text-coral transition-colors"
              >
                view all →
              </button>
            </div>

            {recent.length === 0 ? (
              <div className="text-[12px] text-text-3 italic border border-dashed border-border-base rounded-lg p-6">
                No diagrams yet. Click "New diagram" to start.
              </div>
            ) : (
              <div className="grid grid-cols-3 gap-4">
                {recent.slice(0, 3).map((d) => (
                  <PreviewCard
                    key={d.id}
                    diagram={d}
                    onClick={() => navigate(`/diagram/${d.id}`)}
                    onDelete={() => {
                      if (confirm(`Delete diagram "${d.name}"?`))
                        deleteDiagram.mutate(d.id)
                    }}
                    onPinToggle={() =>
                      updateDiagram.mutate({ id: d.id, pinned: !d.pinned })
                    }
                  />
                ))}
              </div>
            )}
          </div>

          {/* ── Activity feed + Quick start ── */}
          <div className="grid grid-cols-3 gap-6">
            {/* Activity feed (col-span-2) */}
            <div className="col-span-2">
              <SectionLabel className="mb-3">Activity stream</SectionLabel>
              {activityItems.length === 0 ? (
                <div className="py-6 text-[12px] text-text-3 italic">
                  No activity yet.
                </div>
              ) : (
                <div>
                  {activityItems.map((item, idx) => (
                    <div
                      key={item.id}
                      className={`flex items-start gap-3 py-3 ${idx < activityItems.length - 1 ? 'border-b border-border-base' : ''}`}
                    >
                      <Avatar initials={item.initials} gradient={item.gradient} size="sm" />
                      <div className="flex-1 min-w-0">
                        <div className="text-[13px]">
                          <span className="font-medium text-text-base">You </span>
                          {item.text}
                        </div>
                        <div className="font-mono text-[10.5px] text-text-3 mt-1">
                          {item.time}
                        </div>
                      </div>
                      <StatusPill status={item.pillVariant}>
                        {item.pillText}
                      </StatusPill>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Quick start (col-span-1) */}
            <div>
              <SectionLabel className="mb-3">Quick start</SectionLabel>
              <div className="space-y-2">
                {/* Primary — coral accented */}
                <button
                  onClick={() => setCreateOpen(true)}
                  className="w-full text-left p-4 rounded-lg border border-border-base bg-surface hover:border-coral hover:bg-coral-glow transition-all duration-150 group"
                >
                  <div className="flex items-center gap-2 mb-1">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#FF6B35" strokeWidth="2">
                      <path d="M12 5v14M5 12h14" />
                    </svg>
                    <div className="text-[13px] font-medium text-text-base">New diagram</div>
                  </div>
                  <div className="font-mono text-[10.5px] text-text-3 group-hover:text-text-2 transition-colors">
                    Start blank or from template
                  </div>
                </button>

                {/* Import from C4 */}
                <button
                  className="w-full text-left p-4 rounded-lg border border-border-base bg-surface hover:border-border-hi transition-all duration-150"
                  title="Import from C4 — coming soon"
                  disabled
                >
                  <div className="flex items-center gap-2 mb-1">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-text-3">
                      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4m4-5 5-5 5 5m-5-5v12" />
                    </svg>
                    <div className="text-[13px] font-medium text-text-2">Import from C4</div>
                  </div>
                  <div className="font-mono text-[10.5px] text-text-3">
                    PlantUML / Structurizr / JSON
                  </div>
                </button>

                {/* Invite teammates */}
                <button
                  onClick={() => navigate('/members')}
                  className="w-full text-left p-4 rounded-lg border border-border-base bg-surface hover:border-border-hi transition-all duration-150"
                >
                  <div className="flex items-center gap-2 mb-1">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-text-3">
                      <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
                      <circle cx="9" cy="7" r="4" />
                      <path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75" />
                    </svg>
                    <div className="text-[13px] font-medium text-text-2">Invite teammates</div>
                  </div>
                  <div className="font-mono text-[10.5px] text-text-3">
                    Collaborate in real-time
                  </div>
                </button>
              </div>
            </div>
          </div>

        </div>
      </div>
      <SearchModal open={searchOpen} onClose={toggleSearch} />
      <NewDiagramModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={(d) => navigate(`/diagram/${d.id}`)}
      />
    </div>
  )
}
