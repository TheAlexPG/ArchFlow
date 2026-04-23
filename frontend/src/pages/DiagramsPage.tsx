import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AppSidebar } from '../components/nav/AppSidebar'
import { PageToolbar } from '../components/nav/PageToolbar'
import { Button } from '../components/ui/Button'
import { Kbd } from '../components/ui/Kbd'
import { LevelBar } from '../components/ui/LevelBar'
import { SectionLabel } from '../components/ui/SectionLabel'
import { StatusPill } from '../components/ui/Pill'
import type { PillVariant } from '../components/ui/Pill'
import { PreviewCard } from '../components/common/PreviewCard'
import {
  useDiagrams,
  useCreateDiagram,
  useDeleteDiagram,
  useUpdateDiagram,
} from '../hooks/use-diagrams'
import {
  usePacks,
  useCreatePack,
  useRenamePack,
  useDeletePack,
  useSetDiagramPack,
} from '../hooks/use-api'
import { useWorkspaceStore } from '../stores/workspace-store'
import { useWorkspaces } from '../hooks/use-api'
import type { DiagramPack, DiagramType } from '../types/model'
import { cn } from '../utils/cn'

// ─── Constants ───────────────────────────────────────────────────────────────

const C4_LEVEL: Record<string, { label: string; order: number; level: 1 | 2 | 3 | 4 }> = {
  system_landscape: { label: 'Level 1', order: 1, level: 1 },
  system_context:   { label: 'Level 1', order: 1, level: 1 },
  container:        { label: 'Level 2', order: 2, level: 2 },
  component:        { label: 'Level 3', order: 3, level: 3 },
  custom:           { label: 'Custom',  order: 9, level: 4 },
}

const TYPE_LABELS: Record<string, string> = {
  system_landscape: 'System Landscape',
  system_context:   'System Context',
  container:        'Container',
  component:        'Component',
  custom:           'Custom',
}

const DIAGRAM_TYPE_LABELS_FOR_CREATE: Record<string, string> = {
  system_landscape: 'L1 — System Landscape',
  system_context:   'L1 — System Context',
  container:        'L2 — Container',
  component:        'L3 — Component',
  custom:           'Custom',
}

// Types in display order for grouped table
const ORDERED_TYPES: DiagramType[] = [
  'system_landscape',
  'system_context',
  'container',
  'component',
  'custom',
]

// Type → sidebar pack color
const TYPE_COLOR: Record<string, { folder: string; icon: string; well: string }> = {
  system_landscape: { folder: '#c084fc', icon: '#c084fc', well: 'bg-accent-purple-glow' },
  system_context:   { folder: '#c084fc', icon: '#c084fc', well: 'bg-accent-purple-glow' },
  container:        { folder: '#FF6B35', icon: '#FF6B35', well: 'bg-coral-glow' },
  component:        { folder: '#60a5fa', icon: '#60a5fa', well: 'bg-accent-blue-glow' },
  custom:           { folder: '#4ade80', icon: '#4ade80', well: 'bg-accent-green-glow' },
}

// Level → C4 filter sidebar
const LEVEL_ROWS: { level: 1 | 2 | 3 | 4; label: string; types: string[] }[] = [
  { level: 1, label: 'Level 1 · Landscape', types: ['system_landscape', 'system_context'] },
  { level: 2, label: 'Level 2 · Container',  types: ['container'] },
  { level: 3, label: 'Level 3 · Component',  types: ['component'] },
  { level: 4, label: 'Level 4 · Code',       types: ['custom'] },
]

// ─── Helpers ─────────────────────────────────────────────────────────────────

function timeAgo(iso: string): string {
  const seconds = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (seconds < 60) return 'just now'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days}d ago`
  return new Date(iso).toLocaleDateString()
}

function diagramStatus(d: { draft_id: string | null }): Exclude<PillVariant, 'neutral'> {
  if (d.draft_id) return 'draft'
  return 'done'
}

function slugify(name: string): string {
  return name.toLowerCase().replace(/\s+/g, '-').replace(/[^a-z0-9-]/g, '')
}

// ─── Icon SVGs per type ───────────────────────────────────────────────────────

function TypeIcon({ type }: { type: string }) {
  const color = TYPE_COLOR[type]?.icon ?? '#71717a'
  const well = TYPE_COLOR[type]?.well ?? 'bg-surface'

  const svg = (() => {
    switch (type) {
      case 'container':
        return <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 9h6v6H9z"/></svg>
      case 'system_landscape':
      case 'system_context':
        return <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="4"/></svg>
      case 'component':
        return <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2"><rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/></svg>
      default:
        return <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>
    }
  })()

  return (
    <div className={cn('w-6 h-6 rounded-md border border-border-base flex items-center justify-center flex-shrink-0', well)}>
      {svg}
    </div>
  )
}

// ─── Folder icon for sidebar ──────────────────────────────────────────────────

function FolderIcon({ color }: { color: string }) {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill={color + '40'} stroke={color} strokeWidth="1.5">
      <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
    </svg>
  )
}

function ChevronDown() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="m6 9 6 6 6-6"/>
    </svg>
  )
}

// ─── Main page ────────────────────────────────────────────────────────────────

export function DiagramsPage() {
  const { data: diagrams = [], isLoading } = useDiagrams()
  const createDiagram = useCreateDiagram()
  const deleteDiagram = useDeleteDiagram()
  const updateDiagram = useUpdateDiagram()
  const navigate = useNavigate()

  // Search / filter state
  const [search, setSearch] = useState('')
  const [selectedTypeFilter, setSelectedTypeFilter] = useState<string | null>(null)

  // View mode
  const [view, setView] = useState<'list' | 'grid'>('list')

  // Create modal state
  const [showCreate, setShowCreate] = useState(false)
  const [newName, setNewName] = useState('')
  const [newType, setNewType] = useState('system_landscape')

  // Pack management state (preserved)
  const [newPackName, setNewPackName] = useState('')
  const [showNewPackInput, setShowNewPackInput] = useState(false)
  const [renamingPack, setRenamingPack] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState('')

  const wsId = useWorkspaceStore((s) => s.currentWorkspaceId)
  const { data: workspaces = [] } = useWorkspaces()
  const currentWs = workspaces.find((w) => w.id === wsId) ?? null
  const isAdmin = currentWs?.role === 'owner' || currentWs?.role === 'admin'

  const { data: packs = [] } = usePacks(wsId)
  const createPack = useCreatePack(wsId)
  const renamePack = useRenamePack(wsId)
  const deletePack = useDeletePack(wsId)
  const setDiagramPack = useSetDiagramPack()

  // ── Filtered + sorted diagrams ─────────────────────────────────────────────
  const filtered = useMemo(() => {
    let rows = diagrams
    if (search) {
      const q = search.toLowerCase()
      rows = rows.filter((d) => d.name.toLowerCase().includes(q))
    }
    if (selectedTypeFilter) {
      // If the filter matches a level row, expand to all types in that level
      const levelRow = LEVEL_ROWS.find((lr) => lr.types.includes(selectedTypeFilter))
      const matchTypes = levelRow ? levelRow.types : [selectedTypeFilter]
      rows = rows.filter((d) => matchTypes.includes(d.type))
    }
    return [...rows].sort(
      (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
    )
  }, [diagrams, search, selectedTypeFilter])

  // ── Counts per type (full, unfiltered — for sidebar) ──────────────────────
  const countByType = useMemo(() => {
    const map: Record<string, number> = {}
    for (const d of diagrams) {
      map[d.type] = (map[d.type] ?? 0) + 1
    }
    return map
  }, [diagrams])

  const countByLevel = useMemo(() => {
    return LEVEL_ROWS.map((lr) => ({
      ...lr,
      count: diagrams.filter((d) => lr.types.includes(d.type)).length,
    }))
  }, [diagrams])

  // ── Pack handlers ──────────────────────────────────────────────────────────
  const handleCreatePack = () => {
    const name = newPackName.trim()
    if (!name) return
    createPack.mutate(name)
    setNewPackName('')
    setShowNewPackInput(false)
  }

  const handleRenamePack = (packId: string) => {
    const name = renameValue.trim()
    if (!name) return
    renamePack.mutate({ packId, name })
    setRenamingPack(null)
    setRenameValue('')
  }

  // ── Create diagram handler ─────────────────────────────────────────────────
  const handleCreate = () => {
    if (!newName.trim()) return
    createDiagram.mutate(
      { name: newName.trim(), type: newType },
      {
        onSuccess: (diagram) => {
          setShowCreate(false)
          setNewName('')
          navigate(`/diagram/${diagram.id}`)
        },
      },
    )
  }

  const sortedPacks: DiagramPack[] = [...packs].sort(
    (a, b) => a.sort_order - b.sort_order || a.name.localeCompare(b.name),
  )

  // ── Header meta ──────────────────────────────────────────────────────────
  const headerTitle = selectedTypeFilter
    ? (TYPE_LABELS[selectedTypeFilter] ?? 'Filtered')
    : 'All Diagrams'
  const headerBreadcrumb = selectedTypeFilter ? `type / ${selectedTypeFilter}` : 'all diagrams'

  const mostRecentUpdate = filtered[0]?.updated_at
  const metaLine = `${filtered.length} diagram${filtered.length !== 1 ? 's' : ''}${mostRecentUpdate ? ` · last updated ${timeAgo(mostRecentUpdate)}` : ''}`

  // ── Tree item helper ──────────────────────────────────────────────────────
  const treeItemCls = (active: boolean) =>
    cn(
      'flex items-center gap-2 px-2 py-1.5 rounded text-[12.5px] cursor-pointer transition-colors duration-[100ms]',
      active
        ? 'bg-coral-glow text-coral'
        : 'text-text-2 hover:bg-surface hover:text-text-base',
    )

  // ── Grouped table rows ────────────────────────────────────────────────────
  const grouped = useMemo(() => {
    return ORDERED_TYPES.map((type) => ({
      type,
      label: (TYPE_LABELS[type] ?? type).toUpperCase(),
      items: filtered.filter((d) => d.type === type),
    })).filter((g) => g.items.length > 0)
  }, [filtered])

  // ── Pack management (preserve) ────────────────────────────────────────────
  const packMap: Record<string, typeof filtered> = {}
  for (const p of sortedPacks) {
    packMap[p.id] = filtered.filter((d) => d.pack_id === p.id)
  }

  return (
    <div className="flex h-screen bg-bg text-text-base">
      <AppSidebar />
      <div className="flex-1 flex flex-col overflow-hidden">
        <PageToolbar breadcrumb={['Diagrams']} />

        {/* ── Two-column body ─────────────────────────────────────────── */}
        <div className="flex flex-1 overflow-hidden">

          {/* ── Folder sidebar ──────────────────────────────────────────── */}
          <aside className="w-[260px] flex-shrink-0 bg-panel border-r border-border-base flex flex-col overflow-hidden">

            {/* Sidebar header */}
            <div className="p-4 border-b border-border-base flex items-center justify-between flex-shrink-0">
              <div className="flex items-center gap-2 text-text-base">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                  <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
                </svg>
                <span className="text-[13px] font-medium">Diagrams</span>
              </div>
              <Button
                size="icon"
                variant="ghost"
                onClick={() => setShowCreate(true)}
                title="New diagram"
              >
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M12 5v14M5 12h14"/>
                </svg>
              </Button>
            </div>

            {/* Sidebar scroll body */}
            <div className="flex-1 overflow-y-auto p-3 space-y-4">

              {/* Pinned section */}
              <div>
                <SectionLabel counter={diagrams.filter((d) => d.pinned).length} className="mb-2 px-2">
                  Pinned
                </SectionLabel>
                <div
                  className={treeItemCls(selectedTypeFilter === '__recent__')}
                  onClick={() => setSelectedTypeFilter(
                    selectedTypeFilter === '__recent__' ? null : '__recent__'
                  )}
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <circle cx="12" cy="12" r="10"/>
                    <path d="M12 6v6l4 2"/>
                  </svg>
                  <span className="flex-1">Recent</span>
                  <span className="font-mono text-[10.5px] text-text-3">
                    {diagrams.filter((d) => d.pinned).length}
                  </span>
                </div>
              </div>

              {/* Packs section — grouped by type */}
              <div>
                <SectionLabel counter={ORDERED_TYPES.length} className="mb-2 px-2">
                  Packs
                </SectionLabel>
                <div className="space-y-0.5">
                  {ORDERED_TYPES.map((type) => {
                    const count = countByType[type] ?? 0
                    if (count === 0) return null
                    const color = TYPE_COLOR[type]?.folder ?? '#71717a'
                    const isActive = selectedTypeFilter === type
                    return (
                      <div
                        key={type}
                        className={treeItemCls(isActive)}
                        onClick={() => setSelectedTypeFilter(isActive ? null : type)}
                      >
                        <ChevronDown />
                        <FolderIcon color={color} />
                        <span className="flex-1 truncate">{TYPE_LABELS[type] ?? type}</span>
                        <span className="font-mono text-[10.5px] text-text-3">{count}</span>
                      </div>
                    )
                  })}
                </div>

                {/* Admin: new pack input */}
                {isAdmin && (
                  <div className="mt-1">
                    {showNewPackInput ? (
                      <div className="flex items-center gap-1 px-2 py-1">
                        <input
                          autoFocus
                          value={newPackName}
                          onChange={(e) => setNewPackName(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') handleCreatePack()
                            if (e.key === 'Escape') { setShowNewPackInput(false); setNewPackName('') }
                          }}
                          placeholder="Pack name…"
                          className="flex-1 bg-surface border border-border-base rounded px-2 py-0.5 text-[11.5px] outline-none focus:border-border-hi font-mono"
                        />
                        <button onClick={handleCreatePack} className="text-[11px] text-text-3 hover:text-text-base px-1">Save</button>
                        <button onClick={() => { setShowNewPackInput(false); setNewPackName('') }} className="text-[11px] text-text-4 hover:text-text-3 px-1">✕</button>
                      </div>
                    ) : (
                      <button
                        onClick={() => setShowNewPackInput(true)}
                        className="w-full text-left text-[12px] text-text-4 hover:text-text-3 px-2 py-1 transition-colors"
                      >
                        + New pack
                      </button>
                    )}
                  </div>
                )}
              </div>

              {/* C4 Level filter */}
              <div>
                <SectionLabel className="mb-2 px-2">C4 Level filter</SectionLabel>
                <div className="space-y-0.5">
                  {countByLevel.map(({ level, label, types, count }) => {
                    const isActive = types.some((t) => t === selectedTypeFilter)
                    return (
                      <div
                        key={level}
                        className={treeItemCls(isActive)}
                        onClick={() => {
                          // toggle: if already selected, clear; else set first type of this level
                          if (isActive) {
                            setSelectedTypeFilter(null)
                          } else {
                            setSelectedTypeFilter(types[0])
                          }
                        }}
                      >
                        <LevelBar level={level} />
                        <span className="flex-1">{label}</span>
                        <span className="font-mono text-[10.5px] text-text-3">{count}</span>
                      </div>
                    )
                  })}
                </div>
              </div>

              {/* Pack list (real packs from API) */}
              {sortedPacks.length > 0 && (
                <div>
                  <SectionLabel counter={sortedPacks.length} className="mb-2 px-2">
                    Workspace packs
                  </SectionLabel>
                  <div className="space-y-0.5">
                    {sortedPacks.map((pack) => {
                      const count = packMap[pack.id]?.length ?? 0
                      const isRenaming = renamingPack === pack.id
                      return (
                        <div key={pack.id} className="group">
                          {isRenaming ? (
                            <div className="flex items-center gap-1 px-2 py-1">
                              <input
                                autoFocus
                                value={renameValue}
                                onChange={(e) => setRenameValue(e.target.value)}
                                onKeyDown={(e) => {
                                  if (e.key === 'Enter') handleRenamePack(pack.id)
                                  if (e.key === 'Escape') { setRenamingPack(null); setRenameValue('') }
                                }}
                                className="flex-1 bg-surface border border-border-base rounded px-1.5 py-0.5 text-[11.5px] outline-none focus:border-border-hi font-mono"
                              />
                              <button onClick={() => handleRenamePack(pack.id)} className="text-[10px] text-text-3 hover:text-text-base px-1">Save</button>
                              <button onClick={() => { setRenamingPack(null); setRenameValue('') }} className="text-[10px] text-text-4 px-1">✕</button>
                            </div>
                          ) : (
                            <div className={treeItemCls(false)}>
                              <ChevronDown />
                              <FolderIcon color="#71717a" />
                              <span className="flex-1 truncate">{pack.name}</span>
                              <span className="font-mono text-[10.5px] text-text-3">{count}</span>
                              {isAdmin && (
                                <div className="hidden group-hover:flex items-center gap-0.5 ml-1" onClick={(e) => e.stopPropagation()}>
                                  <button
                                    onClick={() => { setRenamingPack(pack.id); setRenameValue(pack.name) }}
                                    className="text-[10px] text-text-4 hover:text-text-3 px-0.5"
                                    title="Rename"
                                  >✎</button>
                                  <button
                                    onClick={() => { if (confirm(`Delete pack "${pack.name}"?`)) deletePack.mutate(pack.id) }}
                                    className="text-[10px] text-text-4 hover:text-red-400 px-0.5"
                                    title="Delete"
                                  >✕</button>
                                </div>
                              )}
                            </div>
                          )}
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}
            </div>
          </aside>

          {/* ── Content area ────────────────────────────────────────────── */}
          <section className="flex-1 flex flex-col overflow-hidden">

            {/* Inner toolbar */}
            <div className="px-8 py-5 border-b border-border-base flex items-end justify-between flex-shrink-0 gap-4">
              <div>
                <div className="font-mono text-[11px] text-text-3">{headerBreadcrumb}</div>
                <h2 className="text-[22px] font-semibold tracking-tight text-text-base mt-1">{headerTitle}</h2>
                <div className="text-[12.5px] text-text-2 mt-1">{metaLine}</div>
              </div>

              <div className="flex items-center gap-2 flex-shrink-0">
                {/* Search input */}
                <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-md border border-border-base bg-surface w-48">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-text-3 flex-shrink-0">
                    <circle cx="11" cy="11" r="8"/>
                    <path d="m21 21-4.35-4.35"/>
                  </svg>
                  <input
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder="Search diagrams…"
                    className="bg-transparent outline-none text-[12.5px] text-text-base placeholder:text-text-4 w-full"
                  />
                </div>

                {/* Filters stub */}
                <Button
                  leftIcon={
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M3 6h18M7 12h10M10 18h4"/>
                    </svg>
                  }
                >
                  Filters
                </Button>

                {/* List / Grid view toggle */}
                <div className="flex items-center border border-border-base rounded-md overflow-hidden">
                  <button
                    onClick={() => setView('list')}
                    title="List view"
                    className={cn(
                      'p-1.5 transition-colors',
                      view === 'list'
                        ? 'bg-surface-hi text-text-base'
                        : 'bg-surface text-text-3 hover:text-text-base',
                    )}
                  >
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>
                    </svg>
                  </button>
                  <button
                    onClick={() => setView('grid')}
                    title="Grid view"
                    className={cn(
                      'p-1.5 transition-colors',
                      view === 'grid'
                        ? 'bg-surface-hi text-text-base'
                        : 'bg-surface text-text-3 hover:text-text-base',
                    )}
                  >
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/>
                      <rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/>
                    </svg>
                  </button>
                </div>

                {/* New diagram */}
                <Button
                  variant="primary"
                  onClick={() => setShowCreate(true)}
                  leftIcon={
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                      <path d="M12 5v14M5 12h14"/>
                    </svg>
                  }
                >
                  New diagram
                </Button>
              </div>
            </div>

            {/* Create modal (inline, preserved behavior) */}
            {showCreate && (
              <div className="mx-8 mt-4 bg-panel border border-border-base rounded-lg p-4 max-w-lg flex-shrink-0">
                <div className="text-[13px] font-medium mb-3 text-text-base">New diagram</div>
                <input
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder="Diagram name…"
                  autoFocus
                  onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
                  className="w-full bg-surface border border-border-base rounded px-3 py-1.5 text-[13px] outline-none focus:border-border-hi mb-2 text-text-base placeholder:text-text-4"
                />
                <select
                  value={newType}
                  onChange={(e) => setNewType(e.target.value)}
                  className="w-full bg-surface border border-border-base rounded px-3 py-1.5 text-[13px] outline-none focus:border-border-hi mb-3 text-text-base"
                >
                  {Object.entries(DIAGRAM_TYPE_LABELS_FOR_CREATE).map(([value, label]) => (
                    <option key={value} value={value}>{label}</option>
                  ))}
                </select>
                <div className="flex gap-2">
                  <Button variant="primary" onClick={handleCreate}>Create</Button>
                  <Button onClick={() => { setShowCreate(false); setNewName('') }}>Cancel</Button>
                </div>
              </div>
            )}

            {isLoading && (
              <div className="px-8 py-4 text-[12.5px] text-text-3">Loading…</div>
            )}

            {/* ── List view ─────────────────────────────────────────────── */}
            {view === 'list' && !isLoading && (
              <div className="flex-1 overflow-y-auto">
                {/* Column header */}
                <div
                  className="sticky top-0 bg-panel z-10 px-8 py-2 grid gap-3 border-b border-border-base"
                  style={{ gridTemplateColumns: '1.5rem 2fr 1fr 0.7fr 1fr 5rem' }}
                >
                  <div />
                  {(['DIAGRAM', 'TYPE', 'LEVEL', 'UPDATED', 'STATUS'] as const).map((col) => (
                    <div key={col} className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-text-3">
                      {col}
                    </div>
                  ))}
                </div>

                {/* Grouped rows */}
                {grouped.length === 0 && (
                  <div className="px-8 py-6 text-[12.5px] text-text-3 italic">
                    No diagrams match the current filter.
                  </div>
                )}

                {grouped.map(({ type, label, items }) => (
                  <div key={type}>
                    {/* Group header */}
                    <div className="px-8 py-2 bg-surface border-b border-border-base flex items-center gap-2">
                      <ChevronDown />
                      <span className="font-mono text-[11.5px] tracking-[0.04em] uppercase text-text-2">
                        {label}
                      </span>
                      <span className="font-mono text-[10.5px] text-text-3 ml-1">· {items.length}</span>
                    </div>

                    {/* Rows */}
                    {items.map((d) => {
                      const level = C4_LEVEL[d.type]?.level ?? 4
                      const status = diagramStatus(d)
                      const slug = slugify(d.name)

                      return (
                        <div
                          key={d.id}
                          className="grid gap-3 px-8 py-2.5 items-center border-b border-border-base cursor-pointer text-[13px] hover:bg-surface transition-colors duration-[80ms] group"
                          style={{ gridTemplateColumns: '1.5rem 2fr 1fr 0.7fr 1fr 5rem' }}
                          onClick={() => navigate(`/diagram/${d.id}`)}
                        >
                          {/* Icon well */}
                          <TypeIcon type={d.type} />

                          {/* Name */}
                          <div className="min-w-0">
                            <div className="text-[13.5px] font-medium text-text-base truncate">
                              {d.name}
                              {d.draft_id && (
                                <span className="font-mono text-[10px] text-text-3 ml-2">(modified)</span>
                              )}
                            </div>
                            <div className="font-mono text-[10.5px] text-text-3 truncate">
                              {slug}
                            </div>
                          </div>

                          {/* Type */}
                          <div className="text-[12px] text-text-2">{TYPE_LABELS[d.type] ?? d.type}</div>

                          {/* Level */}
                          <div>
                            <LevelBar level={level} />
                          </div>

                          {/* Updated */}
                          <div className="font-mono text-[11.5px] text-text-3">{timeAgo(d.updated_at)}</div>

                          {/* Status + row actions */}
                          <div className="flex items-center justify-end gap-2">
                            <StatusPill status={status}>
                              {status === 'done' ? 'LIVE' : status.toUpperCase()}
                            </StatusPill>
                            {/* 3-dot menu on hover */}
                            <div
                              className="hidden group-hover:flex items-center gap-1"
                              onClick={(e) => e.stopPropagation()}
                            >
                              <PackMoveMenu
                                packs={packs}
                                currentPackId={d.pack_id}
                                onSelect={(packId) => setDiagramPack.mutate({ diagramId: d.id, packId })}
                              />
                              <button
                                onClick={() => updateDiagram.mutate({ id: d.id, pinned: !d.pinned })}
                                title={d.pinned ? 'Unpin' : 'Pin'}
                                className="text-[10px] text-text-4 hover:text-text-3"
                              >
                                {d.pinned ? '📌' : '📍'}
                              </button>
                              <button
                                onClick={() => { if (confirm(`Delete "${d.name}"?`)) deleteDiagram.mutate(d.id) }}
                                className="text-[10px] text-text-4 hover:text-red-400"
                              >
                                ✕
                              </button>
                            </div>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                ))}
              </div>
            )}

            {/* ── Grid view ─────────────────────────────────────────────── */}
            {view === 'grid' && !isLoading && (
              <div className="flex-1 overflow-y-auto">
                <div className="grid grid-cols-3 gap-4 p-8">
                  {filtered.map((d) => {
                    const status = diagramStatus(d)
                    return (
                      <PreviewCard
                        key={d.id}
                        name={d.name}
                        typeLabel={TYPE_LABELS[d.type] ?? d.type}
                        slug={slugify(d.name)}
                        updatedLabel={timeAgo(d.updated_at)}
                        status={status}
                        isModified={!!d.draft_id}
                        onClick={() => navigate(`/diagram/${d.id}`)}
                      />
                    )
                  })}
                  {filtered.length === 0 && (
                    <div className="col-span-3 text-[12.5px] text-text-3 italic py-6">
                      No diagrams match the current filter.
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* ── Bottom status strip ──────────────────────────────────── */}
            <div className="px-8 py-2 border-t border-border-base flex items-center justify-between flex-shrink-0">
              <span className="font-mono text-[11px] text-text-3">
                {filtered.length} total
                {selectedTypeFilter || search ? ` · ${filtered.length} filtered` : ''}
                {' '}· {diagrams.length} in workspace
              </span>
              <div className="flex items-center gap-1.5 font-mono text-[10.5px] text-text-3">
                <Kbd>↑↓</Kbd>
                <span>navigate</span>
                <Kbd>↵</Kbd>
                <span>open</span>
              </div>
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}

// ─── PackMoveMenu (preserved) ─────────────────────────────────────────────────

function PackMoveMenu({
  packs,
  currentPackId,
  onSelect,
}: {
  packs: DiagramPack[]
  currentPackId: string | null
  onSelect: (packId: string | null) => void
}) {
  const [open, setOpen] = useState(false)

  return (
    <div className="relative">
      <button
        onClick={(e) => { e.stopPropagation(); setOpen((v) => !v) }}
        className="text-[10px] text-text-4 hover:text-text-3"
        title="Move to pack"
      >
        ⋯
      </button>
      {open && (
        <div
          className="absolute right-0 top-full mt-1 z-20 bg-panel border border-border-base rounded-md shadow-lg min-w-[140px]"
          onClick={(e) => e.stopPropagation()}
        >
          <button
            className={cn(
              'w-full text-left px-3 py-1.5 text-[11.5px] hover:bg-surface transition-colors',
              currentPackId === null ? 'text-coral' : 'text-text-2',
            )}
            onClick={() => { onSelect(null); setOpen(false) }}
          >
            Unfiled
          </button>
          {packs.map((p) => (
            <button
              key={p.id}
              className={cn(
                'w-full text-left px-3 py-1.5 text-[11.5px] hover:bg-surface transition-colors',
                currentPackId === p.id ? 'text-coral' : 'text-text-2',
              )}
              onClick={() => { onSelect(p.id); setOpen(false) }}
            >
              {p.name}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
