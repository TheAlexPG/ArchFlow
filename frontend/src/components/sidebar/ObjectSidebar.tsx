import { useCallback, useEffect, useRef, useState } from 'react'
import { useConnections, useDeleteObject, useObject, useObjects, useUpdateObject } from '../../hooks/use-api'
import { useCanvasStore } from '../../stores/canvas-store'
import type { ObjectScope, ObjectStatus, ObjectType } from '../../types/model'
import { STATUS_COLORS, TYPE_LABELS } from '../canvas/node-utils'
import { RichTextEditor } from '../common/RichTextEditor'

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

        {sidebarTab === 'history' && (
          <div className="text-sm text-neutral-500 italic">
            History will be available after versioning is enabled.
          </div>
        )}
      </div>
    </div>
  )
}

function CrossReferences({ objectId }: { objectId: string }) {
  const { data: objects = [] } = useObjects()
  const { data: connections = [] } = useConnections()

  const children = objects.filter((o) => o.parent_id === objectId)
  const connCount = connections.filter(
    (c) => c.source_id === objectId || c.target_id === objectId,
  ).length

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-xs">
        <span className="text-neutral-500">Contains</span>
        <span className="text-neutral-300">{children.length} objects</span>
      </div>
      <div className="flex items-center justify-between text-xs">
        <span className="text-neutral-500">Connections</span>
        <span className="text-neutral-300">{connCount}</span>
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
