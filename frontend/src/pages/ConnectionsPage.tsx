import { useMemo, useState } from 'react'
import { AppSidebar } from '../components/nav/AppSidebar'
import { PageToolbar } from '../components/nav/PageToolbar'
import { useConnections, useObjects } from '../hooks/use-api'

export function ConnectionsPage() {
  const { data: connections = [], isLoading } = useConnections()
  const { data: objects = [] } = useObjects()
  const [search, setSearch] = useState('')

  const objectMap = useMemo(() => new Map(objects.map((o) => [o.id, o])), [objects])

  const rows = useMemo(() => {
    return connections.map((c) => ({
      id: c.id,
      source: objectMap.get(c.source_id)?.name || '—',
      target: objectMap.get(c.target_id)?.name || '—',
      label: c.label,
      protocol: c.protocol,
      direction: c.direction,
    }))
  }, [connections, objectMap])

  const filtered = useMemo(() => {
    if (!search) return rows
    const q = search.toLowerCase()
    return rows.filter(
      (r) =>
        r.source.toLowerCase().includes(q) ||
        r.target.toLowerCase().includes(q) ||
        r.label?.toLowerCase().includes(q) ||
        r.protocol?.toLowerCase().includes(q),
    )
  }, [rows, search])

  return (
    <div className="flex h-screen bg-bg text-text-base">
      <AppSidebar />
      <div className="flex-1 flex flex-col overflow-hidden">
        <PageToolbar breadcrumb={['alex / personal', 'Connections']} />
        <div className="flex-1 overflow-y-auto p-8">
        <div className="flex items-center justify-between mb-6 gap-4">
          <h1 className="text-xl font-semibold">Connections</h1>
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search connections…"
            className="w-72 bg-neutral-900 border border-neutral-800 rounded px-3 py-1.5 text-sm outline-none focus:border-neutral-600"
          />
        </div>

        {isLoading && <div className="text-sm text-neutral-500">Loading…</div>}
        {!isLoading && filtered.length === 0 && (
          <div className="text-sm text-neutral-500 italic">
            {search ? 'No matches.' : 'No connections yet.'}
          </div>
        )}

        <div className="bg-neutral-900 border border-neutral-800 rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-neutral-500 border-b border-neutral-800">
                <th className="text-left px-4 py-2 font-medium">Source</th>
                <th className="text-left px-4 py-2 font-medium">Target</th>
                <th className="text-left px-4 py-2 font-medium">Direction</th>
                <th className="text-left px-4 py-2 font-medium">Label</th>
                <th className="text-left px-4 py-2 font-medium">Protocol</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((r) => (
                <tr key={r.id} className="border-b border-neutral-800 last:border-0 hover:bg-neutral-800/40">
                  <td className="px-4 py-2 text-neutral-200">{r.source}</td>
                  <td className="px-4 py-2 text-neutral-200">{r.target}</td>
                  <td className="px-4 py-2 text-xs text-neutral-400">
                    {r.direction === 'bidirectional' ? '⇄ bidirectional' : '→ outgoing'}
                  </td>
                  <td className="px-4 py-2 text-neutral-400 text-xs">{r.label || '—'}</td>
                  <td className="px-4 py-2 text-neutral-400 text-xs">{r.protocol || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        </div>
      </div>
    </div>
  )
}
