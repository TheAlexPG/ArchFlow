import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AppSidebar } from '../components/nav/AppSidebar'
import {
  useDiagrams,
  useDeleteDiagram,
  useUpdateDiagram,
} from '../hooks/use-diagrams'

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
  const deleteDiagram = useDeleteDiagram()
  const updateDiagram = useUpdateDiagram()
  const navigate = useNavigate()
  const [search, setSearch] = useState('')
  const [sortKey, setSortKey] = useState<SortKey>('updated_at')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')

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
            <button
              onClick={() => navigate('/')}
              className="text-sm bg-blue-600 hover:bg-blue-500 text-white px-3 py-1.5 rounded"
              title="Create diagram via Overview"
            >
              + Create diagram
            </button>
          </div>
        </div>

        {isLoading && <div className="text-sm text-neutral-500">Loading…</div>}

        <div className="bg-neutral-900 border border-neutral-800 rounded-lg overflow-hidden">
          <table className="w-full text-sm">
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
            <tbody>
              {filtered.map((d) => (
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
                  <td className="px-4 py-2 text-right">
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        if (confirm(`Delete diagram "${d.name}"?`)) deleteDiagram.mutate(d.id)
                      }}
                      className="text-xs text-neutral-600 hover:text-red-400"
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
              {filtered.length === 0 && !isLoading && (
                <tr>
                  <td colSpan={6} className="px-4 py-6 text-center text-sm text-neutral-500 italic">
                    {search ? 'No matches.' : 'No diagrams yet.'}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

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
