import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import {
  useAddObjectToDiagram,
  useCreateObject,
  useDiagramObjects,
  useObjects,
  useUpdateObject,
} from '../../hooks/use-api'
import { useDiagram } from '../../hooks/use-diagrams'
import { useCanvasStore } from '../../stores/canvas-store'
import type { CommentType, DiagramType, ObjectType } from '../../types/model'
import { cn } from '../../utils/cn'
import { SectionLabel } from '../ui'
import { detectParentGroup, nodeToRect } from './group-utils'
import { TYPE_BORDER_COLORS, TYPE_LABELS } from './node-utils'
import { NewObjectModal } from './NewObjectModal'

// ─── Type helpers (match AddObjectToolbar's logic exactly) ────────────────────

const ALL_QUICK_TYPES: ObjectType[] = ['system', 'actor', 'external_system', 'app', 'store', 'group']

const DIAGRAM_LEVEL_LABEL: Record<DiagramType, string> = {
  system_landscape: 'L1 · System Landscape',
  system_context: 'L1 · System Context',
  container: 'L2 · Container',
  component: 'L3 · Component',
  custom: 'Custom',
}

function getQuickTypesForDiagram(diagramType: DiagramType | undefined): ObjectType[] {
  if (!diagramType) return ALL_QUICK_TYPES
  switch (diagramType) {
    case 'system_landscape':
    case 'system_context':
      return ['system', 'actor', 'external_system', 'group']
    case 'container':
      return ['app', 'store', 'component', 'system', 'external_system', 'actor', 'group']
    case 'component':
      return ['component', 'system', 'external_system', 'actor', 'group']
    case 'custom':
    default:
      return ALL_QUICK_TYPES
  }
}

// ─── SVG icons (inline, no deps) ────────────────────────────────────────────

function PlusIcon() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.5"
      strokeLinecap="round"
    >
      <path d="M12 5v14M5 12h14" />
    </svg>
  )
}

function SearchIcon() {
  return (
    <svg
      width="12"
      height="12"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
    >
      <circle cx="11" cy="11" r="8" />
      <path d="m21 21-4.35-4.35" />
    </svg>
  )
}

// Per-type SVG icons for the "Create new object" grid
function SystemIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <rect x="3" y="3" width="18" height="18" rx="3" />
    </svg>
  )
}

function ActorIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <circle cx="12" cy="7" r="4" />
      <path d="M5.5 21c.83-4 4-6 6.5-6s5.67 2 6.5 6" />
    </svg>
  )
}

function ExternalIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M21 12.8V7a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h8.5" />
      <path d="M15 3v4M9 3v4M3 11h18" />
      <circle cx="18" cy="18" r="3" />
      <path d="m16.5 19.5 3-3" />
    </svg>
  )
}

function GroupIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeDasharray="3 2">
      <rect x="3" y="3" width="18" height="18" rx="2" />
    </svg>
  )
}

// Small obj-row type icons (14px)
function ObjTypeIcon({ type }: { type: ObjectType }) {
  const color = TYPE_BORDER_COLORS[type]
  switch (type) {
    case 'system':
      return (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="1.8">
          <rect x="3" y="3" width="18" height="18" rx="3" />
        </svg>
      )
    case 'actor':
      return (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="1.8">
          <circle cx="12" cy="7" r="4" />
          <path d="M5.5 21c.83-4 4-6 6.5-6s5.67 2 6.5 6" />
        </svg>
      )
    case 'external_system':
      return (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="1.8">
          <path d="M21 12.8V7a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h7" />
          <circle cx="17" cy="17" r="3" />
          <path d="m15.5 18.5 3-3" />
        </svg>
      )
    case 'group':
      return (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="1.8" strokeDasharray="3 2">
          <rect x="3" y="3" width="18" height="18" rx="2" />
        </svg>
      )
    case 'app':
      return (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="1.8">
          <rect x="3" y="3" width="18" height="18" rx="2" />
          <path d="M3 9h18M9 3v18" />
        </svg>
      )
    case 'store':
      return (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="1.8">
          <ellipse cx="12" cy="5" rx="9" ry="3" />
          <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5M3 12c0 1.66 4 3 9 3s9-1.34 9-3" />
        </svg>
      )
    case 'component':
      return (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="1.8">
          <rect x="3" y="3" width="18" height="18" rx="2" />
          <path d="M9 3v18M3 9h6M3 15h6" />
        </svg>
      )
    default:
      return null
  }
}

// Map ObjectType to which quick-create icon component to use
const CREATE_TYPE_CONFIGS: {
  type: ObjectType
  label: string
  icon: React.ReactNode
}[] = [
  { type: 'system', label: 'System', icon: <SystemIcon /> },
  { type: 'actor', label: 'Actor', icon: <ActorIcon /> },
  { type: 'external_system', label: 'External', icon: <ExternalIcon /> },
  { type: 'group', label: 'Group', icon: <GroupIcon /> },
]

// Annotation types — wired to existing comment compose mechanism
const ANNOTATION_CONFIGS: {
  value: CommentType
  label: string
  icon: React.ReactNode
  colorClass: string
  hoverClass: string
}[] = [
  {
    value: 'question',
    label: 'Question',
    colorClass: 'text-accent-amber border-accent-amber/30 bg-accent-amber-glow',
    hoverClass: 'hover:border-accent-amber hover:text-accent-amber',
    icon: (
      <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
        <circle cx="12" cy="12" r="10" />
        <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3M12 17h.01" />
      </svg>
    ),
  },
  {
    value: 'inaccuracy',
    label: 'Inaccuracy',
    colorClass: 'border-[#ef4444]/30 bg-[#ef4444]/10',
    hoverClass: 'hover:border-[#ef4444]',
    icon: (
      <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="#ef4444" strokeWidth="2.2">
        <path d="M3 3l18 18M10.58 5.08A10 10 0 0 1 22 12c-.58 1.12-1.33 2.14-2.21 3.02M6.61 6.61A10 10 0 0 0 2 12s3.5 7 10 7c1.84 0 3.55-.4 5.08-1.08" />
      </svg>
    ),
  },
  {
    value: 'idea',
    label: 'Idea',
    colorClass: 'text-accent-amber border-accent-amber/30 bg-accent-amber-glow',
    hoverClass: 'hover:border-accent-amber hover:text-accent-amber',
    icon: (
      <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
        <path d="M9 18h6M10 22h4M12 2a7 7 0 0 0-4 12.74V17h8v-2.26A7 7 0 0 0 12 2z" />
      </svg>
    ),
  },
  {
    value: 'note',
    label: 'Note',
    colorClass: 'text-accent-blue border-accent-blue/30 bg-accent-blue-glow',
    hoverClass: 'hover:border-accent-blue hover:text-accent-blue',
    icon: (
      <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
        <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
        <path d="M18.5 2.5a2.1 2.1 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
      </svg>
    ),
  },
]

// ─── Props ───────────────────────────────────────────────────────────────────

interface AddObjectFABProps {
  diagramId?: string
}

// ─── Component ────────────────────────────────────────────────────────────────

export function AddObjectFAB({ diagramId }: AddObjectFABProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [newObjectType, setNewObjectType] = useState<ObjectType | null>(null)

  // ── Data hooks (identical to AddObjectToolbar) ──────────────────────────
  const { data: diagram } = useDiagram(diagramId)
  const draftId = diagram?.draft_id ?? null
  const diagramType = diagram?.type as DiagramType | undefined
  const quickTypes = getQuickTypesForDiagram(diagramType)
  const levelLabel = diagramType ? DIAGRAM_LEVEL_LABEL[diagramType] : null

  const { data: objects = [] } = useObjects(draftId)
  const { data: diagramObjects = [] } = useDiagramObjects(diagramId)
  const createObject = useCreateObject(draftId)
  const addToDiagram = useAddObjectToDiagram()
  const updateObject = useUpdateObject()
  const { setCommentComposeType } = useCanvasStore()

  // ── Derived ─────────────────────────────────────────────────────────────
  const inDiagramIds = useMemo(
    () => new Set(diagramObjects.map((d) => d.object_id)),
    [diagramObjects],
  )

  const filtered = useMemo(() => {
    if (!search) return objects
    const q = search.toLowerCase()
    return objects.filter(
      (o) =>
        o.name.toLowerCase().includes(q) ||
        o.description?.toLowerCase().includes(q) ||
        o.technology?.some((t) => t.toLowerCase().includes(q)),
    )
  }, [objects, search])

  // ── Handlers ─────────────────────────────────────────────────────────────

  const handleAddExisting = (objectId: string) => {
    if (!diagramId) return
    if (inDiagramIds.has(objectId)) return
    addToDiagram.mutate({
      diagramId,
      objectId,
      x: 200 + Math.random() * 300,
      y: 150 + Math.random() * 250,
    })
    setIsOpen(false)
  }

  const handleCreateNew = (type: ObjectType) => {
    setNewObjectType(type)
    // Keep FAB popup open until user confirms in the modal
  }

  const handleNewObjectSubmit = (name: string) => {
    if (!newObjectType) return
    const type = newObjectType
    const placementX = 200 + Math.random() * 300
    const placementY = 150 + Math.random() * 250
    createObject.mutate(
      { name: name.trim(), type },
      {
        onSuccess: (obj) => {
          if (!diagramId) return
          addToDiagram.mutate(
            { diagramId, objectId: obj.id, x: placementX, y: placementY },
            {
              onSuccess: () => {
                if (type === 'group') return
                const nodeRect = nodeToRect(
                  obj.id,
                  { x: placementX, y: placementY },
                  undefined,
                  undefined,
                  [obj],
                )
                const newParentId = detectParentGroup(obj.id, nodeRect, diagramObjects, [
                  ...objects,
                  obj,
                ])
                if (newParentId) {
                  updateObject.mutate({ id: obj.id, parent_id: newParentId })
                }
              },
            },
          )
        },
      },
    )
    setNewObjectType(null)
    setIsOpen(false)
  }

  const handleAnnotation = (type: CommentType) => {
    setCommentComposeType(type)
    setIsOpen(false)
  }

  // ── Close on click-outside / Escape ─────────────────────────────────────
  const containerRef = useRef<HTMLDivElement>(null)
  const fabRef = useRef<HTMLButtonElement>(null)

  // Popup anchors its horizontal edge to the FAB's right side but floats to
  // the viewport's vertical centre — so it never clips off the screen
  // regardless of where the FAB itself sits within the canvas.
  const [popupLeft, setPopupLeft] = useState(72)
  useLayoutEffect(() => {
    if (!isOpen) return
    const recompute = () => {
      const rect = fabRef.current?.getBoundingClientRect()
      if (rect) setPopupLeft(rect.right + 12)
    }
    recompute()
    window.addEventListener('resize', recompute)
    return () => window.removeEventListener('resize', recompute)
  }, [isOpen])

  useEffect(() => {
    if (!isOpen) return
    const handlePointerDown = (e: PointerEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false)
      }
    }
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setIsOpen(false)
    }
    document.addEventListener('pointerdown', handlePointerDown)
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('pointerdown', handlePointerDown)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [isOpen])

  // Reset search when popup closes
  useEffect(() => {
    if (!isOpen) setSearch('')
  }, [isOpen])

  // ── Render ───────────────────────────────────────────────────────────────

  return (
    <div ref={containerRef} className="relative">
      {/* ── FAB button ── */}
      <button
        ref={fabRef}
        onClick={() => setIsOpen((v) => !v)}
        title="Add to canvas (A)"
        aria-label="Add object to diagram"
        style={{
          width: 44,
          height: 44,
          borderRadius: '50%',
          border: 'none',
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          flexShrink: 0,
          // Open state: neutral surface; closed state: coral gradient
          background: isOpen
            ? 'var(--color-surface)'
            : 'linear-gradient(135deg, #FF8552 0%, #FF6B35 100%)',
          color: isOpen ? 'var(--color-text-base)' : '#0a0a0b',
          boxShadow: isOpen
            ? '0 4px 12px rgba(0,0,0,0.4)'
            : '0 8px 24px -4px rgba(0,0,0,0.6), 0 0 0 1px rgba(255,107,53,0.3)',
          transform: isOpen ? 'rotate(45deg)' : undefined,
          // Springy hover is handled via CSS class below; we set the base transition
          transition:
            'transform 0.2s cubic-bezier(0.34, 1.56, 0.64, 1), box-shadow 0.2s ease, background 0.15s ease',
          animation: isOpen ? 'none' : 'fab-ring 3s ease-in-out infinite',
        }}
        className={cn(
          // Hover scale — only when not open (open has its own rotate-45 state)
          !isOpen && 'hover:scale-[1.08] hover:!rotate-90',
          // Stronger shadow on hover (closed)
          !isOpen &&
            'hover:![box-shadow:0_12px_32px_-4px_rgba(255,107,53,0.5),0_0_0_1px_rgba(255,107,53,0.5)]',
        )}
      >
        <PlusIcon />
      </button>

      {/* ── Popup ── */}
      {isOpen && (
        <div
          className="add-popup flex flex-col"
          style={{
            position: 'fixed',
            left: popupLeft,
            top: '50vh',
            transform: 'translateY(-50%)',
            width: 340,
            maxHeight: 'min(640px, calc(100vh - 40px))',
            background: 'var(--color-panel)',
            border: '1px solid var(--color-border-base)',
            borderRadius: 12,
            boxShadow:
              '0 20px 60px -10px rgba(0,0,0,0.7), 0 0 0 1px rgba(255,255,255,0.02)',
            zIndex: 30,
            overflow: 'hidden',
          }}
        >
          {/* ── Fixed header: search ── */}
          <div
            className="flex-shrink-0"
            style={{
              padding: '10px 12px 10px',
              borderBottom: '1px solid var(--color-border-base)',
            }}
          >
            <div className="flex items-center justify-between mb-2.5">
              <div>
                <SectionLabel>Add to canvas</SectionLabel>
                {levelLabel && (
                  <div className="font-mono text-[10px] text-text-3 mt-0.5">{levelLabel}</div>
                )}
              </div>
            </div>
            {/* Search input */}
            <div
              className="flex items-center gap-1.5 px-2.5 py-2 rounded-md border border-border-base bg-surface focus-within:border-coral transition-colors"
            >
              <span className="text-text-3 flex-shrink-0">
                <SearchIcon />
              </span>
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search or type to create..."
                autoFocus
                className="bg-transparent outline-none text-[12.5px] w-full placeholder:text-text-4 text-text-base"
              />
            </div>
          </div>

          {/* ── Scrollable pool section ── */}
          <div
            className="flex-shrink-0 px-2 pt-2 pb-1"
            style={{ maxHeight: 280, overflowY: 'auto' }}
          >
            <div
              className="popup-section px-1 pt-1 pb-2"
              style={{ animationDelay: '0ms' }}
            >
              <div className="flex items-center justify-between px-2 mb-1.5">
                <SectionLabel counter={filtered.length}>From object pool</SectionLabel>
              </div>

              {filtered.length === 0 ? (
                <div className="px-2 py-3 font-mono text-[11px] text-text-4 text-center">
                  {search ? 'No matches' : 'No objects yet'}
                </div>
              ) : (
                <div className="space-y-0.5">
                  {filtered.map((obj, idx) => {
                    const inDiagram = inDiagramIds.has(obj.id)
                    const delayMs = [50, 80, 110, 140, 170, 200, 230, 260][idx] ?? 260
                    return (
                      <button
                        key={obj.id}
                        onClick={() => handleAddExisting(obj.id)}
                        disabled={inDiagram}
                        title={
                          inDiagram
                            ? 'Already in this diagram'
                            : `Add ${TYPE_LABELS[obj.type]} to diagram`
                        }
                        className={cn(
                          'obj-row popup-item w-full text-left group/row',
                          inDiagram && 'opacity-50 cursor-default',
                        )}
                        style={{ animationDelay: `${delayMs}ms` }}
                      >
                        {/* Type icon */}
                        <div
                          className="obj-icon flex-shrink-0"
                          style={{
                            borderColor:
                              TYPE_BORDER_COLORS[obj.type] + '66',
                          }}
                        >
                          <ObjTypeIcon type={obj.type} />
                        </div>

                        {/* Name + subtext */}
                        <div className="flex-1 min-w-0">
                          <div className="text-[12.5px] font-medium text-text-base truncate">
                            {obj.name}
                          </div>
                          <div className="font-mono text-[10.5px] text-text-3 truncate">
                            {TYPE_LABELS[obj.type].toLowerCase()}
                            {obj.technology && obj.technology.length > 0
                              ? ` · ${obj.technology.join(', ')}`
                              : ''}
                          </div>
                        </div>

                        {/* Hover-reveal add hint */}
                        {!inDiagram && (
                          <div className="obj-add-hint flex-shrink-0">↵ add</div>
                        )}
                        {inDiagram && (
                          <span
                            title="In this diagram"
                            className="font-mono text-[9px] text-accent-blue flex-shrink-0"
                          >
                            ●
                          </span>
                        )}
                      </button>
                    )
                  })}
                </div>
              )}
            </div>
          </div>

          {/* ── Fixed: Create new object ── */}
          <div
            className="flex-shrink-0 px-2 pt-1 pb-2"
            style={{ borderTop: '1px solid var(--color-border-base)' }}
          >
            <div
              className="popup-section px-1 pt-1 pb-2"
              style={{ animationDelay: '120ms' }}
            >
              <div className="flex items-center justify-between px-2 mb-2">
                <SectionLabel>Create new object</SectionLabel>
                {levelLabel && (
                  <span className="font-mono text-[9.5px] text-text-3">{levelLabel}</span>
                )}
              </div>

              <div className="grid grid-cols-4 gap-1.5 px-1">
                {CREATE_TYPE_CONFIGS.filter((c) =>
                  quickTypes.includes(c.type),
                ).map((cfg, idx) => (
                  <button
                    key={cfg.type}
                    onClick={() => handleCreateNew(cfg.type)}
                    title={cfg.label}
                    className="create-type-btn popup-item"
                    style={{ animationDelay: `${50 + idx * 30}ms` }}
                  >
                    <div className="create-type-icon">{cfg.icon}</div>
                    <div className="font-mono text-[10px] text-text-2">{cfg.label}</div>
                  </button>
                ))}
                {/* Extra types that don't appear in the 4 standard buttons */}
                {quickTypes
                  .filter((t) => !CREATE_TYPE_CONFIGS.some((c) => c.type === t))
                  .map((type, idx) => (
                    <button
                      key={type}
                      onClick={() => handleCreateNew(type)}
                      title={TYPE_LABELS[type]}
                      className="create-type-btn popup-item"
                      style={{ animationDelay: `${170 + idx * 30}ms` }}
                    >
                      <div className="create-type-icon">
                        <ObjTypeIcon type={type} />
                      </div>
                      <div className="font-mono text-[10px] text-text-2">
                        {TYPE_LABELS[type]}
                      </div>
                    </button>
                  ))}
              </div>
            </div>
          </div>

          {/* ── Fixed: Add annotation ── */}
          <div
            className="flex-shrink-0 px-2 pb-2"
            style={{ borderTop: '1px solid var(--color-border-base)' }}
          >
            <div
              className="popup-section px-1 pt-2 pb-1"
              style={{ animationDelay: '220ms' }}
            >
              <div className="px-2 mb-2">
                <SectionLabel>Add annotation</SectionLabel>
              </div>
              <div className="flex items-center gap-1.5 px-1 flex-wrap">
                {ANNOTATION_CONFIGS.map((ann) => (
                  <button
                    key={ann.value}
                    onClick={() => handleAnnotation(ann.value)}
                    title={`Drop a ${ann.label.toLowerCase()} pin on the canvas`}
                    className={cn(
                      'popup-item flex items-center gap-1.5 px-2.5 py-1',
                      'font-mono text-[10.5px] tracking-[0.02em]',
                      'rounded-full border cursor-pointer',
                      'transition-all duration-150',
                      ann.colorClass,
                      ann.hoverClass,
                    )}
                  >
                    {ann.icon}
                    {ann.label}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* ── Fixed footer ── */}
          <div
            className="flex-shrink-0 px-3 py-2 border-t border-border-base flex items-center justify-between font-mono text-[10px] text-text-3"
          >
            <span>Click canvas to place</span>
            <span className="flex items-center gap-1">
              <kbd
                className="inline-flex items-center px-1 py-0.5 rounded border border-border-base bg-surface text-text-3 font-mono text-[9px]"
              >
                ↑↓
              </kbd>
              {' '}nav
              <kbd
                className="ml-1 inline-flex items-center px-1 py-0.5 rounded border border-border-base bg-surface text-text-3 font-mono text-[9px]"
              >
                ↵
              </kbd>
              {' '}add
            </span>
          </div>
        </div>
      )}

      {/* ── New object name modal (replaces native prompt) ── */}
      {newObjectType && (
        <NewObjectModal
          open={true}
          onClose={() => setNewObjectType(null)}
          objectType={newObjectType}
          existingNames={objects.map((o) => o.name)}
          onSubmit={handleNewObjectSubmit}
        />
      )}
    </div>
  )
}
