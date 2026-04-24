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
import { STATUS_COLORS, TYPE_ICONS, TYPE_LABELS } from '../canvas/node-utils'
import { RichTextEditor } from '../common/RichTextEditor'
import {
  CreateChildDiagramModal,
  DRILLABLE_TYPES,
} from '../drafts/CreateChildDiagramModal'
import { Avatar, AvatarStack, Pill, SectionLabel } from '../ui'
import { TechnologyPicker, TechBadge } from '../tech'
import { useTechnologies } from '../../hooks/use-api'
import { useWorkspaceStore } from '../../stores/workspace-store'
import { cn } from '../../utils/cn'

// ─── Helpers ──────────────────────────────────────────────────────────────────

function relTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60_000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  if (days < 30) return `${days}d ago`
  return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

// Deterministic tag color from string — cycles through semantic variants
const TAG_PALETTE: Array<{ text: string; border: string; bg: string }> = [
  { text: 'text-accent-pink',   border: 'border-accent-pink/35',   bg: 'bg-accent-pink-glow' },
  { text: 'text-accent-amber',  border: 'border-accent-amber/30',  bg: 'bg-accent-amber-glow' },
  { text: 'text-accent-blue',   border: 'border-accent-blue/30',   bg: 'bg-accent-blue-glow' },
  { text: 'text-accent-green',  border: 'border-accent-green/30',  bg: 'bg-accent-green-glow' },
  { text: 'text-accent-purple', border: 'border-accent-purple/30', bg: 'bg-accent-purple-glow' },
]

function tagColor(tag: string) {
  let hash = 0
  for (const c of tag) hash = (hash * 31 + c.charCodeAt(0)) | 0
  return TAG_PALETTE[Math.abs(hash) % TAG_PALETTE.length]
}

// ─── Types ────────────────────────────────────────────────────────────────────

interface ObjectSidebarProps {
  objectId?: string | null
  open?: boolean
  onClose?: () => void
  context?: 'canvas' | 'standalone'
}

// ─── Main component ───────────────────────────────────────────────────────────

export function ObjectSidebar({
  objectId,
  open,
  onClose,
  context = 'canvas',
}: ObjectSidebarProps = {}) {
  const { selectedNodeId, sidebarOpen, sidebarTab, setSidebarTab, toggleSidebar, selectedEdgeId } =
    useCanvasStore()
  const effectiveObjectId = objectId !== undefined ? objectId : selectedNodeId
  const effectiveOpen = open !== undefined ? open : sidebarOpen
  const handleClose = () => {
    if (onClose) onClose()
    else toggleSidebar(false)
  }
  const isStandalone = context === 'standalone'
  const { data: obj } = useObject(effectiveObjectId)
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

  if (!effectiveOpen || !obj) return null

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
      handleClose()
    }
  }

  const handleFieldChange = (field: string, value: unknown) => {
    updateObject.mutate({ id: obj.id, [field]: value })
  }

  const typeLabel = TYPE_LABELS[obj.type] ?? obj.type
  const levelLabel = `L${obj.c4_level ?? '?'}`

  return (
    <div className="w-80 bg-panel border-l border-border-base flex flex-col h-full overflow-hidden">

      {/* ── Header ── */}
      <div className="px-4 py-3 border-b border-border-base">
        {/* Top row: Inspector label + SELECTED pill + close */}
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <span className="font-mono text-[10px] uppercase tracking-[0.08em] text-text-3">Inspector</span>
            <Pill variant="draft" className="text-[9.5px] py-[2px]">SELECTED</Pill>
          </div>
          <button
            onClick={handleClose}
            className="text-text-4 hover:text-text-2 text-lg leading-none transition-colors"
            aria-label="Close inspector"
          >
            ×
          </button>
        </div>

        {/* Object name — inline editable */}
        <input
          value={editName}
          onChange={(e) => setEditName(e.target.value)}
          onBlur={handleSave}
          onKeyDown={(e) => e.key === 'Enter' && handleSave()}
          className="bg-transparent text-[15px] font-semibold text-text-base outline-none w-full mb-0.5"
        />
        <div className="font-mono text-[10.5px] text-text-3">
          {typeLabel} · {levelLabel}
        </div>
      </div>

      {/* ── Tabs ── */}
      <div className="flex border-b border-border-base">
        {(['details', 'connections', 'history'] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setSidebarTab(tab)}
            className={cn(
              'flex-1 px-3 py-2 font-mono text-[10.5px] uppercase tracking-[0.05em] transition-colors',
              sidebarTab === tab
                ? 'text-coral border-b-2 border-coral'
                : 'text-text-4 hover:text-text-2',
            )}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* ── Content ── */}
      <div className="flex-1 overflow-y-auto p-4 space-y-5">
        {sidebarTab === 'details' && (
          <>
            {/* Type */}
            <div>
              <SectionLabel className="mb-1.5">Type</SectionLabel>
              <select
                value={obj.type}
                onChange={(e) => handleFieldChange('type', e.target.value)}
                className="bg-surface border border-border-base text-text-2 text-[12.5px] rounded-md px-2.5 py-1.5 w-full"
              >
                {Object.entries(TYPE_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </select>
            </div>

            {/* Scope */}
            <div>
              <SectionLabel className="mb-1.5">Scope</SectionLabel>
              <select
                value={obj.scope}
                onChange={(e) => handleFieldChange('scope', e.target.value as ObjectScope)}
                className="bg-surface border border-border-base text-text-2 text-[12.5px] rounded-md px-2.5 py-1.5 w-full"
              >
                <option value="internal">Internal</option>
                <option value="external">External</option>
              </select>
            </div>

            {/* Status */}
            <div>
              <SectionLabel className="mb-1.5">Status</SectionLabel>
              <div className="flex gap-1.5">
                {(['live', 'future', 'deprecated', 'removed'] as ObjectStatus[]).map((status) => (
                  <button
                    key={status}
                    onClick={() => handleFieldChange('status', status)}
                    className={cn(
                      'flex items-center gap-1 px-2 py-1 rounded-md text-[11px] capitalize transition-colors',
                      obj.status === status
                        ? 'bg-surface-hi text-text-base border border-border-hi'
                        : 'text-text-4 hover:text-text-2',
                    )}
                  >
                    <span
                      className="w-2 h-2 rounded-full flex-shrink-0"
                      style={{ backgroundColor: STATUS_COLORS[status] }}
                    />
                    {status}
                  </button>
                ))}
              </div>
            </div>

            {/* Cross-references — canvas context only */}
            {!isStandalone && <CrossReferences objectId={obj.id} />}

            {/* Description */}
            <div>
              <SectionLabel className="mb-1.5">Description</SectionLabel>
              <div className="bg-surface border border-border-base rounded-md p-3">
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
              </div>
            </div>

            {/* Technology stack */}
            <div>
              <SectionLabel className="mb-1.5">Technology stack</SectionLabel>
              <TechnologyPicker
                mode={{
                  multi: true,
                  value: obj.technology_ids || [],
                  onChange: (ids) => handleFieldChange('technology_ids', ids),
                }}
                placeholder="Add technology…"
              />
            </div>

            {/* Tags */}
            <div>
              <SectionLabel className="mb-1.5">Tags</SectionLabel>
              <ColoredTagEditor
                tags={obj.tags || []}
                onChange={(tags) => handleFieldChange('tags', tags)}
              />
            </div>

            {/* Connections list with selected-edge coral glow */}
            {!isStandalone && (
              <ConnectionsList objectId={obj.id} selectedEdgeId={selectedEdgeId} />
            )}

            {/* Owners */}
            <OwnersSection ownerTeam={obj.owner_team} />

            {/* Drill into — only for drillable types, canvas context only */}
            {!isStandalone && DRILLABLE_TYPES.has(obj.type) && (
              <DrillIntoSection obj={obj} />
            )}

            {/* Group members — only for group type, canvas context only */}
            {!isStandalone && obj.type === 'group' && (
              <GroupMembersSection groupId={obj.id} />
            )}

            {/* Delete */}
            <button
              onClick={handleDelete}
              className="w-full mt-2 px-3 py-2 rounded-md text-[12.5px] font-mono border border-accent-pink/40 text-accent-pink hover:bg-accent-pink-glow transition-colors"
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

      {/* ── Footer meta ── */}
      <div className="border-t border-border-base p-4 space-y-1 font-mono text-[11px] text-text-3">
        {obj.created_at && (
          <div className="flex justify-between">
            <span>created</span>
            <span>{relTime(obj.created_at)}</span>
          </div>
        )}
        {obj.updated_at && (
          <div className="flex justify-between">
            <span>last edit</span>
            <span>{relTime(obj.updated_at)}</span>
          </div>
        )}
        <div className="flex justify-between">
          <span>version</span>
          <span>
            v1.0 ·{' '}
            <span className="text-coral">
              {obj.status === 'live' ? 'live' : 'draft'}
            </span>
          </span>
        </div>
      </div>
    </div>
  )
}

// ─── Colored Tag Editor ───────────────────────────────────────────────────────

function ColoredTagEditor({
  tags,
  onChange,
}: {
  tags: string[]
  onChange: (tags: string[]) => void
}) {
  const [adding, setAdding] = useState(false)
  const [input, setInput] = useState('')

  const handleAdd = () => {
    const v = input.trim()
    if (v && !tags.includes(v)) onChange([...tags, v])
    setInput('')
    setAdding(false)
  }

  return (
    <div className="flex flex-wrap gap-1.5">
      {tags.map((tag) => {
        const { text, border, bg } = tagColor(tag)
        return (
          <span
            key={tag}
            className={cn(
              'group inline-flex items-center gap-1 px-2 py-[3px] border rounded-md font-mono text-[10.5px]',
              text, border, bg,
            )}
          >
            #{tag}
            <button
              onClick={() => onChange(tags.filter((t) => t !== tag))}
              className="opacity-0 group-hover:opacity-100 transition-opacity leading-none"
              aria-label={`Remove ${tag}`}
            >
              ×
            </button>
          </span>
        )
      })}
      {adding ? (
        <input
          autoFocus
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') handleAdd()
            if (e.key === 'Escape') { setAdding(false); setInput('') }
          }}
          onBlur={handleAdd}
          className="inline-flex px-2 py-[3px] bg-surface border border-coral/50 rounded-md font-mono text-[10.5px] text-text-base outline-none w-24"
          placeholder="#tag"
        />
      ) : (
        <button
          onClick={() => setAdding(true)}
          className="inline-flex items-center px-2 py-[3px] border border-dashed border-border-hi rounded-md font-mono text-[10.5px] text-text-3 hover:border-coral hover:text-coral transition-colors cursor-pointer"
        >
          +
        </button>
      )}
    </div>
  )
}

// ─── Connections list (with selected-edge highlight) ─────────────────────────

function ConnectionsList({
  objectId,
  selectedEdgeId,
}: {
  objectId: string
  selectedEdgeId: string | null
}) {
  const { data: connections = [] } = useConnections()
  const { data: objects = [] } = useObjects()
  const { selectEdge } = useCanvasStore()
  const workspaceId = useWorkspaceStore((s) => s.currentWorkspaceId)
  const { data: catalog = [] } = useTechnologies(workspaceId)

  const related = connections.filter(
    (c) => c.source_id === objectId || c.target_id === objectId,
  )
  if (related.length === 0) return null

  const getName = (id: string) => objects.find((o) => o.id === id)?.name ?? 'Unknown'
  const getProtocol = (id: string | null) =>
    id ? catalog.find((t) => t.id === id) : undefined

  return (
    <div>
      <SectionLabel className="mb-2" counter={related.length}>Connections</SectionLabel>
      <div className="space-y-1.5">
        {related.map((c) => {
          const isOutgoing = c.source_id === objectId
          const otherId = isOutgoing ? c.target_id : c.source_id
          const isSelected = c.id === selectedEdgeId

          return (
            <button
              key={c.id}
              onClick={() => selectEdge(c.id)}
              className={cn(
                'w-full flex items-center gap-2 text-left text-[12px] p-2 rounded-md border transition-all',
                isSelected
                  ? 'bg-coral-glow border-coral shadow-[0_0_0_3px_rgba(255,107,53,0.15)]'
                  : 'bg-surface border-border-base hover:border-border-hi',
              )}
            >
              {/* Direction arrow */}
              <svg
                width="12" height="12"
                viewBox="0 0 24 24"
                fill="none"
                stroke={isSelected ? '#FF6B35' : '#71717a'}
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                className="flex-shrink-0"
              >
                {isOutgoing
                  ? <path d="M5 12h14M13 5l6 7-6 7" />
                  : <path d="M19 12H5M11 5L5 12l6 7" />}
              </svg>

              <span className={cn('flex-1 text-[12.5px] truncate', isSelected ? 'text-text-base' : 'text-text-2')}>
                {getName(otherId)}
              </span>

              {(() => {
                const proto = getProtocol(c.protocol_id)
                return proto ? (
                  <TechBadge technology={proto} iconOnly className="!border-transparent !bg-transparent !px-0" />
                ) : null
              })()}

              {!c.protocol_id && c.label && (
                <span className={cn('font-mono text-[10.5px] flex-shrink-0 truncate max-w-[70px]', isSelected ? 'text-coral' : 'text-text-3')}>
                  {c.label}
                </span>
              )}

              {/* direction indicator */}
              <span className={cn('font-mono text-[9.5px] flex-shrink-0', isSelected ? 'text-coral' : 'text-text-4')}>
                {isOutgoing ? '↑' : '↓'}
              </span>
            </button>
          )
        })}
      </div>
    </div>
  )
}

// ─── Owners section ───────────────────────────────────────────────────────────

function OwnersSection({ ownerTeam }: { ownerTeam?: string | null }) {
  // TODO: wire to real workspace members once members integration lands.
  // For now render owner_team text as a single avatar if set, plus dashed add button.
  const initials = ownerTeam
    ? ownerTeam
        .split(/\s+/)
        .slice(0, 2)
        .map((w) => w[0] ?? '')
        .join('')
        .toUpperCase()
    : null

  return (
    <div>
      <SectionLabel className="mb-2">Owners</SectionLabel>
      <div className="flex items-center gap-2">
        <AvatarStack>
          {initials && (
            <Avatar initials={initials} gradient="coral-amber" size="sm" />
          )}
        </AvatarStack>
        {/* TODO: open members picker when workspace members API is ready */}
        <button
          onClick={() => {/* no-op — owners stub */}}
          className="w-7 h-7 rounded-full border border-dashed border-border-hi flex items-center justify-center text-text-3 hover:border-coral hover:text-coral transition-colors"
          aria-label="Add owner"
        >
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M12 5v14M5 12h14" />
          </svg>
        </button>
      </div>
    </div>
  )
}

// ─── DrillIntoSection ─────────────────────────────────────────────────────────

function DrillIntoSection({ obj }: { obj: ModelObject }) {
  const navigate = useNavigate()
  const { data: childDiagrams = [] } = useDiagrams(obj.id)
  const [createModalOpen, setCreateModalOpen] = useState(false)

  const levelText = obj.type === 'system' ? 'Container diagram (L2)' : 'Component diagram (L3)'

  return (
    <div>
      <SectionLabel className="mb-1.5">Drill into</SectionLabel>
      <div className="bg-surface border border-border-base rounded-md p-2.5 flex flex-col gap-1.5">
        <div className="font-mono text-[10px] text-text-4 uppercase tracking-[0.05em]">
          {levelText}
        </div>
        {childDiagrams.length === 0 ? (
          <button
            onClick={() => setCreateModalOpen(true)}
            className="bg-accent-blue-glow border border-accent-blue/25 rounded-md text-accent-blue text-[12px] px-2.5 py-1.5 text-left hover:border-accent-blue/50 transition-colors"
          >
            + Create {obj.type === 'system' ? 'container' : 'component'} diagram
          </button>
        ) : (
          <>
            {childDiagrams.map((d) => (
              <button
                key={d.id}
                onClick={() => navigate(`/diagram/${d.id}`)}
                className="bg-transparent border border-border-base rounded-md text-accent-blue text-[12px] px-2.5 py-1 text-left hover:bg-accent-blue-glow hover:border-accent-blue/30 transition-colors"
              >
                {d.name}
              </button>
            ))}
            <button
              onClick={() => setCreateModalOpen(true)}
              className="text-text-4 hover:text-text-2 text-[11px] text-left transition-colors"
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

// ─── CrossReferences ──────────────────────────────────────────────────────────

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
        <div className="flex items-center justify-between text-[11.5px]">
          <span className="text-text-3">Belongs to</span>
          <button
            onClick={() => selectNode(parent.id)}
            className="text-accent-blue hover:text-accent-blue/80 transition-colors"
          >
            {parent.name}
          </button>
        </div>
      )}
      <div className="flex items-center justify-between text-[11.5px]">
        <span className="text-text-3">Contains</span>
        <span className="text-text-2">{children.length} objects</span>
      </div>
      <div className="flex items-center justify-between text-[11.5px]">
        <span className="text-text-3">Connections</span>
        <span className="text-text-2">{connCount}</span>
      </div>
      <div className="flex items-start justify-between text-[11.5px]">
        <span className="text-text-3">Diagrams</span>
        {objectDiagrams.length > 0 ? (
          <div className="flex flex-col gap-0.5 items-end">
            {objectDiagrams.slice(0, 3).map((d) => (
              <button
                key={d.id}
                onClick={() => navigate(`/diagram/${d.id}`)}
                className="text-accent-blue hover:text-accent-blue/80 truncate max-w-[160px] transition-colors"
              >
                {d.name}
              </button>
            ))}
            {objectDiagrams.length > 3 && (
              <span className="text-text-4">+{objectDiagrams.length - 3} more</span>
            )}
          </div>
        ) : (
          <span className="text-text-4">None</span>
        )}
      </div>
    </div>
  )
}

// ─── GroupMembersSection ──────────────────────────────────────────────────────

function GroupMembersSection({ groupId }: { groupId: string }) {
  const { data: children = [], isLoading } = useObjectChildren(groupId)
  const { selectNode } = useCanvasStore()

  return (
    <div>
      <SectionLabel className="mb-1.5">Members</SectionLabel>
      <div className="bg-surface border border-border-base rounded-md overflow-hidden">
        {isLoading ? (
          <div className="p-2.5 text-[12px] text-text-4">Loading…</div>
        ) : children.length === 0 ? (
          <div className="p-2.5 text-[12px] text-text-4 italic">No objects in this group yet.</div>
        ) : (
          children.map((child, i) => (
            <button
              key={child.id}
              onClick={() => selectNode(child.id)}
              className={cn(
                'flex items-center gap-2 w-full px-2.5 py-1.5 bg-transparent text-text-2 text-[12px] text-left hover:bg-surface-hi transition-colors',
                i < children.length - 1 && 'border-b border-border-base',
              )}
            >
              <span className="opacity-50 text-[13px]">{TYPE_ICONS[child.type]}</span>
              <span className="flex-1 truncate">{child.name}</span>
              <span className="text-[10px] text-text-4">{TYPE_LABELS[child.type]}</span>
            </button>
          ))
        )}
      </div>
    </div>
  )
}

// ─── ConnectionsTab ───────────────────────────────────────────────────────────

function ConnectionsTab({ objectId }: { objectId: string }) {
  const { data: connections = [] } = useConnections()
  const { data: objects = [] } = useObjects()

  const incoming = connections.filter((c) => c.target_id === objectId)
  const outgoing = connections.filter((c) => c.source_id === objectId)

  const getObjectName = (id: string) => objects.find((o) => o.id === id)?.name || 'Unknown'

  return (
    <div className="space-y-4">
      <div>
        <SectionLabel className="mb-2" counter={outgoing.length}>Outgoing</SectionLabel>
        {outgoing.map((c) => (
          <div key={c.id} className="flex items-center gap-2 py-1.5 text-[12px]">
            <span className="text-text-3">→</span>
            <span className="text-text-2">{getObjectName(c.target_id)}</span>
            {c.label && <span className="text-text-4 font-mono text-[10.5px] truncate">({c.label})</span>}
          </div>
        ))}
        {outgoing.length === 0 && (
          <div className="text-[11.5px] text-text-4 italic">None</div>
        )}
      </div>
      <div>
        <SectionLabel className="mb-2" counter={incoming.length}>Incoming</SectionLabel>
        {incoming.map((c) => (
          <div key={c.id} className="flex items-center gap-2 py-1.5 text-[12px]">
            <span className="text-text-3">←</span>
            <span className="text-text-2">{getObjectName(c.source_id)}</span>
            {c.label && <span className="text-text-4 font-mono text-[10.5px] truncate">({c.label})</span>}
          </div>
        ))}
        {incoming.length === 0 && (
          <div className="text-[11.5px] text-text-4 italic">None</div>
        )}
      </div>
    </div>
  )
}

// ─── HistoryTab ───────────────────────────────────────────────────────────────

function HistoryTab({ objectId }: { objectId: string }) {
  const { data: entries = [], isLoading } = useObjectHistory(objectId)

  if (isLoading) {
    return <div className="text-[11.5px] text-text-3">Loading…</div>
  }
  if (entries.length === 0) {
    return (
      <div className="text-[11.5px] text-text-3 italic">No changes recorded yet.</div>
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
      <EntryShell when={when} action="Created" color="#4ade80">
        {typeof snap.name === 'string' && (
          <div className="text-[11.5px] text-text-2">
            Name: <span className="font-medium">{snap.name}</span>
          </div>
        )}
      </EntryShell>
    )
  }

  if (entry.action === 'deleted') {
    return <EntryShell when={when} action="Deleted" color="#f472b6" />
  }

  const changes = (entry.changes || {}) as Record<
    string,
    { before: unknown; after: unknown }
  >
  const fields = Object.keys(changes).filter((k) => !HIDDEN_CHANGE_FIELDS.has(k))
  if (fields.length === 0) {
    return <EntryShell when={when} action="Updated" color="#60a5fa" />
  }

  return (
    <EntryShell when={when} action="Updated" color="#60a5fa">
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
          className="text-[10px] uppercase tracking-wide font-medium font-mono"
          style={{ color }}
        >
          {action}
        </span>
        <span className="text-[10px] text-text-4">{when}</span>
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
    <div className="text-[11.5px] text-text-2">
      <span className="text-text-3">{field}: </span>
      <span className="line-through text-text-4 mr-1">{formatValue(before)}</span>
      <span className="text-text-base">→ {formatValue(after)}</span>
    </div>
  )
}
