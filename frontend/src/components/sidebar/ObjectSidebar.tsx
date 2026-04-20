import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  useConnections,
  useDeleteObject,
  useObject,
  useObjectChildren,
  useObjectHistory,
  useObjects,
  useUpdateObject,
  type ActivityLogEntry,
} from '../../hooks/use-api'
import { useDiagrams, useObjectDiagrams } from '../../hooks/use-diagrams'
import { useCanvasStore } from '../../stores/canvas-store'
import type { ModelObject, ObjectScope, ObjectStatus } from '../../types/model'
import { STATUS_COLORS, TYPE_LABELS } from '../canvas/node-utils'
import { RichTextEditor } from '../common/RichTextEditor'
import {
  CreateChildDiagramModal,
  DRILLABLE_TYPES,
} from '../drafts/CreateChildDiagramModal'

export function ObjectSidebar() {
  const { selectedNodeId, sidebarOpen, sidebarTab, setSidebarTab, toggleSidebar } = useCanvasStore()
  const { data: obj } = useObject(selectedNodeId)
  const updateObject = useUpdateObject()
  const deleteObject = useDeleteObject()

  const [editName, setEditName] = useState('')
  const [editDescription, setEditDescription] = useState('')
  const descTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (obj) {
      setEditName(obj.name)
      setEditDescription(obj.description || '')
    }
  }, [obj])

  if (!sidebarOpen || !obj) return null

  const handleSave = () => {
    updateObject.mutate({
      id: obj.id,
      name: editName,
      description: editDescription || null,
    })
  }

  const handleDelete = () => {
    if (confirm(`Delete "${obj.name}"?`)) {
      deleteObject.mutate(obj.id)
      toggleSidebar(false)
    }
  }

  const handleFieldChange = (field: string, value: unknown) => {
    updateObject.mutate({ id: obj.id, [field]: value })
  }

  return (
    <div className="w-80 bg-neutral-900 border-l border-neutral-800 flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-neutral-800">
        <input
          value={editName}
          onChange={(e) => setEditName(e.target.value)}
          onBlur={handleSave}
          onKeyDown={(e) => e.key === 'Enter' && handleSave()}
          className="bg-transparent text-neutral-100 font-semibold text-sm outline-none flex-1 mr-2"
        />
        <button
          onClick={() => toggleSidebar(false)}
          className="text-neutral-500 hover:text-neutral-300 text-lg"
        >
          ×
        </button>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-neutral-800">
        {(['details', 'connections', 'history'] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setSidebarTab(tab)}
            className={`flex-1 px-3 py-2 text-xs font-medium capitalize transition-colors ${
              sidebarTab === tab
                ? 'text-blue-400 border-b-2 border-blue-400'
                : 'text-neutral-500 hover:text-neutral-300'
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {sidebarTab === 'details' && (
          <>
            {/* Type */}
            <Field label="Type">
              <select
                value={obj.type}
                onChange={(e) => handleFieldChange('type', e.target.value)}
                className="bg-neutral-800 text-neutral-200 text-sm rounded px-2 py-1 w-full border border-neutral-700"
              >
                {Object.entries(TYPE_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </select>
            </Field>

            {/* Scope */}
            <Field label="Scope">
              <select
                value={obj.scope}
                onChange={(e) => handleFieldChange('scope', e.target.value as ObjectScope)}
                className="bg-neutral-800 text-neutral-200 text-sm rounded px-2 py-1 w-full border border-neutral-700"
              >
                <option value="internal">Internal</option>
                <option value="external">External</option>
              </select>
            </Field>

            {/* Status */}
            <Field label="Status">
              <div className="flex gap-1.5">
                {(['live', 'future', 'deprecated', 'removed'] as ObjectStatus[]).map((status) => (
                  <button
                    key={status}
                    onClick={() => handleFieldChange('status', status)}
                    className={`flex items-center gap-1 px-2 py-1 rounded text-xs capitalize transition-colors ${
                      obj.status === status
                        ? 'bg-neutral-700 text-neutral-100'
                        : 'text-neutral-500 hover:text-neutral-300'
                    }`}
                  >
                    <span
                      className="w-2 h-2 rounded-full"
                      style={{ backgroundColor: STATUS_COLORS[status] }}
                    />
                    {status}
                  </button>
                ))}
              </div>
            </Field>

            {/* C4 Level */}
            <Field label="C4 Level">
              <span className="text-sm text-neutral-300">{obj.c4_level}</span>
            </Field>

            {/* Cross-references */}
            <CrossReferences objectId={obj.id} />

            {/* Description */}
            <Field label="Description">
              <RichTextEditor
                content={editDescription}
                onChange={(html) => {
                  setEditDescription(html)
                  descTimerRef.current && clearTimeout(descTimerRef.current)
                  descTimerRef.current = setTimeout(() => {
                    updateObject.mutate({ id: obj.id, description: html || null })
                  }, 500)
                }}
                placeholder="Add description..."
              />
            </Field>

            {/* Technology */}
            <Field label="Technology">
              <TagEditor
                tags={obj.technology || []}
                onChange={(tags) => handleFieldChange('technology', tags)}
                placeholder="Add technology..."
              />
            </Field>

            {/* Tags */}
            <Field label="Tags">
              <TagEditor
                tags={obj.tags || []}
                onChange={(tags) => handleFieldChange('tags', tags)}
                placeholder="Add tag..."
              />
            </Field>

            {/* Owner Team */}
            <Field label="Owner Team">
              <input
                value={obj.owner_team || ''}
                onChange={(e) => handleFieldChange('owner_team', e.target.value || null)}
                className="bg-neutral-800 text-neutral-200 text-sm rounded px-2 py-1 w-full border border-neutral-700"
                placeholder="Team name..."
              />
            </Field>

            {/* Drill into — only for drillable types */}
            {DRILLABLE_TYPES.has(obj.type) && (
              <DrillIntoSection obj={obj} />
            )}

            {/* Group members — only for group type */}
            {obj.type === 'group' && (
              <GroupMembersSection groupId={obj.id} />
            )}

            {/* Delete */}
            <button
              onClick={handleDelete}
              className="w-full mt-4 px-3 py-2 rounded text-sm text-red-400 border border-red-900/50 hover:bg-red-900/20 transition-colors"
            >
              Delete object
            </button>
          </>
        )}

        {sidebarTab === 'connections' && (
          <ConnectionsTab objectId={obj.id} />
        )}

        {sidebarTab === 'history' && <HistoryTab objectId={obj.id} />}
      </div>
    </div>
  )
}

function DrillIntoSection({ obj }: { obj: ModelObject }) {
  const navigate = useNavigate()
  const { data: childDiagrams = [] } = useDiagrams(obj.id)
  const [createModalOpen, setCreateModalOpen] = useState(false)

  const levelText = obj.type === 'system' ? 'Container diagram (L2)' : 'Component diagram (L3)'

  return (
    <div>
      <div className="text-xs text-neutral-500 mb-1">Drill into</div>
      <div
        style={{
          background: '#0f0f0f',
          border: '1px solid #262626',
          borderRadius: 6,
          padding: '8px 10px',
          display: 'flex',
          flexDirection: 'column',
          gap: 6,
        }}
      >
        <div
          style={{
            fontSize: 10,
            color: '#525252',
            textTransform: 'uppercase',
            letterSpacing: '0.05em',
          }}
        >
          {levelText}
        </div>
        {childDiagrams.length === 0 ? (
          <button
            onClick={() => setCreateModalOpen(true)}
            style={{
              background: '#1e3a5f',
              border: '1px solid #3b82f655',
              borderRadius: 5,
              color: '#93c5fd',
              cursor: 'pointer',
              fontSize: 12,
              padding: '6px 10px',
              textAlign: 'left',
            }}
          >
            + Create {obj.type === 'system' ? 'container' : 'component'} diagram
          </button>
        ) : (
          <>
            {childDiagrams.map((d) => (
              <button
                key={d.id}
                onClick={() => navigate(`/diagram/${d.id}`)}
                style={{
                  background: 'transparent',
                  border: '1px solid #262626',
                  borderRadius: 5,
                  color: '#60a5fa',
                  cursor: 'pointer',
                  fontSize: 12,
                  padding: '5px 8px',
                  textAlign: 'left',
                  textDecoration: 'none',
                }}
                onMouseEnter={(e) => (e.currentTarget.style.background = '#1e3a5f')}
                onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
              >
                {d.name}
              </button>
            ))}
            <button
              onClick={() => setCreateModalOpen(true)}
              style={{
                background: 'transparent',
                border: 'none',
                color: '#525252',
                cursor: 'pointer',
                fontSize: 11,
                padding: '2px 0',
                textAlign: 'left',
              }}
              onMouseEnter={(e) => (e.currentTarget.style.color = '#a3a3a3')}
              onMouseLeave={(e) => (e.currentTarget.style.color = '#525252')}
            >
              + New child diagram
            </button>
          </>
        )}
      </div>
      <CreateChildDiagramModal
        object={obj}
        open={createModalOpen}
        onClose={() => setCreateModalOpen(false)}
      />
    </div>
  )
}

function CrossReferences({ objectId }: { objectId: string }) {
  const { data: objects = [] } = useObjects()
  const { data: connections = [] } = useConnections()
  const { data: objectDiagrams = [] } = useObjectDiagrams(objectId)

  const obj = objects.find((o) => o.id === objectId)
  const parent = obj?.parent_id ? objects.find((o) => o.id === obj.parent_id) : null
  const children = objects.filter((o) => o.parent_id === objectId)
  const connCount = connections.filter(
    (c) => c.source_id === objectId || c.target_id === objectId,
  ).length

  const { selectNode } = useCanvasStore()
  const navigate = useNavigate()

  return (
    <div className="space-y-1.5">
      {parent && (
        <div className="flex items-center justify-between text-xs">
          <span className="text-neutral-500">Belongs to</span>
          <button
            onClick={() => selectNode(parent.id)}
            className="text-blue-400 hover:text-blue-300"
          >
            {parent.name}
          </button>
        </div>
      )}
      <div className="flex items-center justify-between text-xs">
        <span className="text-neutral-500">Contains</span>
        <span className="text-neutral-300">{children.length} objects</span>
      </div>
      <div className="flex items-center justify-between text-xs">
        <span className="text-neutral-500">Connections</span>
        <span className="text-neutral-300">{connCount}</span>
      </div>
      <div className="flex items-center justify-between text-xs">
        <span className="text-neutral-500">Diagrams</span>
        {objectDiagrams.length > 0 ? (
          <div className="flex flex-col gap-0.5 items-end">
            {objectDiagrams.slice(0, 3).map((d) => (
              <button
                key={d.id}
                onClick={() => navigate(`/diagram/${d.id}`)}
                className="text-blue-400 hover:text-blue-300 truncate max-w-[160px]"
              >
                {d.name}
              </button>
            ))}
            {objectDiagrams.length > 3 && (
              <span className="text-neutral-600">+{objectDiagrams.length - 3} more</span>
            )}
          </div>
        ) : (
          <span className="text-neutral-600">None</span>
        )}
      </div>
    </div>
  )
}

function GroupMembersSection({ groupId }: { groupId: string }) {
  const { data: children = [], isLoading } = useObjectChildren(groupId)
  const { selectNode } = useCanvasStore()

  return (
    <div>
      <div className="text-xs text-neutral-500 mb-1">Members</div>
      <div
        style={{
          background: '#0f0f0f',
          border: '1px solid #262626',
          borderRadius: 6,
          overflow: 'hidden',
        }}
      >
        {isLoading ? (
          <div style={{ padding: '8px 10px', fontSize: 12, color: '#525252' }}>Loading…</div>
        ) : children.length === 0 ? (
          <div style={{ padding: '8px 10px', fontSize: 12, color: '#525252', fontStyle: 'italic' }}>
            No objects in this group yet.
          </div>
        ) : (
          children.map((child) => (
            <button
              key={child.id}
              onClick={() => selectNode(child.id)}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                width: '100%',
                padding: '6px 10px',
                background: 'transparent',
                border: 'none',
                borderBottom: '1px solid #1a1a1a',
                color: '#d4d4d4',
                cursor: 'pointer',
                fontSize: 12,
                textAlign: 'left',
              }}
              onMouseEnter={(e) => (e.currentTarget.style.background = '#1c1c1c')}
              onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
            >
              <span style={{ opacity: 0.5, fontSize: 13 }}>{TYPE_ICONS[child.type]}</span>
              <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {child.name}
              </span>
              <span style={{ fontSize: 10, color: '#525252' }}>{TYPE_LABELS[child.type]}</span>
            </button>
          ))
        )}
      </div>
    </div>
  )
}

function ConnectionsTab({ objectId }: { objectId: string }) {
  const { data: connections = [] } = useConnections()
  const { data: objects = [] } = useObjects()

  const incoming = connections.filter((c) => c.target_id === objectId)
  const outgoing = connections.filter((c) => c.source_id === objectId)

  const getObjectName = (id: string) => objects.find((o) => o.id === id)?.name || 'Unknown'

  return (
    <div className="space-y-4">
      <div>
        <div className="text-xs text-neutral-500 mb-2">
          Outgoing ({outgoing.length})
        </div>
        {outgoing.map((c) => (
          <div key={c.id} className="flex items-center gap-2 py-1.5 text-xs">
            <span className="text-neutral-500">→</span>
            <span className="text-neutral-300">{getObjectName(c.target_id)}</span>
            {c.label && <span className="text-neutral-600 truncate">({c.label})</span>}
          </div>
        ))}
        {outgoing.length === 0 && (
          <div className="text-xs text-neutral-600 italic">None</div>
        )}
      </div>
      <div>
        <div className="text-xs text-neutral-500 mb-2">
          Incoming ({incoming.length})
        </div>
        {incoming.map((c) => (
          <div key={c.id} className="flex items-center gap-2 py-1.5 text-xs">
            <span className="text-neutral-500">←</span>
            <span className="text-neutral-300">{getObjectName(c.source_id)}</span>
            {c.label && <span className="text-neutral-600 truncate">({c.label})</span>}
          </div>
        ))}
        {incoming.length === 0 && (
          <div className="text-xs text-neutral-600 italic">None</div>
        )}
      </div>
    </div>
  )
}

function HistoryTab({ objectId }: { objectId: string }) {
  const { data: entries = [], isLoading } = useObjectHistory(objectId)

  if (isLoading) {
    return <div className="text-xs text-neutral-500">Loading…</div>
  }
  if (entries.length === 0) {
    return (
      <div className="text-xs text-neutral-500 italic">
        No changes recorded yet.
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {entries.map((e) => (
        <HistoryEntry key={e.id} entry={e} />
      ))}
    </div>
  )
}

// Fields that should never surface in the history diff (noise for the user).
const HIDDEN_CHANGE_FIELDS = new Set(['metadata_'])

function HistoryEntry({ entry }: { entry: ActivityLogEntry }) {
  const date = new Date(entry.created_at)
  const when = date.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })

  if (entry.action === 'created') {
    const snap = (entry.changes || {}) as Record<string, unknown>
    return (
      <EntryShell when={when} action="Created" color="#22c55e">
        {typeof snap.name === 'string' && (
          <div className="text-xs text-neutral-300">
            Name: <span className="font-medium">{snap.name}</span>
          </div>
        )}
      </EntryShell>
    )
  }

  if (entry.action === 'deleted') {
    return <EntryShell when={when} action="Deleted" color="#ef4444" />
  }

  // updated
  const changes = (entry.changes || {}) as Record<
    string,
    { before: unknown; after: unknown }
  >
  const fields = Object.keys(changes).filter((k) => !HIDDEN_CHANGE_FIELDS.has(k))
  if (fields.length === 0) {
    return <EntryShell when={when} action="Updated" color="#3b82f6" />
  }

  return (
    <EntryShell when={when} action="Updated" color="#3b82f6">
      <div className="space-y-1">
        {fields.map((field) => (
          <FieldDiff
            key={field}
            field={field}
            before={changes[field]?.before}
            after={changes[field]?.after}
          />
        ))}
      </div>
    </EntryShell>
  )
}

function EntryShell({
  when,
  action,
  color,
  children,
}: {
  when: string
  action: string
  color: string
  children?: React.ReactNode
}) {
  return (
    <div className="border-l-2 pl-3" style={{ borderColor: color }}>
      <div className="flex items-center gap-2 mb-1">
        <span
          className="text-[10px] uppercase tracking-wide font-medium"
          style={{ color }}
        >
          {action}
        </span>
        <span className="text-[10px] text-neutral-500">{when}</span>
      </div>
      {children}
    </div>
  )
}

function formatValue(v: unknown): string {
  if (v === null || v === undefined) return '—'
  if (Array.isArray(v)) return v.length === 0 ? '—' : v.join(', ')
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

function FieldDiff({
  field,
  before,
  after,
}: {
  field: string
  before: unknown
  after: unknown
}) {
  return (
    <div className="text-xs text-neutral-300">
      <span className="text-neutral-500">{field}: </span>
      <span className="line-through text-neutral-500 mr-1">{formatValue(before)}</span>
      <span className="text-neutral-200">→ {formatValue(after)}</span>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-xs text-neutral-500 mb-1">{label}</div>
      {children}
    </div>
  )
}

function TagEditor({
  tags,
  onChange,
  placeholder,
}: {
  tags: string[]
  onChange: (tags: string[]) => void
  placeholder: string
}) {
  const [input, setInput] = useState('')

  const handleAdd = () => {
    const value = input.trim()
    if (value && !tags.includes(value)) {
      onChange([...tags, value])
    }
    setInput('')
  }

  return (
    <div>
      <div className="flex flex-wrap gap-1 mb-1">
        {tags.map((tag) => (
          <span
            key={tag}
            className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-neutral-800 text-neutral-300 text-xs"
          >
            {tag}
            <button
              onClick={() => onChange(tags.filter((t) => t !== tag))}
              className="text-neutral-500 hover:text-neutral-300"
            >
              ×
            </button>
          </span>
        ))}
      </div>
      <input
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={(e) => e.key === 'Enter' && handleAdd()}
        onBlur={handleAdd}
        className="bg-neutral-800 text-neutral-200 text-xs rounded px-2 py-1 w-full border border-neutral-700"
        placeholder={placeholder}
      />
    </div>
  )
}
