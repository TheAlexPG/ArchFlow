import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AppSidebar } from '../components/nav/AppSidebar'
import { PageToolbar, SearchButton } from '../components/nav/PageToolbar'
import { SearchModal } from '../components/nav/SearchModal'
import {
  useCreateDiagram,
  useDeleteDiagram,
  useDiagrams,
  useUpdateDiagram,
  type Diagram,
} from '../hooks/use-diagrams'
import { useConnections, useObjects } from '../hooks/use-api'

const DIAGRAM_TYPE_LABELS: Record<string, string> = {
  system_landscape: 'L1 — System Landscape',
  system_context: 'L1 — System Context',
  container: 'L2 — Container',
  component: 'L3 — Component',
  custom: 'Custom',
}

const DIAGRAM_TYPE_ICONS: Record<string, string> = {
  system_landscape: '🌐',
  system_context: '◉',
  container: '▦',
  component: '◧',
  custom: '✦',
}

export function OverviewPage() {
  const { data: diagrams = [] } = useDiagrams()
  const { data: objects = [] } = useObjects()
  const { data: connections = [] } = useConnections()
  const createDiagram = useCreateDiagram()
  const deleteDiagram = useDeleteDiagram()
  const updateDiagram = useUpdateDiagram()
  const navigate = useNavigate()
  const [showCreate, setShowCreate] = useState(false)
  const [newName, setNewName] = useState('')
  const [newType, setNewType] = useState('system_landscape')
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

  const pinned = useMemo(() => diagrams.filter((d) => d.pinned), [diagrams])
  const recent = useMemo(
    () =>
      [...diagrams]
        .sort(
          (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
        )
        .slice(0, 6),
    [diagrams],
  )

  // Health checks reuse data already fetched — cheap, no extra roundtrip.
  const orphanObjects = useMemo(
    () =>
      objects.filter(
        (o) =>
          !connections.some((c) => c.source_id === o.id || c.target_id === o.id),
      ).length,
    [objects, connections],
  )
  const missingDescriptions = useMemo(
    () => objects.filter((o) => !o.description).length,
    [objects],
  )

  return (
    <div className="flex h-screen bg-bg text-text-base">
      <AppSidebar />
      <div className="flex-1 flex flex-col overflow-hidden">
        <PageToolbar
          breadcrumb={['alex / personal', 'Overview']}
          actions={
            <>
              <SearchButton onClick={toggleSearch} />
              <button
                onClick={() => setShowCreate(true)}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-coral border border-coral text-bg text-[12.5px] font-medium hover:bg-coral/90 transition-colors"
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M12 5v14M5 12h14"/></svg>
                New diagram
              </button>
            </>
          }
        />
        <div className="flex-1 overflow-y-auto p-8">

        {showCreate && (
          <div className="bg-neutral-900 border border-neutral-800 rounded-lg p-4 mb-6 max-w-lg">
            <div className="text-sm font-medium mb-3">New diagram</div>
            <input
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="Diagram name…"
              autoFocus
              onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
              className="w-full bg-neutral-800 border border-neutral-700 rounded px-3 py-1.5 text-sm outline-none mb-2"
            />
            <select
              value={newType}
              onChange={(e) => setNewType(e.target.value)}
              className="w-full bg-neutral-800 border border-neutral-700 rounded px-3 py-1.5 text-sm outline-none mb-3"
            >
              {Object.entries(DIAGRAM_TYPE_LABELS).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
            <div className="flex gap-2">
              <button
                onClick={handleCreate}
                className="text-sm bg-blue-600 hover:bg-blue-500 text-white px-3 py-1 rounded"
              >
                Create
              </button>
              <button
                onClick={() => { setShowCreate(false); setNewName('') }}
                className="text-sm text-neutral-400 border border-neutral-700 px-3 py-1 rounded"
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {/* Pinned */}
        <Section title="📌 Pinned">
          {pinned.length === 0 ? (
            <EmptyRow hint="Pin a diagram from the Diagrams page to have it show up here." />
          ) : (
            <Grid>
              {pinned.map((d) => (
                <DiagramCard
                  key={d.id}
                  diagram={d}
                  onClick={() => navigate(`/diagram/${d.id}`)}
                  onPinToggle={() =>
                    updateDiagram.mutate({ id: d.id, pinned: !d.pinned })
                  }
                  onDelete={() => {
                    if (confirm(`Delete diagram "${d.name}"?`)) deleteDiagram.mutate(d.id)
                  }}
                />
              ))}
            </Grid>
          )}
        </Section>

        {/* Recent */}
        <Section title="⏱ Recent">
          {recent.length === 0 ? (
            <EmptyRow hint="No diagrams yet. Click + Create diagram to start." />
          ) : (
            <Grid>
              {recent.map((d) => (
                <DiagramCard
                  key={d.id}
                  diagram={d}
                  onClick={() => navigate(`/diagram/${d.id}`)}
                  onPinToggle={() =>
                    updateDiagram.mutate({ id: d.id, pinned: !d.pinned })
                  }
                  onDelete={() => {
                    if (confirm(`Delete diagram "${d.name}"?`)) deleteDiagram.mutate(d.id)
                  }}
                />
              ))}
            </Grid>
          )}
        </Section>

        {/* Health */}
        <Section title="🩺 Health check">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 max-w-3xl">
            <Stat value={objects.length} label="Objects" />
            <Stat value={connections.length} label="Connections" />
            <Stat value={missingDescriptions} label="Missing descriptions" warn={missingDescriptions > 0} />
            <Stat value={orphanObjects} label="Orphan objects" warn={orphanObjects > 0} />
          </div>
        </Section>
        </div>
      </div>
      <SearchModal open={searchOpen} onClose={toggleSearch} />
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mb-8">
      <div className="text-sm font-medium text-neutral-300 mb-3">{title}</div>
      {children}
    </div>
  )
}

function Grid({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-3">
      {children}
    </div>
  )
}

function EmptyRow({ hint }: { hint: string }) {
  return (
    <div className="text-xs text-neutral-500 italic border border-dashed border-neutral-800 rounded-lg p-4">
      {hint}
    </div>
  )
}

function Stat({ value, label, warn }: { value: number; label: string; warn?: boolean }) {
  return (
    <div className="bg-neutral-900 border border-neutral-800 rounded-lg p-3">
      <div
        className="text-2xl font-semibold"
        style={{ color: warn ? '#f59e0b' : '#e5e5e5' }}
      >
        {value}
      </div>
      <div className="text-[11px] text-neutral-500">{label}</div>
    </div>
  )
}

function DiagramCard({
  diagram,
  onClick,
  onPinToggle,
  onDelete,
}: {
  diagram: Diagram
  onClick: () => void
  onPinToggle: () => void
  onDelete: () => void
}) {
  return (
    <div
      onClick={onClick}
      className="bg-neutral-900 border border-neutral-800 hover:border-neutral-700 rounded-lg p-3 cursor-pointer"
    >
      <div
        className="h-20 rounded mb-2 flex items-center justify-center text-3xl opacity-30"
        style={{ background: '#0a0a0a' }}
      >
        {DIAGRAM_TYPE_ICONS[diagram.type] || '▦'}
      </div>
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="text-sm font-medium text-neutral-100 truncate">
            {diagram.name}
          </div>
          <div className="text-[10px] text-neutral-500">
            {DIAGRAM_TYPE_LABELS[diagram.type] || diagram.type}
          </div>
        </div>
        <button
          onClick={(e) => { e.stopPropagation(); onPinToggle() }}
          title={diagram.pinned ? 'Unpin' : 'Pin to Overview'}
          className={diagram.pinned ? 'text-yellow-400' : 'text-neutral-600 hover:text-neutral-300'}
        >
          {diagram.pinned ? '📌' : '📍'}
        </button>
      </div>
      <button
        onClick={(e) => { e.stopPropagation(); onDelete() }}
        className="mt-2 text-[10px] text-neutral-600 hover:text-red-400"
      >
        Delete
      </button>
    </div>
  )
}
