import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AppSidebar } from '../components/nav/AppSidebar'
import { PageToolbar } from '../components/nav/PageToolbar'
import { ObjectSidebar } from '../components/sidebar/ObjectSidebar'
import { useObjectDiagrams } from '../hooks/use-diagrams'
import { useObjects, useTechnologies } from '../hooks/use-api'
import { useWorkspaceStore } from '../stores/workspace-store'
import type { ModelObject, Technology } from '../types/model'
import { STATUS_COLORS, TYPE_ICONS, TYPE_LABELS } from '../components/canvas/node-utils'
import { TechBadge } from '../components/tech'

export function ObjectsPage() {
  const { data: objects = [], isLoading } = useObjects()
  const workspaceId = useWorkspaceStore((s) => s.currentWorkspaceId)
  const { data: catalog = [] } = useTechnologies(workspaceId)
  const [search, setSearch] = useState('')
  const [editingObjectId, setEditingObjectId] = useState<string | null>(null)

  // Resolve a text haystack once per object — matches by display name and
  // aliases, not just UUIDs, so typing "postgres" finds every row tagged
  // with the PostgreSQL technology.
  const techText = useMemo(() => {
    const byId = new Map(catalog.map((t) => [t.id, t]))
    const map = new Map<string, string>()
    for (const o of objects) {
      const parts: string[] = []
      for (const id of o.technology_ids ?? []) {
        const t = byId.get(id)
        if (t) {
          parts.push(t.name.toLowerCase(), t.slug.toLowerCase())
          for (const alias of t.aliases ?? []) parts.push(alias.toLowerCase())
        }
      }
      map.set(o.id, parts.join(' '))
    }
    return map
  }, [objects, catalog])

  const filtered = useMemo(() => {
    if (!search) return objects
    const q = search.toLowerCase()
    return objects.filter(
      (o) =>
        o.name.toLowerCase().includes(q) ||
        o.description?.toLowerCase().includes(q) ||
        techText.get(o.id)?.includes(q),
    )
  }, [objects, search, techText])

  return (
    <div className="flex h-screen bg-bg text-text-base">
      <AppSidebar />
      <div className="flex-1 flex flex-col overflow-hidden">
        <PageToolbar breadcrumb={['alex / personal', 'Model Objects']} />
        <div className="flex-1 overflow-y-auto p-8">
        <div className="flex items-center justify-between mb-6 gap-4">
          <h1 className="text-xl font-semibold">Model Objects</h1>
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search objects…"
            className="w-72 bg-neutral-900 border border-neutral-800 rounded px-3 py-1.5 text-sm outline-none focus:border-neutral-600"
          />
        </div>

        {isLoading && <div className="text-sm text-neutral-500">Loading…</div>}
        {!isLoading && filtered.length === 0 && (
          <div className="text-sm text-neutral-500 italic">
            {search ? 'No matches.' : 'No objects yet. Create one from a diagram.'}
          </div>
        )}

        <div className="bg-neutral-900 border border-neutral-800 rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-neutral-500 border-b border-neutral-800">
                <th className="text-left px-4 py-2 font-medium">Name</th>
                <th className="text-left px-4 py-2 font-medium">Type</th>
                <th className="text-left px-4 py-2 font-medium">Status</th>
                <th className="text-left px-4 py-2 font-medium">Technology</th>
                <th className="text-left px-4 py-2 font-medium">Team</th>
                <th className="text-left px-4 py-2 font-medium">Diagrams</th>
                <th className="w-10 px-2 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((o) => (
                <ObjectRow
                  key={o.id}
                  obj={o}
                  catalog={catalog}
                  onEdit={setEditingObjectId}
                />
              ))}
            </tbody>
          </table>
        </div>
        </div>
      </div>
      <ObjectSidebar
        objectId={editingObjectId}
        open={!!editingObjectId}
        onClose={() => setEditingObjectId(null)}
        context="standalone"
      />
    </div>
  )
}

function ObjectRow({
  obj,
  catalog,
  onEdit,
}: {
  obj: ModelObject
  catalog: Technology[]
  onEdit: (id: string) => void
}) {
  const { data: diagrams = [] } = useObjectDiagrams(obj.id)
  const navigate = useNavigate()
  const technologies = (obj.technology_ids ?? [])
    .map((id) => catalog.find((t) => t.id === id))
    .filter((t): t is Technology => Boolean(t))

  return (
    <tr className="border-b border-neutral-800 last:border-0 hover:bg-neutral-800/40">
      <td className="px-4 py-2">
        <span className="mr-2 opacity-60">{TYPE_ICONS[obj.type]}</span>
        <span className="text-neutral-200">{obj.name}</span>
      </td>
      <td className="px-4 py-2 text-neutral-400">{TYPE_LABELS[obj.type]}</td>
      <td className="px-4 py-2">
        <span
          className="inline-flex items-center gap-1.5 text-xs"
          style={{ color: STATUS_COLORS[obj.status] }}
        >
          <span
            className="w-2 h-2 rounded-full"
            style={{ backgroundColor: STATUS_COLORS[obj.status] }}
          />
          {obj.status}
        </span>
      </td>
      <td className="px-4 py-2 text-xs">
        {technologies.length === 0 ? (
          <span className="text-neutral-600">—</span>
        ) : (
          <div className="flex flex-wrap gap-1">
            {technologies.slice(0, 4).map((t) => (
              <TechBadge key={t.id} technology={t} />
            ))}
            {technologies.length > 4 && (
              <span className="text-neutral-600">+{technologies.length - 4}</span>
            )}
          </div>
        )}
      </td>
      <td className="px-4 py-2 text-neutral-400 text-xs">{obj.owner_team || '—'}</td>
      <td className="px-4 py-2 text-xs">
        {diagrams.length === 0 ? (
          <span className="text-neutral-600">—</span>
        ) : (
          <div className="flex flex-wrap gap-1">
            {diagrams.slice(0, 2).map((d) => (
              <button
                key={d.id}
                onClick={() => navigate(`/diagram/${d.id}`)}
                className="text-blue-400 hover:text-blue-300 underline decoration-dotted"
              >
                {d.name}
              </button>
            ))}
            {diagrams.length > 2 && (
              <span className="text-neutral-600">+{diagrams.length - 2}</span>
            )}
          </div>
        )}
      </td>
      <td className="px-2 py-2 text-right">
        <button
          onClick={(e) => {
            e.stopPropagation()
            onEdit(obj.id)
          }}
          className="px-2 py-1 text-neutral-500 hover:text-neutral-200 hover:bg-neutral-800 rounded text-base leading-none"
          title="Edit object"
        >
          ⋯
        </button>
      </td>
    </tr>
  )
}
