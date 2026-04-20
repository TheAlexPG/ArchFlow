import { useState } from 'react'
import { Link } from 'react-router-dom'
import { AppSidebar } from '../components/nav/AppSidebar'
import {
  useCompareVersions,
  useCreateManualSnapshot,
  useRevertVersion,
  useVersions,
} from '../hooks/use-api'
import type { Version, VersionSource } from '../types/model'

const SOURCE_STYLES: Record<VersionSource, { color: string; bg: string; border: string }> = {
  apply:     { color: '#22c55e', bg: '#22c55e22', border: '#22c55e55' },
  manual:    { color: '#3b82f6', bg: '#3b82f622', border: '#3b82f655' },
  scheduled: { color: '#a855f7', bg: '#a855f722', border: '#a855f755' },
  revert:    { color: '#f59e0b', bg: '#f59e0b22', border: '#f59e0b55' },
}

function SourcePill({ source }: { source: VersionSource }) {
  const s = SOURCE_STYLES[source]
  return (
    <span
      style={{
        fontSize: 10,
        padding: '2px 8px',
        borderRadius: 9999,
        color: s.color,
        background: s.bg,
        border: `1px solid ${s.border}`,
        fontWeight: 500,
        textTransform: 'capitalize',
      }}
    >
      {source}
    </span>
  )
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

type CompareSummary = {
  objects_added: number
  objects_removed: number
  objects_modified: number
  connections_added: number
  connections_removed: number
  connections_modified: number
  diagrams_added: number
  diagrams_removed: number
  diagrams_modified: number
}

function SummaryCard({ summary }: { summary: CompareSummary }) {
  const rows: { label: string; added: number; removed: number; modified: number }[] = [
    { label: 'Objects',     added: summary.objects_added,     removed: summary.objects_removed,     modified: summary.objects_modified },
    { label: 'Connections', added: summary.connections_added, removed: summary.connections_removed, modified: summary.connections_modified },
    { label: 'Diagrams',    added: summary.diagrams_added,    removed: summary.diagrams_removed,    modified: summary.diagrams_modified },
  ]
  return (
    <div className="mt-4 bg-neutral-900 border border-neutral-800 rounded-lg overflow-hidden">
      <div className="px-4 py-2 border-b border-neutral-800 text-xs font-medium text-neutral-400 uppercase tracking-wider">
        Diff summary
      </div>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-neutral-800">
            <th className="text-left px-4 py-2 text-xs text-neutral-500 font-normal">Entity</th>
            <th className="text-right px-4 py-2 text-xs text-green-500 font-normal">Added</th>
            <th className="text-right px-4 py-2 text-xs text-red-500 font-normal">Removed</th>
            <th className="text-right px-4 py-2 text-xs text-amber-500 font-normal">Modified</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.label} className="border-b border-neutral-800 last:border-0">
              <td className="px-4 py-2 text-neutral-300 text-xs">{r.label}</td>
              <td className="px-4 py-2 text-right text-xs text-green-400">{r.added > 0 ? `+${r.added}` : '—'}</td>
              <td className="px-4 py-2 text-right text-xs text-red-400">{r.removed > 0 ? `-${r.removed}` : '—'}</td>
              <td className="px-4 py-2 text-right text-xs text-amber-400">{r.modified > 0 ? r.modified : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function VersionSelect({
  versions,
  value,
  onChange,
  placeholder,
}: {
  versions: Version[]
  value: string
  onChange: (v: string) => void
  placeholder: string
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="bg-neutral-800 border border-neutral-700 rounded px-2 py-1.5 text-sm text-neutral-200 outline-none focus:border-neutral-500 min-w-0 flex-1"
    >
      <option value="">{placeholder}</option>
      {versions.map((v) => (
        <option key={v.id} value={v.id}>
          {v.label} ({v.source}) — {formatDate(v.created_at)}
        </option>
      ))}
    </select>
  )
}

export function VersionsPage() {
  const { data: versions = [], isLoading } = useVersions()
  const createSnapshot = useCreateManualSnapshot()
  const compare = useCompareVersions()
  const revert = useRevertVersion()

  const [compareA, setCompareA] = useState('')
  const [compareB, setCompareB] = useState('')

  const handleSnapshot = () => {
    createSnapshot.mutate()
  }

  const handleCompare = () => {
    if (!compareA || !compareB) return
    compare.mutate({ a: compareA, b: compareB })
  }

  return (
    <div className="flex h-screen bg-neutral-950 text-neutral-200">
      <AppSidebar />
      <div className="flex-1 overflow-y-auto p-8">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-xl font-semibold">Versions</h1>
          <button
            onClick={handleSnapshot}
            disabled={createSnapshot.isPending}
            className="text-sm bg-blue-600 hover:bg-blue-500 text-white px-3 py-1.5 rounded disabled:opacity-40"
          >
            {createSnapshot.isPending ? 'Saving…' : 'Create manual snapshot'}
          </button>
        </div>

        {/* Versions table */}
        <section className="mb-8 bg-neutral-900 border border-neutral-800 rounded-lg overflow-hidden">
          {isLoading ? (
            <div className="p-6 text-sm text-neutral-500">Loading…</div>
          ) : versions.length === 0 ? (
            <div className="p-6 text-sm text-neutral-500 italic">No versions yet.</div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-neutral-800">
                  <th className="text-left px-4 py-2 text-xs text-neutral-500 font-normal">Label</th>
                  <th className="text-left px-4 py-2 text-xs text-neutral-500 font-normal">Source</th>
                  <th className="text-left px-4 py-2 text-xs text-neutral-500 font-normal">Created</th>
                  <th className="text-left px-4 py-2 text-xs text-neutral-500 font-normal">Draft</th>
                  <th className="text-right px-4 py-2 text-xs text-neutral-500 font-normal" />
                </tr>
              </thead>
              <tbody>
                {versions.map((v, i) => {
                  const isHead = i === 0
                  return (
                    <tr key={v.id} className="border-b border-neutral-800 last:border-0 hover:bg-neutral-800/40">
                      <td className="px-4 py-2.5 text-neutral-200 font-medium">{v.label}</td>
                      <td className="px-4 py-2.5">
                        <SourcePill source={v.source} />
                      </td>
                      <td className="px-4 py-2.5 text-neutral-400 text-xs">{formatDate(v.created_at)}</td>
                      <td className="px-4 py-2.5 text-xs">
                        {v.draft_id ? (
                          <Link
                            to={`/drafts/${v.draft_id}`}
                            className="text-blue-400 hover:text-blue-300 underline underline-offset-2"
                          >
                            {v.draft_id.slice(0, 8)}…
                          </Link>
                        ) : (
                          <span className="text-neutral-600">—</span>
                        )}
                      </td>
                      <td className="px-4 py-2.5 text-right whitespace-nowrap">
                        {isHead ? (
                          <span className="text-[10px] text-neutral-600 uppercase tracking-wider">
                            current
                          </span>
                        ) : (
                          <button
                            onClick={() => {
                              if (
                                confirm(
                                  `Revert workspace to ${v.label}?\n\nThis replaces the live state with this snapshot. All prior versions stay in history, so you can revert forward again if needed.`,
                                )
                              ) {
                                revert.mutate(v.id)
                              }
                            }}
                            disabled={revert.isPending}
                            className="text-xs text-amber-400 hover:text-amber-300 disabled:opacity-40"
                            title="Restore this snapshot onto main"
                          >
                            Revert
                          </button>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </section>

        {/* Compare section */}
        <section className="max-w-2xl">
          <h2 className="text-sm font-semibold mb-3">Compare versions</h2>
          <div className="bg-neutral-900 border border-neutral-800 rounded-lg p-4">
            <div className="flex gap-2 items-center flex-wrap">
              <VersionSelect
                versions={versions}
                value={compareA}
                onChange={setCompareA}
                placeholder="Version A…"
              />
              <span className="text-neutral-600 text-sm flex-shrink-0">vs</span>
              <VersionSelect
                versions={versions}
                value={compareB}
                onChange={setCompareB}
                placeholder="Version B…"
              />
              <button
                onClick={handleCompare}
                disabled={!compareA || !compareB || compare.isPending}
                className="text-sm bg-neutral-700 hover:bg-neutral-600 text-neutral-100 px-3 py-1.5 rounded disabled:opacity-40 flex-shrink-0"
              >
                {compare.isPending ? 'Comparing…' : 'Compare'}
              </button>
            </div>

            {compare.isError && (
              <div className="mt-3 text-xs text-red-400">
                {(() => {
                  const e = compare.error as { response?: { data?: { detail?: string } }; message?: string }
                  return e.response?.data?.detail ?? e.message ?? 'Compare failed'
                })()}
              </div>
            )}

            {compare.data && <SummaryCard summary={compare.data.summary} />}
          </div>
        </section>
      </div>
    </div>
  )
}
