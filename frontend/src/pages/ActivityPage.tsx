import { useState } from 'react'
import { AppSidebar } from '../components/nav/AppSidebar'
import { useGlobalActivity, type ActivityLogEntry } from '../hooks/use-api'

type TargetFilter = 'all' | 'object' | 'connection' | 'diagram'

const ACTION_COLORS = {
  created: '#22c55e',
  updated: '#3b82f6',
  deleted: '#ef4444',
} as const

export function ActivityPage() {
  const [filter, setFilter] = useState<TargetFilter>('all')
  const { data: entries = [], isLoading } = useGlobalActivity({
    target_type: filter === 'all' ? null : filter,
    limit: 200,
  })

  return (
    <div className="flex h-screen bg-neutral-950 text-neutral-200">
      <AppSidebar />
      <div className="flex-1 overflow-y-auto p-8">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-xl font-semibold">Activity</h1>
          <div className="flex gap-1">
            {(['all', 'object', 'connection', 'diagram'] as TargetFilter[]).map((f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={`text-xs px-3 py-1 rounded capitalize ${
                  filter === f
                    ? 'bg-neutral-700 text-neutral-100'
                    : 'text-neutral-500 hover:text-neutral-300'
                }`}
              >
                {f}
              </button>
            ))}
          </div>
        </div>

        {isLoading && <div className="text-sm text-neutral-500">Loading…</div>}
        {!isLoading && entries.length === 0 && (
          <div className="text-sm text-neutral-500 italic">No activity yet.</div>
        )}
        <div className="space-y-3 max-w-3xl">
          {entries.map((e) => (
            <Row key={e.id} entry={e} />
          ))}
        </div>
      </div>
    </div>
  )
}

function Row({ entry }: { entry: ActivityLogEntry }) {
  const when = new Date(entry.created_at).toLocaleString()
  const color = ACTION_COLORS[entry.action] ?? '#737373'
  const summary = summarize(entry)

  return (
    <div
      className="border-l-2 pl-3 py-1"
      style={{ borderColor: color }}
    >
      <div className="flex items-center gap-2 mb-0.5">
        <span
          className="text-[10px] uppercase tracking-wide font-medium"
          style={{ color }}
        >
          {entry.action}
        </span>
        <span className="text-[10px] text-neutral-500">·</span>
        <span className="text-[10px] text-neutral-500 capitalize">{entry.target_type}</span>
        <span className="text-[10px] text-neutral-500">·</span>
        <span className="text-[10px] text-neutral-500">{when}</span>
      </div>
      <div className="text-xs text-neutral-300">{summary}</div>
    </div>
  )
}

// A very small summariser — prefers the `name` field snapshot when
// available, falls back to a list of changed field names.
function summarize(entry: ActivityLogEntry): string {
  const changes = entry.changes as Record<string, unknown> | null
  if (!changes) return entry.target_id
  if (entry.action === 'created' || entry.action === 'deleted') {
    const name = (changes as Record<string, unknown>).name
    if (typeof name === 'string') return name
    return entry.target_id
  }
  // updated → list changed fields
  const fields = Object.keys(changes).filter((k) => k !== 'metadata_')
  return fields.length === 0 ? '(no visible changes)' : `changed ${fields.join(', ')}`
}
