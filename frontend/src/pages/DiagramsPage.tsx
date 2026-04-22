import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AppSidebar } from '../components/nav/AppSidebar'
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
import type { DiagramPack } from '../types/model'

const C4_LEVEL: Record<string, { label: string; order: number }> = {
  system_landscape: { label: 'Level 1', order: 1 },
  system_context: { label: 'Level 1', order: 1 },
  container: { label: 'Level 2', order: 2 },
  component: { label: 'Level 3', order: 3 },
  custom: { label: 'Custom', order: 9 },
}

const TYPE_LABELS: Record<string, string> = {
  system_landscape: 'System Landscape',
  system_context: 'System Context',
  container: 'Container',
  component: 'Component',
  custom: 'Custom',
}

const DIAGRAM_TYPE_LABELS_FOR_CREATE: Record<string, string> = {
  system_landscape: 'L1 — System Landscape',
  system_context: 'L1 — System Context',
  container: 'L2 — Container',
  component: 'L3 — Component',
  custom: 'Custom',
}

type SortKey = 'name' | 'type' | 'c4' | 'updated_at'

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

export function DiagramsPage() {
  const { data: diagrams = [], isLoading } = useDiagrams()
  const createDiagram = useCreateDiagram()
  const deleteDiagram = useDeleteDiagram()
  const updateDiagram = useUpdateDiagram()
  const navigate = useNavigate()
  const [search, setSearch] = useState('')
  const [sortKey, setSortKey] = useState<SortKey>('updated_at')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({})
  const [newPackName, setNewPackName] = useState('')
  const [showNewPackInput, setShowNewPackInput] = useState(false)
  const [renamingPack, setRenamingPack] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const [showCreate, setShowCreate] = useState(false)
  const [newName, setNewName] = useState('')
  const [newType, setNewType] = useState('system_landscape')

  const wsId = useWorkspaceStore((s) => s.currentWorkspaceId)
  const { data: workspaces = [] } = useWorkspaces()
  const currentWs = workspaces.find((w) => w.id === wsId) ?? null
  const isAdmin =
    currentWs?.role === 'owner' || currentWs?.role === 'admin'

  const { data: packs = [] } = usePacks(wsId)
  const createPack = useCreatePack(wsId)
  const renamePack = useRenamePack(wsId)
  const deletePack = useDeletePack(wsId)
  const setDiagramPack = useSetDiagramPack()

  const filtered = useMemo(() => {
    let rows = diagrams
    if (search) {
      const q = search.toLowerCase()
      rows = rows.filter((d) => d.name.toLowerCase().includes(q))
    }
    return [...rows].sort((a, b) => {
      const factor = sortDir === 'asc' ? 1 : -1
      if (sortKey === 'name') return factor * a.name.localeCompare(b.name)
      if (sortKey === 'type') return factor * a.type.localeCompare(b.type)
      if (sortKey === 'c4') {
        const oa = C4_LEVEL[a.type]?.order ?? 99
        const ob = C4_LEVEL[b.type]?.order ?? 99
        return factor * (oa - ob)
      }
      return factor * (new Date(a.updated_at).getTime() - new Date(b.updated_at).getTime())
    })
  }, [diagrams, search, sortKey, sortDir])

  const setSort = (key: SortKey) => {
    if (sortKey === key) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    else {
      setSortKey(key)
      setSortDir(key === 'updated_at' ? 'desc' : 'asc')
    }
  }

  const arrow = (key: SortKey) =>
    sortKey === key ? (sortDir === 'asc' ? ' ▲' : ' ▼') : ''

  const toggleCollapse = (groupId: string) =>
    setCollapsed((prev) => ({ ...prev, [groupId]: !prev[groupId] }))

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

  const unfiledDiagrams = filtered.filter((d) => !d.pack_id)
  const packMap: Record<string, typeof filtered> = {}
  for (const p of sortedPacks) {
    packMap[p.id] = filtered.filter((d) => d.pack_id === p.id)
  }

  const tableHeader = (
    <thead>
      <tr className="text-xs text-neutral-500 border-b border-neutral-800">
        <th className="text-left px-4 py-2 font-medium"></th>
        <SortHeader label="Diagram name" active={sortKey === 'name'} onClick={() => setSort('name')} arrow={arrow('name')} />
        <SortHeader label="Type" active={sortKey === 'type'} onClick={() => setSort('type')} arrow={arrow('type')} />
        <SortHeader label="C4 level" active={sortKey === 'c4'} onClick={() => setSort('c4')} arrow={arrow('c4')} />
        <SortHeader label="Last edit" active={sortKey === 'updated_at'} onClick={() => setSort('updated_at')} arrow={arrow('updated_at')} />
        <th className="text-left px-4 py-2 font-medium"></th>
      </tr>
    </thead>
  )

  const renderRow = (d: (typeof filtered)[0]) => (
    <tr
      key={d.id}
      className="border-b border-neutral-800 last:border-0 hover:bg-neutral-800/40 cursor-pointer"
      onClick={() => navigate(`/diagram/${d.id}`)}
    >
      <td className="px-4 py-2 w-8">
        <button
          onClick={(e) => {
            e.stopPropagation()
            updateDiagram.mutate({ id: d.id, pinned: !d.pinned })
          }}
          title={d.pinned ? 'Unpin' : 'Pin to Overview'}
          className={d.pinned ? 'text-yellow-400' : 'text-neutral-600 hover:text-neutral-300'}
        >
          {d.pinned ? '📌' : '📍'}
        </button>
      </td>
      <td className="px-4 py-2 text-neutral-100">{d.name}</td>
      <td className="px-4 py-2 text-neutral-400 text-xs">{TYPE_LABELS[d.type] || d.type}</td>
      <td className="px-4 py-2 text-neutral-400 text-xs">{C4_LEVEL[d.type]?.label ?? '—'}</td>
      <td className="px-4 py-2 text-neutral-500 text-xs">{timeAgo(d.updated_at)}</td>
      <td className="px-4 py-2 text-right" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-end gap-2">
          <PackMoveMenu
            packs={packs}
            currentPackId={d.pack_id}
            onSelect={(packId) => setDiagramPack.mutate({ diagramId: d.id, packId })}
          />
          <button
            onClick={(e) => {
              e.stopPropagation()
              if (confirm(`Delete diagram "${d.name}"?`)) deleteDiagram.mutate(d.id)
            }}
            className="text-xs text-neutral-600 hover:text-red-400"
          >
            Delete
          </button>
        </div>
      </td>
    </tr>
  )

  const renderGroup = (
    groupId: string,
    label: string,
    count: number,
    rows: typeof filtered,
    headerActions?: React.ReactNode,
  ) => (
    <section key={groupId} className="bg-neutral-900 border border-neutral-800 rounded-lg overflow-hidden mb-4">
      <div
        className="flex items-center justify-between px-4 py-2 border-b border-neutral-800 bg-neutral-900/80 cursor-pointer select-none"
        onClick={() => toggleCollapse(groupId)}
      >
        <div className="flex items-center gap-2">
          <span className="text-xs text-neutral-500">{collapsed[groupId] ? '▶' : '▼'}</span>
          <span className="text-sm font-medium text-neutral-300">{label}</span>
          <span className="text-xs text-neutral-600 bg-neutral-800 px-1.5 py-0.5 rounded">{count}</span>
        </div>
        {headerActions && (
          <div onClick={(e) => e.stopPropagation()} className="flex items-center gap-1">
            {headerActions}
          </div>
        )}
      </div>
      {!collapsed[groupId] && (
        <table className="w-full text-sm">
          {tableHeader}
          <tbody>
            {rows.map(renderRow)}
            {rows.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-4 text-center text-sm text-neutral-600 italic">
                  No diagrams in this group.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}
    </section>
  )

  return (
    <div className="flex h-screen bg-neutral-950 text-neutral-200">
      <AppSidebar />
      <div className="flex-1 overflow-y-auto p-8">
        <div className="flex items-center justify-between mb-6 gap-4">
          <h1 className="text-xl font-semibold">All diagrams</h1>
          <div className="flex gap-3 items-center">
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search diagrams…"
              className="w-72 bg-neutral-900 border border-neutral-800 rounded px-3 py-1.5 text-sm outline-none focus:border-neutral-600"
            />
            {isAdmin && (
              showNewPackInput ? (
                <div className="flex items-center gap-1">
                  <input
                    autoFocus
                    value={newPackName}
                    onChange={(e) => setNewPackName(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') handleCreatePack()
                      if (e.key === 'Escape') {
                        setShowNewPackInput(false)
                        setNewPackName('')
                      }
                    }}
                    placeholder="Pack name…"
                    className="bg-neutral-900 border border-neutral-700 rounded px-2 py-1 text-sm outline-none focus:border-neutral-500 w-40"
                  />
                  <button
                    onClick={handleCreatePack}
                    className="text-sm bg-neutral-700 hover:bg-neutral-600 px-2 py-1 rounded"
                  >
                    Save
                  </button>
                  <button
                    onClick={() => { setShowNewPackInput(false); setNewPackName('') }}
                    className="text-sm text-neutral-500 hover:text-neutral-300 px-2 py-1"
                  >
                    Cancel
                  </button>
                </div>
              ) : (
                <button
                  onClick={() => setShowNewPackInput(true)}
                  className="text-sm bg-neutral-800 hover:bg-neutral-700 border border-neutral-700 px-3 py-1.5 rounded"
                >
                  + New pack
                </button>
              )
            )}
            <button
              onClick={() => setShowCreate(true)}
              className="text-sm bg-blue-600 hover:bg-blue-500 text-white px-3 py-1.5 rounded"
            >
              + Create diagram
            </button>
          </div>
        </div>

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
              {Object.entries(DIAGRAM_TYPE_LABELS_FOR_CREATE).map(([value, label]) => (
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

        {isLoading && <div className="text-sm text-neutral-500">Loading…</div>}

        {/* Unfiled group */}
        {renderGroup('__unfiled__', 'Unfiled', unfiledDiagrams.length, unfiledDiagrams)}

        {/* Per-pack groups */}
        {sortedPacks.map((pack) => {
          const packDiagrams = packMap[pack.id] ?? []
          const isRenaming = renamingPack === pack.id

          const headerActions = isAdmin ? (
            <>
              {isRenaming ? (
                <>
                  <input
                    autoFocus
                    value={renameValue}
                    onChange={(e) => setRenameValue(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') handleRenamePack(pack.id)
                      if (e.key === 'Escape') { setRenamingPack(null); setRenameValue('') }
                    }}
                    className="bg-neutral-800 border border-neutral-700 rounded px-2 py-0.5 text-xs outline-none focus:border-neutral-500 w-32"
                  />
                  <button
                    onClick={() => handleRenamePack(pack.id)}
                    className="text-xs text-neutral-400 hover:text-neutral-200 px-1"
                  >
                    Save
                  </button>
                  <button
                    onClick={() => { setRenamingPack(null); setRenameValue('') }}
                    className="text-xs text-neutral-600 hover:text-neutral-400 px-1"
                  >
                    Cancel
                  </button>
                </>
              ) : (
                <>
                  <button
                    onClick={() => { setRenamingPack(pack.id); setRenameValue(pack.name) }}
                    className="text-xs text-neutral-600 hover:text-neutral-300 px-1"
                    title="Rename pack"
                  >
                    Rename
                  </button>
                  <button
                    onClick={() => {
                      if (confirm(`Delete pack "${pack.name}"? Diagrams will become unfiled.`))
                        deletePack.mutate(pack.id)
                    }}
                    className="text-xs text-neutral-600 hover:text-red-400 px-1"
                    title="Delete pack"
                  >
                    Delete
                  </button>
                </>
              )}
            </>
          ) : undefined

          return renderGroup(pack.id, pack.name, packDiagrams.length, packDiagrams, headerActions)
        })}

        <div className="mt-3 text-[11px] text-neutral-600">
          Total diagrams: {diagrams.length}
        </div>
      </div>
    </div>
  )
}

function SortHeader({
  label,
  active,
  onClick,
  arrow,
}: {
  label: string
  active: boolean
  onClick: () => void
  arrow: string
}) {
  return (
    <th
      onClick={onClick}
      className={`text-left px-4 py-2 font-medium cursor-pointer select-none ${
        active ? 'text-neutral-200' : 'text-neutral-500 hover:text-neutral-300'
      }`}
    >
      {label}
      <span className="text-[10px]">{arrow}</span>
    </th>
  )
}

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
        className="text-xs text-neutral-600 hover:text-neutral-300"
        title="Move to pack"
      >
        Move to…
      </button>
      {open && (
        <div
          className="absolute right-0 top-full mt-1 z-20 bg-neutral-800 border border-neutral-700 rounded shadow-lg min-w-[140px]"
          onClick={(e) => e.stopPropagation()}
        >
          <button
            className={`w-full text-left px-3 py-1.5 text-xs hover:bg-neutral-700 ${currentPackId === null ? 'text-blue-400' : 'text-neutral-300'}`}
            onClick={() => { onSelect(null); setOpen(false) }}
          >
            Unfiled
          </button>
          {packs.map((p) => (
            <button
              key={p.id}
              className={`w-full text-left px-3 py-1.5 text-xs hover:bg-neutral-700 ${currentPackId === p.id ? 'text-blue-400' : 'text-neutral-300'}`}
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
