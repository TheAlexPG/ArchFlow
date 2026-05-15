import { useMemo, useState } from 'react'
import { AppSidebar } from '../components/nav/AppSidebar'
import { PageToolbar } from '../components/nav/PageToolbar'
import { useConnections, useObjects, useTechnologies } from '../hooks/use-api'
import { useWorkspaceStore } from '../stores/workspace-store'
import { TechBadge } from '../components/tech'

export function ConnectionsPage() {
  const { data: connections = [], isLoading } = useConnections()
  const { data: objects = [] } = useObjects()
  const workspaceId = useWorkspaceStore((s) => s.currentWorkspaceId)
  const { data: catalog = [] } = useTechnologies(workspaceId)
  const [search, setSearch] = useState('')

  const objectMap = useMemo(() => new Map(objects.map((o) => [o.id, o])), [objects])
  const catalogMap = useMemo(() => new Map(catalog.map((t) => [t.id, t])), [catalog])

  const rows = useMemo(() => {
    return connections.map((c) => ({
      id: c.id,
      source: objectMap.get(c.source_id)?.name || '—',
      target: objectMap.get(c.target_id)?.name || '—',
      label: c.label,
      protocols: (c.protocol_ids ?? [])
        .map((id) => catalogMap.get(id))
        .filter((t): t is NonNullable<typeof t> => Boolean(t)),
      direction: c.direction,
    }))
  }, [connections, objectMap, catalogMap])

  const filtered = useMemo(() => {
    if (!search) return rows
    const q = search.toLowerCase()
    return rows.filter(
      (r) =>
        r.source.toLowerCase().includes(q) ||
        r.target.toLowerCase().includes(q) ||
        r.label?.toLowerCase().includes(q) ||
        r.protocols.some(
          (p) =>
            p.name.toLowerCase().includes(q) ||
            p.slug.toLowerCase().includes(q),
        ),
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
            className="w-72 bg-surface border border-border-base rounded px-3 py-1.5 text-sm text-text-base placeholder:text-text-4 outline-none focus:border-border-hi"
          />
        </div>

        {isLoading && <div className="text-sm text-neutral-500">Loading…</div>}
        {!isLoading && filtered.length === 0 && (
          <div className="text-sm text-neutral-500 italic">
            {search ? 'No matches.' : 'No connections yet.'}
          </div>
        )}

        <div className="bg-panel border border-border-base rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-text-3 border-b border-border-base">
                <th className="text-left px-4 py-2 font-medium">Source</th>
                <th className="text-left px-4 py-2 font-medium">Target</th>
                <th className="text-left px-4 py-2 font-medium">Direction</th>
                <th className="text-left px-4 py-2 font-medium">Label</th>
                <th className="text-left px-4 py-2 font-medium">Protocols</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((r) => (
                <tr key={r.id} className="border-b border-border-base last:border-0 hover:bg-surface">
                  <td className="px-4 py-2 text-text-base">{r.source}</td>
                  <td className="px-4 py-2 text-text-base">{r.target}</td>
                  <td className="px-4 py-2 text-xs text-text-2">
                    {r.direction === 'bidirectional' ? '⇄ bidirectional' : '→ outgoing'}
                  </td>
                  <td className="px-4 py-2 text-text-2 text-xs">{r.label || '—'}</td>
                  <td className="px-4 py-2 text-xs">
                    {r.protocols.length === 0 ? (
                      <span className="text-text-3">—</span>
                    ) : (
                      <div className="flex flex-wrap gap-1">
                        {r.protocols.slice(0, 4).map((p) => (
                          <TechBadge key={p.id} technology={p} />
                        ))}
                        {r.protocols.length > 4 && (
                          <span className="text-text-3">
                            +{r.protocols.length - 4}
                          </span>
                        )}
                      </div>
                    )}
                  </td>
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
