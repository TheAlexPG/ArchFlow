import { useMemo, useState } from 'react'
import { AppSidebar } from '../components/nav/AppSidebar'
import { PageToolbar } from '../components/nav/PageToolbar'
import {
  useDeleteCustomTechnology,
  useTechnologies,
} from '../hooks/use-api'
import { useWorkspaceStore } from '../stores/workspace-store'
import type { TechCategory, Technology } from '../types/model'
import { Button, Pill, type PillVariant } from '../components/ui'
import { CustomTechModal, TechIcon } from '../components/tech'
import { cn } from '../utils/cn'

const CATEGORY_LABEL: Record<TechCategory, string> = {
  language: 'Language',
  framework: 'Framework',
  database: 'Database',
  cloud: 'Cloud',
  saas: 'SaaS',
  tool: 'Tool',
  protocol: 'Protocol',
  other: 'Other',
}

// Map each category onto one of the existing Pill glow variants so the
// management table reads as a quick visual legend without inventing new
// color tokens.
const CATEGORY_PILL: Record<TechCategory, PillVariant> = {
  language: 'processing',
  framework: 'ai',
  database: 'input',
  cloud: 'review',
  saas: 'done',
  tool: 'neutral',
  protocol: 'draft',
  other: 'neutral',
}

const SCOPE_TABS = [
  { value: 'all', label: 'All' },
  { value: 'custom', label: 'Custom' },
  { value: 'builtin', label: 'Built-in' },
] as const

type Scope = (typeof SCOPE_TABS)[number]['value']

export function TechnologiesPage() {
  const workspaceId = useWorkspaceStore((s) => s.currentWorkspaceId)
  const { data: all = [], isLoading } = useTechnologies(workspaceId)
  const [scope, setScope] = useState<Scope>('all')
  const [category, setCategory] = useState<TechCategory | 'all'>('all')
  const [search, setSearch] = useState('')
  const [createOpen, setCreateOpen] = useState(false)
  const [editing, setEditing] = useState<Technology | null>(null)

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return all.filter((t) => {
      if (scope === 'builtin' && t.workspace_id !== null) return false
      if (scope === 'custom' && t.workspace_id === null) return false
      if (category !== 'all' && t.category !== category) return false
      if (!q) return true
      if (t.name.toLowerCase().includes(q)) return true
      if (t.slug.toLowerCase().includes(q)) return true
      return t.aliases?.some((a) => a.toLowerCase().includes(q)) ?? false
    })
  }, [all, scope, category, search])

  const countsByCategory = useMemo(() => {
    const m = new Map<TechCategory, number>()
    for (const t of all) m.set(t.category, (m.get(t.category) ?? 0) + 1)
    return m
  }, [all])

  const categoryOptions: Array<TechCategory | 'all'> = [
    'all',
    ...(Object.keys(CATEGORY_LABEL) as TechCategory[]),
  ]

  return (
    <div className="flex h-screen bg-bg text-text-base">
      <AppSidebar />
      <div className="flex-1 flex flex-col overflow-hidden">
        <PageToolbar breadcrumb={['alex / personal', 'Technologies']} />

        <div className="flex-1 overflow-y-auto p-8">
          {/* Header */}
          <div className="flex items-start justify-between mb-6 gap-4">
            <div>
              <h1 className="text-xl font-semibold">Technologies</h1>
              <p className="text-[12.5px] text-text-3 mt-1">
                Browse the built-in catalog and manage custom technologies
                available across this workspace.
              </p>
            </div>
            <Button variant="primary" onClick={() => setCreateOpen(true)}>
              + New custom technology
            </Button>
          </div>

          {/* Scope tabs + category filter + search */}
          <div className="flex items-center gap-3 mb-5 flex-wrap">
            <div className="inline-flex p-[2px] bg-surface border border-border-base rounded-md">
              {SCOPE_TABS.map((t) => (
                <button
                  key={t.value}
                  onClick={() => setScope(t.value)}
                  className={cn(
                    'px-3 py-1 font-mono text-[11px] rounded',
                    scope === t.value
                      ? 'bg-coral text-bg'
                      : 'text-text-3 hover:text-text-base',
                  )}
                >
                  {t.label}
                </button>
              ))}
            </div>

            <select
              value={category}
              onChange={(e) =>
                setCategory(e.target.value as TechCategory | 'all')
              }
              className="bg-surface border border-border-base rounded-md px-2 py-1 text-[12px] text-text-2 outline-none focus:border-border-hi"
            >
              {categoryOptions.map((c) => (
                <option key={c} value={c}>
                  {c === 'all'
                    ? 'All categories'
                    : `${CATEGORY_LABEL[c]} · ${countsByCategory.get(c) ?? 0}`}
                </option>
              ))}
            </select>

            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search name, slug, alias…"
              className="flex-1 min-w-[200px] max-w-[360px] bg-surface border border-border-base rounded-md px-3 py-1.5 font-mono text-[11.5px] text-text-base placeholder:text-text-4 outline-none focus:border-border-hi"
            />
          </div>

          {/* Table */}
          {isLoading ? (
            <div className="text-[12.5px] text-text-3">Loading catalog…</div>
          ) : filtered.length === 0 ? (
            <div className="text-[12.5px] text-text-3 italic">
              {search || category !== 'all' || scope !== 'all'
                ? 'No technologies match the current filters.'
                : 'Nothing here yet — use "New custom technology" to add one.'}
            </div>
          ) : (
            <div className="bg-panel border border-border-base rounded-lg overflow-hidden">
              <table className="w-full text-[12.5px]">
                <thead>
                  <tr className="text-[10.5px] text-text-3 border-b border-border-base font-mono uppercase tracking-[0.05em]">
                    <th className="text-left px-4 py-2 font-medium">Name</th>
                    <th className="text-left px-4 py-2 font-medium">Slug</th>
                    <th className="text-left px-4 py-2 font-medium">Category</th>
                    <th className="text-left px-4 py-2 font-medium">Scope</th>
                    <th className="text-left px-4 py-2 font-medium">Iconify</th>
                    <th className="w-10 px-2 py-2"></th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((t) => (
                    <TechnologyRow
                      key={t.id}
                      technology={t}
                      onEdit={() => setEditing(t)}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      <CustomTechModal
        open={createOpen || editing !== null}
        existing={editing}
        onClose={() => {
          setCreateOpen(false)
          setEditing(null)
        }}
      />
    </div>
  )

  function TechnologyRow({
    technology,
    onEdit,
  }: {
    technology: Technology
    onEdit: () => void
  }) {
    const isBuiltin = technology.workspace_id === null
    const deleteMutation = useDeleteCustomTechnology(workspaceId)
    const [deleteError, setDeleteError] = useState<string | null>(null)

    const handleDelete = () => {
      if (!confirm(`Delete custom technology "${technology.name}"?`)) return
      setDeleteError(null)
      deleteMutation.mutate(technology.id, {
        onError: (e: unknown) => setDeleteError(toMessage(e)),
      })
    }

    return (
      <tr className="border-b border-border-base last:border-0 hover:bg-surface/60">
        <td className="px-4 py-2.5">
          <div className="flex items-center gap-2 min-w-0">
            <TechIcon technology={technology} size={18} />
            <span className="truncate text-text-base">{technology.name}</span>
          </div>
          {deleteError && (
            <div className="mt-1 text-[10.5px] text-accent-pink font-mono">
              {deleteError}
            </div>
          )}
        </td>
        <td className="px-4 py-2.5 font-mono text-[11px] text-text-3">
          {technology.slug}
        </td>
        <td className="px-4 py-2.5">
          <Pill variant={CATEGORY_PILL[technology.category]}>
            {CATEGORY_LABEL[technology.category]}
          </Pill>
        </td>
        <td className="px-4 py-2.5 font-mono text-[10.5px]">
          {isBuiltin ? (
            <span className="text-text-3">built-in</span>
          ) : (
            <span className="text-coral">custom</span>
          )}
        </td>
        <td className="px-4 py-2.5 font-mono text-[10.5px] text-text-3 truncate max-w-[220px]">
          {technology.iconify_name}
        </td>
        <td className="px-2 py-2.5 text-right whitespace-nowrap">
          {isBuiltin ? (
            <span className="text-text-4 text-[11px] font-mono">read-only</span>
          ) : (
            <>
              <button
                onClick={onEdit}
                className="px-2 py-1 text-text-3 hover:text-text-base hover:bg-surface-hi rounded text-[12px] transition-colors"
                title="Edit"
              >
                Edit
              </button>
              <button
                onClick={handleDelete}
                disabled={deleteMutation.isPending}
                className="px-2 py-1 text-text-3 hover:text-accent-pink hover:bg-surface-hi rounded text-[12px] transition-colors disabled:opacity-40"
                title="Delete"
              >
                {deleteMutation.isPending ? 'Deleting…' : 'Delete'}
              </button>
            </>
          )}
        </td>
      </tr>
    )
  }
}

function toMessage(e: unknown): string {
  const err = e as {
    response?: {
      status?: number
      data?: {
        detail?:
          | string
          | { object_refs?: number; connection_refs?: number; detail?: string }
      }
    }
    message?: string
  }
  const status = err.response?.status
  const detail = err.response?.data?.detail
  if (status === 409 && detail && typeof detail === 'object') {
    const obj = detail.object_refs ?? 0
    const conn = detail.connection_refs ?? 0
    return `In use by ${obj} object${obj === 1 ? '' : 's'} and ${conn} connection${
      conn === 1 ? '' : 's'
    } — remove references first`
  }
  if (typeof detail === 'string') return detail
  return err.message ?? 'Delete failed'
}
