import { useMemo, useState, useRef, useCallback, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { AppSidebar } from '../components/nav/AppSidebar'
import { PageToolbar } from '../components/nav/PageToolbar'
import { Button } from '../components/ui/Button'
import { Kbd } from '../components/ui/Kbd'
import { LevelBar } from '../components/ui/LevelBar'
import { SectionLabel } from '../components/ui/SectionLabel'
import { StatusPill } from '../components/ui/Pill'
import type { PillVariant } from '../components/ui/Pill'
import { PreviewCard } from '../components/common/PreviewCard'
import { Modal } from '../components/common/Modal'
import { NewDiagramModal } from '../components/diagram/NewDiagramModal'
import {
  useDiagrams,
  useDeleteDiagram,
  useUpdateDiagram,
} from '../hooks/use-diagrams'
import {
  usePacks,
  useCreatePack,
  useRenamePack,
  useDeletePack,
  useSetDiagramPack,
} from '../hooks/use-api'
import { useWorkspaceStore } from '../stores/workspace-store'
import { useWorkspaces } from '../hooks/use-api'
import type { DiagramPack, DiagramType } from '../types/model'
import { cn } from '../utils/cn'

// ─── Constants ───────────────────────────────────────────────────────────────

const C4_LEVEL: Record<string, { label: string; order: number; level: 1 | 2 | 3 | 4 }> = {
  system_landscape: { label: 'Level 1', order: 1, level: 1 },
  system_context:   { label: 'Level 1', order: 1, level: 1 },
  container:        { label: 'Level 2', order: 2, level: 2 },
  component:        { label: 'Level 3', order: 3, level: 3 },
  custom:           { label: 'Custom',  order: 9, level: 4 },
}

const TYPE_LABELS: Record<string, string> = {
  system_landscape: 'System Landscape',
  system_context:   'System Context',
  container:        'Container',
  component:        'Component',
  custom:           'Custom',
}

// Types in display order for grouped table
const ORDERED_TYPES: DiagramType[] = [
  'system_landscape',
  'system_context',
  'container',
  'component',
  'custom',
]

// Type → sidebar pack color
const TYPE_COLOR: Record<string, { folder: string; icon: string; well: string }> = {
  system_landscape: { folder: '#c084fc', icon: '#c084fc', well: 'bg-accent-purple-glow' },
  system_context:   { folder: '#c084fc', icon: '#c084fc', well: 'bg-accent-purple-glow' },
  container:        { folder: '#FF6B35', icon: '#FF6B35', well: 'bg-coral-glow' },
  component:        { folder: '#60a5fa', icon: '#60a5fa', well: 'bg-accent-blue-glow' },
  custom:           { folder: '#4ade80', icon: '#4ade80', well: 'bg-accent-green-glow' },
}

// Level → C4 filter sidebar
const LEVEL_ROWS: { level: 1 | 2 | 3 | 4; label: string; types: string[] }[] = [
  { level: 1, label: 'Level 1 · Landscape', types: ['system_landscape', 'system_context'] },
  { level: 2, label: 'Level 2 · Container',  types: ['container'] },
  { level: 3, label: 'Level 3 · Component',  types: ['component'] },
  { level: 4, label: 'Level 4 · Code',       types: ['custom'] },
]

// Folder color palette (swatches for create modal — UI-only, not persisted to backend)
// NOTE: The backend Pack model has no `color` field. Colors are derived
// deterministically from pack name at render time.
const FOLDER_COLORS = [
  { id: 'coral',  hex: '#FF6B35', label: 'Coral' },
  { id: 'purple', hex: '#c084fc', label: 'Purple' },
  { id: 'blue',   hex: '#60a5fa', label: 'Blue' },
  { id: 'green',  hex: '#4ade80', label: 'Green' },
  { id: 'amber',  hex: '#fbbf24', label: 'Amber' },
]

// ─── Helpers ─────────────────────────────────────────────────────────────────

function timeAgo(iso: string): string {
  const seconds = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (seconds < 60) return 'just now'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days}d ago`
  return new Date(iso).toLocaleDateString()
}

function diagramStatus(d: { draft_id: string | null }): Exclude<PillVariant, 'neutral'> {
  if (d.draft_id) return 'draft'
  return 'done'
}

function slugify(name: string): string {
  return name.toLowerCase().replace(/\s+/g, '-').replace(/[^a-z0-9-]/g, '')
}

/** Deterministic folder color from name hash → one of the 5 palette entries */
function folderColorFromName(name: string): string {
  let h = 0
  for (let i = 0; i < name.length; i++) {
    h = (h * 31 + name.charCodeAt(i)) >>> 0
  }
  return FOLDER_COLORS[h % FOLDER_COLORS.length]?.hex ?? '#FF6B35'
}

// ─── SVG icon components ──────────────────────────────────────────────────────

function TypeIcon({ type }: { type: string }) {
  const color = TYPE_COLOR[type]?.icon ?? '#71717a'
  const well = TYPE_COLOR[type]?.well ?? 'bg-surface'

  const svg = (() => {
    switch (type) {
      case 'container':
        return <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 9h6v6H9z"/></svg>
      case 'system_landscape':
      case 'system_context':
        return <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="4"/></svg>
      case 'component':
        return <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2"><rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/></svg>
      default:
        return <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>
    }
  })()

  return (
    <div className={cn('w-6 h-6 rounded-md border border-border-base flex items-center justify-center flex-shrink-0', well)}>
      {svg}
    </div>
  )
}

function FolderIcon({ color }: { color: string }) {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill={color + '33'} stroke={color} strokeWidth="1.5">
      <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
    </svg>
  )
}

function ChevronDown() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="m6 9 6 6 6-6"/>
    </svg>
  )
}

// Clean 14px Lucide-style action icons (stroke-width 1.5)

function IconMoreHorizontal() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
      <circle cx="5" cy="12" r="1.2"/><circle cx="12" cy="12" r="1.2"/><circle cx="19" cy="12" r="1.2"/>
    </svg>
  )
}

function IconPin({ filled }: { filled?: boolean }) {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill={filled ? '#FF6B35' : 'none'} stroke={filled ? '#FF6B35' : 'currentColor'} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 2L8 8H2l7 6-2.5 8L12 18l5.5 4L15 14l7-6h-6z"/>
    </svg>
  )
}

function IconTrash() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/>
    </svg>
  )
}

function IconFolderMove() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
      <path d="M12 11v6M9 14l3-3 3 3"/>
    </svg>
  )
}

function IconPencil() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
      <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
    </svg>
  )
}

function IconPlusSm() {
  return (
    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
      <path d="M12 5v14M5 12h14"/>
    </svg>
  )
}

// ─── Create Folder Modal ──────────────────────────────────────────────────────

function CreateFolderModal({
  open,
  onClose,
  onCreate,
  isPending,
}: {
  open: boolean
  onClose: () => void
  onCreate: (name: string) => void
  isPending: boolean
}) {
  const [name, setName] = useState('')
  const [selectedColor, setSelectedColor] = useState(FOLDER_COLORS[0].id)

  const resetAndClose = () => {
    setName('')
    setSelectedColor(FOLDER_COLORS[0].id)
    onClose()
  }

  const handleCreate = () => {
    const trimmed = name.trim()
    if (!trimmed) return
    onCreate(trimmed)
  }

  return (
    <Modal
      open={open}
      onClose={resetAndClose}
      title="Create folder"
      width={320}
      footer={
        <>
          <Button variant="ghost" onClick={resetAndClose}>Cancel</Button>
          <Button
            variant="primary"
            disabled={!name.trim() || isPending}
            onClick={handleCreate}
          >
            {isPending ? 'Creating…' : 'Create'}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div>
          <label className="block font-mono text-[10.5px] uppercase tracking-[0.07em] text-text-3 mb-1.5">
            Name
          </label>
          <input
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleCreate()
              if (e.key === 'Escape') resetAndClose()
            }}
            placeholder="e.g. Backend services"
            className="w-full bg-surface border border-border-base rounded-md px-3 py-2 text-[13px] text-text-base outline-none focus:border-border-hi placeholder:text-text-4 transition-colors"
          />
        </div>

        <div>
          <label className="block font-mono text-[10.5px] uppercase tracking-[0.07em] text-text-3 mb-2">
            Colour <span className="text-text-4 normal-case">(display only)</span>
          </label>
          <div className="flex items-center gap-2">
            {FOLDER_COLORS.map((c) => (
              <button
                key={c.id}
                title={c.label}
                onClick={() => setSelectedColor(c.id)}
                style={{ background: c.hex, ['--tw-ring-color' as string]: c.hex } as React.CSSProperties}
                className={cn(
                  'w-6 h-6 rounded-full transition-all duration-100',
                  selectedColor === c.id
                    ? 'ring-2 ring-offset-2 ring-offset-[#171717] scale-110'
                    : 'opacity-70 hover:opacity-100 hover:scale-105',
                )}
              />
            ))}
          </div>
        </div>
      </div>
    </Modal>
  )
}

// ─── Row context menu (3-dot) ─────────────────────────────────────────────────

interface RowMenuProps {
  packs: DiagramPack[]
  currentPackId: string | null
  isPinned: boolean
  diagramName: string
  onMoveToFolder: (packId: string | null) => void
  onTogglePin: () => void
  onDelete: () => void
  onRename?: () => void
}

// Approximate width of the submenu (px) — used for flip-direction calculation
const SUBMENU_WIDTH = 168

function RowMenu({
  packs,
  currentPackId,
  isPinned,
  diagramName,
  onMoveToFolder,
  onTogglePin,
  onDelete,
}: RowMenuProps) {
  const [open, setOpen] = useState(false)
  const [moveFolderOpen, setMoveFolderOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  // Flip state: true = submenu opens to the LEFT of the primary menu
  const [subMenuLeft, setSubMenuLeft] = useState(false)

  // Close on outside click
  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
        setMoveFolderOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  // Calculate submenu flip direction whenever the primary menu opens
  useEffect(() => {
    if (!open) return
    // Defer one tick so the menu has been rendered and getBoundingClientRect is valid
    const id = requestAnimationFrame(() => {
      if (!ref.current) return
      const rect = ref.current.getBoundingClientRect()
      setSubMenuLeft(rect.right + SUBMENU_WIDTH > window.innerWidth - 8)
    })
    return () => cancelAnimationFrame(id)
  }, [open])

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={(e) => { e.stopPropagation(); setOpen((v) => !v); setMoveFolderOpen(false) }}
        title="Actions"
        className="w-6 h-6 flex items-center justify-center rounded text-text-3 hover:text-text-base hover:bg-surface-hi transition-colors"
      >
        <IconMoreHorizontal />
      </button>

      {open && (
        <div
          className="absolute right-0 top-full mt-1 z-30 bg-panel border border-border-base rounded-md shadow-lg min-w-[160px] py-1"
          onClick={(e) => e.stopPropagation()}
        >
          {/* Move to folder */}
          <div className="relative">
            <button
              className="w-full text-left px-3 py-1.5 text-[12px] text-text-2 hover:bg-surface hover:text-text-base flex items-center gap-2 transition-colors"
              onClick={() => setMoveFolderOpen((v) => !v)}
            >
              <IconFolderMove />
              Move to folder
              <svg className="ml-auto" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="m9 6 6 6-6 6"/></svg>
            </button>

            {moveFolderOpen && (
              <div
                className={cn(
                  'absolute top-0 ml-1 z-30 bg-panel border border-border-base rounded-md shadow-lg min-w-[160px] py-1',
                  subMenuLeft ? 'right-full mr-1 ml-0' : 'left-full',
                )}
              >
                <button
                  className={cn(
                    'w-full text-left px-3 py-1.5 text-[12px] hover:bg-surface transition-colors flex items-center gap-2',
                    currentPackId === null ? 'text-coral font-medium' : 'text-text-2',
                  )}
                  onClick={() => { onMoveToFolder(null); setOpen(false); setMoveFolderOpen(false) }}
                >
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>
                  Unfiled
                </button>
                {packs.length > 0 && <div className="h-px bg-border-base mx-2 my-1" />}
                {packs.map((p) => {
                  const color = folderColorFromName(p.name)
                  return (
                    <button
                      key={p.id}
                      className={cn(
                        'w-full text-left px-3 py-1.5 text-[12px] hover:bg-surface transition-colors flex items-center gap-2',
                        currentPackId === p.id ? 'text-coral font-medium' : 'text-text-2',
                      )}
                      onClick={() => { onMoveToFolder(p.id); setOpen(false); setMoveFolderOpen(false) }}
                    >
                      <FolderIcon color={color} />
                      <span className="truncate">{p.name}</span>
                    </button>
                  )
                })}
                {packs.length === 0 && (
                  <div className="px-3 py-1.5 text-[11px] text-text-4 italic">No folders yet</div>
                )}
              </div>
            )}
          </div>

          {/* Pin toggle */}
          <button
            className="w-full text-left px-3 py-1.5 text-[12px] text-text-2 hover:bg-surface hover:text-text-base flex items-center gap-2 transition-colors"
            onClick={() => { onTogglePin(); setOpen(false) }}
          >
            <IconPin filled={isPinned} />
            {isPinned ? 'Unpin' : 'Pin'}
          </button>

          <div className="h-px bg-border-base mx-2 my-1" />

          {/* Delete */}
          <button
            className="w-full text-left px-3 py-1.5 text-[12px] text-text-2 hover:bg-surface hover:text-red-400 flex items-center gap-2 transition-colors"
            onClick={() => {
              if (confirm(`Delete "${diagramName}"?`)) {
                onDelete()
              }
              setOpen(false)
            }}
          >
            <IconTrash />
            Delete
          </button>
        </div>
      )}
    </div>
  )
}

// ─── Folder tree item (sidebar) ───────────────────────────────────────────────

interface FolderTreeItemProps {
  pack: DiagramPack
  count: number
  isActive: boolean
  isRenaming: boolean
  renameValue: string
  isAdmin: boolean
  isDragOver: boolean
  onClick: () => void
  onRenameStart: () => void
  onRenameChange: (v: string) => void
  onRenameCommit: () => void
  onRenameCancel: () => void
  onDelete: () => void
  onDragOver: (e: React.DragEvent) => void
  onDragLeave: () => void
  onDrop: (e: React.DragEvent) => void
}

function FolderTreeItem({
  pack,
  count,
  isActive,
  isRenaming,
  renameValue,
  isAdmin,
  isDragOver,
  onClick,
  onRenameStart,
  onRenameChange,
  onRenameCommit,
  onRenameCancel,
  onDelete,
  onDragOver,
  onDragLeave,
  onDrop,
}: FolderTreeItemProps) {
  const color = folderColorFromName(pack.name)
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!menuOpen) return
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [menuOpen])

  if (isRenaming) {
    return (
      <div className="flex items-center gap-1 px-2 py-1">
        <input
          autoFocus
          value={renameValue}
          onChange={(e) => onRenameChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') onRenameCommit()
            if (e.key === 'Escape') onRenameCancel()
          }}
          className="flex-1 bg-surface border border-border-base rounded px-1.5 py-0.5 text-[11.5px] outline-none focus:border-border-hi font-mono text-text-base"
        />
        <button onClick={onRenameCommit} className="text-[10px] text-text-3 hover:text-text-base px-1">Save</button>
        <button onClick={onRenameCancel} className="text-[10px] text-text-4 px-1">✕</button>
      </div>
    )
  }

  return (
    <div
      className={cn(
        'group flex items-center gap-2 px-2 py-1.5 rounded text-[12.5px] cursor-pointer transition-all duration-[100ms] select-none',
        isActive
          ? 'bg-coral-glow text-coral'
          : 'text-text-2 hover:bg-surface hover:text-text-base',
        isDragOver && 'ring-1 ring-coral/60 bg-coral-glow/60 scale-[1.02]',
      )}
      onClick={onClick}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
    >
      <FolderIcon color={color} />
      <span className="flex-1 truncate">{pack.name}</span>
      <span className="font-mono text-[10.5px] text-text-3">{count}</span>

      {isAdmin && (
        <div className="relative" ref={menuRef}>
          <button
            onClick={(e) => { e.stopPropagation(); setMenuOpen((v) => !v) }}
            className="opacity-0 group-hover:opacity-100 w-5 h-5 flex items-center justify-center rounded text-text-4 hover:text-text-2 hover:bg-surface-hi transition-all"
            title="Folder options"
          >
            <IconMoreHorizontal />
          </button>
          {menuOpen && (
            <div
              className="absolute right-0 top-full mt-1 z-30 bg-panel border border-border-base rounded-md shadow-lg min-w-[140px] py-1"
              onClick={(e) => e.stopPropagation()}
            >
              <button
                className="w-full text-left px-3 py-1.5 text-[12px] text-text-2 hover:bg-surface hover:text-text-base flex items-center gap-2 transition-colors"
                onClick={() => { onRenameStart(); setMenuOpen(false) }}
              >
                <IconPencil />
                Rename
              </button>
              <div className="h-px bg-border-base mx-2 my-1" />
              <button
                className="w-full text-left px-3 py-1.5 text-[12px] text-text-2 hover:bg-surface hover:text-red-400 flex items-center gap-2 transition-colors"
                onClick={() => {
                  if (confirm(`Delete folder "${pack.name}"? Diagrams will remain unfiled.`)) onDelete()
                  setMenuOpen(false)
                }}
              >
                <IconTrash />
                Delete folder
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ─── Main page ────────────────────────────────────────────────────────────────

export function DiagramsPage() {
  const { data: diagrams = [], isLoading } = useDiagrams()
  const deleteDiagram = useDeleteDiagram()
  const updateDiagram = useUpdateDiagram()
  const navigate = useNavigate()

  // Search / filter state
  const [search, setSearch] = useState('')
  const [selectedTypeFilter, setSelectedTypeFilter] = useState<string | null>(null)
  // null = all, '__type__' + type = filter by type, pack id = filter by folder
  const [selectedFolderFilter, setSelectedFolderFilter] = useState<string | null>(null)

  // View mode
  const [view, setView] = useState<'list' | 'grid'>('list')

  // Show/hide by-type grouping toggle
  const [showByType, setShowByType] = useState(true)

  // New diagram modal state
  const [createOpen, setCreateOpen] = useState(false)

  // Create folder modal
  const [showCreateFolder, setShowCreateFolder] = useState(false)

  // Pack renaming state
  const [renamingPack, setRenamingPack] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState('')

  // Drag state — tracks which folder is being hovered
  const [dragOverFolderId, setDragOverFolderId] = useState<string | null>(null)
  const dragDiagramId = useRef<string | null>(null)

  const wsId = useWorkspaceStore((s) => s.currentWorkspaceId)
  const { data: workspaces = [] } = useWorkspaces()
  const currentWs = workspaces.find((w) => w.id === wsId) ?? null
  const isAdmin = currentWs?.role === 'owner' || currentWs?.role === 'admin'

  const { data: packs = [] } = usePacks(wsId)
  const createPack = useCreatePack(wsId)
  const renamePack = useRenamePack(wsId)
  const deletePack = useDeletePack(wsId)
  const setDiagramPack = useSetDiagramPack()

  // ── Sorted packs ───────────────────────────────────────────────────────────
  const sortedPacks: DiagramPack[] = useMemo(
    () => [...packs].sort((a, b) => a.sort_order - b.sort_order || a.name.localeCompare(b.name)),
    [packs],
  )

  // ── Filtered + sorted diagrams ─────────────────────────────────────────────
  const filtered = useMemo(() => {
    let rows = diagrams

    if (search) {
      const q = search.toLowerCase()
      rows = rows.filter((d) => d.name.toLowerCase().includes(q))
    }

    if (selectedFolderFilter !== null) {
      rows = rows.filter((d) => d.pack_id === selectedFolderFilter)
    } else if (selectedTypeFilter) {
      const levelRow = LEVEL_ROWS.find((lr) => lr.types.includes(selectedTypeFilter))
      const matchTypes = levelRow ? levelRow.types : [selectedTypeFilter]
      rows = rows.filter((d) => matchTypes.includes(d.type))
    }

    return [...rows].sort(
      (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
    )
  }, [diagrams, search, selectedTypeFilter, selectedFolderFilter])

  // ── Counts per type (full, unfiltered — for sidebar) ──────────────────────
  const countByType = useMemo(() => {
    const map: Record<string, number> = {}
    for (const d of diagrams) {
      map[d.type] = (map[d.type] ?? 0) + 1
    }
    return map
  }, [diagrams])

  const countByLevel = useMemo(() => {
    return LEVEL_ROWS.map((lr) => ({
      ...lr,
      count: diagrams.filter((d) => lr.types.includes(d.type)).length,
    }))
  }, [diagrams])

  // ── Count per pack (real folders, unfiltered) ──────────────────────────────
  const countByPack = useMemo(() => {
    const map: Record<string, number> = {}
    for (const d of diagrams) {
      if (d.pack_id) map[d.pack_id] = (map[d.pack_id] ?? 0) + 1
    }
    return map
  }, [diagrams])

  // ── Pack handlers ──────────────────────────────────────────────────────────
  const handleCreatePack = useCallback((name: string) => {
    createPack.mutate(name, {
      onSuccess: () => setShowCreateFolder(false),
    })
  }, [createPack])

  const handleRenamePack = useCallback((packId: string) => {
    const name = renameValue.trim()
    if (!name) return
    renamePack.mutate({ packId, name })
    setRenamingPack(null)
    setRenameValue('')
  }, [renamePack, renameValue])

  // ── Drag-and-drop handlers ────────────────────────────────────────────────
  const handleDragStart = useCallback((diagramId: string) => {
    dragDiagramId.current = diagramId
  }, [])

  const handleDragOverFolder = useCallback((e: React.DragEvent, folderId: string) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
    setDragOverFolderId(folderId)
  }, [])

  const handleDragLeaveFolder = useCallback(() => {
    setDragOverFolderId(null)
  }, [])

  const handleDropOnFolder = useCallback((folderId: string) => {
    const diagramId = dragDiagramId.current
    if (diagramId) {
      setDiagramPack.mutate({ diagramId, packId: folderId })
    }
    dragDiagramId.current = null
    setDragOverFolderId(null)
  }, [setDiagramPack])

  // ── Header meta ──────────────────────────────────────────────────────────
  const headerTitle = (() => {
    if (selectedFolderFilter) {
      return packs.find((p) => p.id === selectedFolderFilter)?.name ?? 'Folder'
    }
    if (selectedTypeFilter) {
      return TYPE_LABELS[selectedTypeFilter] ?? 'Filtered'
    }
    return 'All Diagrams'
  })()

  const headerBreadcrumb = (() => {
    if (selectedFolderFilter) return `folders / ${headerTitle.toLowerCase()}`
    if (selectedTypeFilter) return `by type / ${selectedTypeFilter}`
    return 'all diagrams'
  })()

  const mostRecentUpdate = filtered[0]?.updated_at
  const metaLine = `${filtered.length} diagram${filtered.length !== 1 ? 's' : ''}${mostRecentUpdate ? ` · last updated ${timeAgo(mostRecentUpdate)}` : ''}`

  // ── Tree item helper ──────────────────────────────────────────────────────
  const treeItemCls = (active: boolean) =>
    cn(
      'flex items-center gap-2 px-2 py-1.5 rounded text-[12.5px] cursor-pointer transition-colors duration-[100ms]',
      active
        ? 'bg-coral-glow text-coral'
        : 'text-text-2 hover:bg-surface hover:text-text-base',
    )

  // ── Grouped table rows (by type) ──────────────────────────────────────────
  const grouped = useMemo(() => {
    return ORDERED_TYPES.map((type) => ({
      type,
      label: (TYPE_LABELS[type] ?? type).toUpperCase(),
      items: filtered.filter((d) => d.type === type),
    })).filter((g) => g.items.length > 0)
  }, [filtered])

  return (
    <div className="flex h-screen bg-bg text-text-base">
      <AppSidebar />
      <div className="flex-1 flex flex-col overflow-hidden">
        <PageToolbar breadcrumb={['Diagrams']} />

        {/* ── Two-column body ─────────────────────────────────────────── */}
        <div className="flex flex-1 overflow-hidden">

          {/* ── Folder sidebar ──────────────────────────────────────────── */}
          <aside className="w-[260px] flex-shrink-0 bg-panel border-r border-border-base flex flex-col overflow-hidden">

            {/* Sidebar header */}
            <div className="px-4 py-3 border-b border-border-base flex items-center justify-between flex-shrink-0">
              <div className="flex items-center gap-2 text-text-base">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                  <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
                </svg>
                <span className="text-[13px] font-medium">Diagrams</span>
              </div>
              <Button
                size="icon"
                variant="ghost"
                onClick={() => setCreateOpen(true)}
                title="New diagram"
              >
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M12 5v14M5 12h14"/>
                </svg>
              </Button>
            </div>

            {/* Sidebar scroll body */}
            <div className="flex-1 overflow-y-auto p-3 space-y-4">

              {/* All diagrams + Pinned quick links */}
              <div className="space-y-0.5">
                {/* All diagrams */}
                <div
                  className={treeItemCls(!selectedTypeFilter && !selectedFolderFilter && !search)}
                  onClick={() => { setSelectedTypeFilter(null); setSelectedFolderFilter(null) }}
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                    <rect x="3" y="3" width="18" height="18" rx="2"/>
                    <path d="M3 9h18M9 9v12"/>
                  </svg>
                  <span className="flex-1">All diagrams</span>
                  <span className="font-mono text-[10.5px] text-text-3">{diagrams.length}</span>
                </div>

                {/* Pinned */}
                <div
                  className={treeItemCls(selectedTypeFilter === '__pinned__')}
                  onClick={() => setSelectedTypeFilter(
                    selectedTypeFilter === '__pinned__' ? null : '__pinned__'
                  )}
                >
                  <IconPin filled={false} />
                  <span className="flex-1">Pinned</span>
                  <span className="font-mono text-[10.5px] text-text-3">
                    {diagrams.filter((d) => d.pinned).length}
                  </span>
                </div>
              </div>

              {/* ── Folders section (real workspace packs) ──────────────── */}
              <div>
                <div className="flex items-center justify-between px-2 mb-2">
                  <span className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-text-3">
                    Folders
                  </span>
                  <div className="flex items-center gap-1">
                    <span className="font-mono text-[10.5px] text-text-4">{sortedPacks.length}</span>
                    {isAdmin && (
                      <button
                        onClick={() => setShowCreateFolder(true)}
                        title="New folder"
                        className="w-5 h-5 flex items-center justify-center rounded text-text-4 hover:text-text-base hover:bg-surface-hi transition-colors ml-1"
                      >
                        <IconPlusSm />
                      </button>
                    )}
                  </div>
                </div>

                <div className="space-y-0.5">
                  {sortedPacks.map((pack) => {
                    const count = countByPack[pack.id] ?? 0
                    return (
                      <FolderTreeItem
                        key={pack.id}
                        pack={pack}
                        count={count}
                        isActive={selectedFolderFilter === pack.id}
                        isRenaming={renamingPack === pack.id}
                        renameValue={renameValue}
                        isAdmin={isAdmin}
                        isDragOver={dragOverFolderId === pack.id}
                        onClick={() => {
                          setSelectedFolderFilter(
                            selectedFolderFilter === pack.id ? null : pack.id,
                          )
                          setSelectedTypeFilter(null)
                        }}
                        onRenameStart={() => { setRenamingPack(pack.id); setRenameValue(pack.name) }}
                        onRenameChange={setRenameValue}
                        onRenameCommit={() => handleRenamePack(pack.id)}
                        onRenameCancel={() => { setRenamingPack(null); setRenameValue('') }}
                        onDelete={() => deletePack.mutate(pack.id)}
                        onDragOver={(e) => handleDragOverFolder(e, pack.id)}
                        onDragLeave={handleDragLeaveFolder}
                        onDrop={() => handleDropOnFolder(pack.id)}
                      />
                    )
                  })}

                  {sortedPacks.length === 0 && (
                    <div className="px-2 py-2 text-[11.5px] text-text-4 italic">
                      No folders yet
                      {isAdmin && (
                        <button
                          onClick={() => setShowCreateFolder(true)}
                          className="ml-1 text-text-3 hover:text-text-base underline underline-offset-2 transition-colors"
                        >
                          Create one
                        </button>
                      )}
                    </div>
                  )}
                </div>
              </div>

              {/* ── By type section ─────────────────────────────────────── */}
              <div>
                <button
                  onClick={() => setShowByType((v) => !v)}
                  className="flex items-center gap-1.5 px-2 mb-2 w-full group"
                >
                  <span className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-text-3">
                    By type
                  </span>
                  <svg
                    width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                    className={cn('text-text-4 transition-transform duration-150', showByType ? '' : '-rotate-90')}
                  >
                    <path d="m6 9 6 6 6-6"/>
                  </svg>
                </button>

                {showByType && (
                  <div className="space-y-0.5">
                    {ORDERED_TYPES.map((type) => {
                      const count = countByType[type] ?? 0
                      if (count === 0) return null
                      const color = TYPE_COLOR[type]?.folder ?? '#71717a'
                      const isActive = selectedTypeFilter === type && !selectedFolderFilter
                      return (
                        <div
                          key={type}
                          className={treeItemCls(isActive)}
                          onClick={() => {
                            setSelectedFolderFilter(null)
                            setSelectedTypeFilter(isActive ? null : type)
                          }}
                        >
                          <FolderIcon color={color} />
                          <span className="flex-1 truncate">{TYPE_LABELS[type] ?? type}</span>
                          <span className="font-mono text-[10.5px] text-text-3">{count}</span>
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>

              {/* ── C4 Level filter ──────────────────────────────────────── */}
              <div>
                <SectionLabel className="mb-2 px-2">C4 Level filter</SectionLabel>
                <div className="space-y-0.5">
                  {countByLevel.map(({ level, label, types, count }) => {
                    const isActive = types.some((t) => t === selectedTypeFilter) && !selectedFolderFilter
                    return (
                      <div
                        key={level}
                        className={treeItemCls(isActive)}
                        onClick={() => {
                          setSelectedFolderFilter(null)
                          if (isActive) {
                            setSelectedTypeFilter(null)
                          } else {
                            setSelectedTypeFilter(types[0])
                          }
                        }}
                      >
                        <LevelBar level={level} />
                        <span className="flex-1">{label}</span>
                        <span className="font-mono text-[10.5px] text-text-3">{count}</span>
                      </div>
                    )
                  })}
                </div>
              </div>
            </div>
          </aside>

          {/* ── Content area ────────────────────────────────────────────── */}
          <section className="flex-1 flex flex-col overflow-hidden">

            {/* Inner toolbar */}
            <div className="px-8 py-5 border-b border-border-base flex items-end justify-between flex-shrink-0 gap-4">
              <div>
                <div className="font-mono text-[11px] text-text-3">{headerBreadcrumb}</div>
                <h2 className="text-[22px] font-semibold tracking-tight text-text-base mt-1">{headerTitle}</h2>
                <div className="text-[12.5px] text-text-2 mt-1">{metaLine}</div>
              </div>

              <div className="flex items-center gap-2 flex-shrink-0">
                {/* Search input */}
                <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-md border border-border-base bg-surface w-48">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-text-3 flex-shrink-0">
                    <circle cx="11" cy="11" r="8"/>
                    <path d="m21 21-4.35-4.35"/>
                  </svg>
                  <input
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder="Search diagrams…"
                    className="bg-transparent outline-none text-[12.5px] text-text-base placeholder:text-text-4 w-full"
                  />
                </div>

                {/* Filters stub */}
                <Button
                  leftIcon={
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M3 6h18M7 12h10M10 18h4"/>
                    </svg>
                  }
                >
                  Filters
                </Button>

                {/* List / Grid view toggle */}
                <div className="flex items-center border border-border-base rounded-md overflow-hidden">
                  <button
                    onClick={() => setView('list')}
                    title="List view"
                    className={cn(
                      'p-1.5 transition-colors',
                      view === 'list'
                        ? 'bg-surface-hi text-text-base'
                        : 'bg-surface text-text-3 hover:text-text-base',
                    )}
                  >
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>
                    </svg>
                  </button>
                  <button
                    onClick={() => setView('grid')}
                    title="Grid view"
                    className={cn(
                      'p-1.5 transition-colors',
                      view === 'grid'
                        ? 'bg-surface-hi text-text-base'
                        : 'bg-surface text-text-3 hover:text-text-base',
                    )}
                  >
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/>
                      <rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/>
                    </svg>
                  </button>
                </div>

                {/* New diagram */}
                <Button
                  variant="primary"
                  onClick={() => setCreateOpen(true)}
                  leftIcon={
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                      <path d="M12 5v14M5 12h14"/>
                    </svg>
                  }
                >
                  New diagram
                </Button>
              </div>
            </div>

            {isLoading && (
              <div className="px-8 py-4 text-[12.5px] text-text-3">Loading…</div>
            )}

            {/* ── Folder empty state ─────────────────────────────────── */}
            {selectedFolderFilter && filtered.length === 0 && !isLoading && (
              <div
                className="mx-8 mt-8 border-2 border-dashed border-border-base rounded-xl p-10 flex flex-col items-center gap-2 text-center"
                onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = 'move' }}
                onDrop={() => {
                  const diagramId = dragDiagramId.current
                  if (diagramId) {
                    setDiagramPack.mutate({ diagramId, packId: selectedFolderFilter })
                  }
                  dragDiagramId.current = null
                }}
              >
                <FolderIcon color={folderColorFromName(packs.find((p) => p.id === selectedFolderFilter)?.name ?? '')} />
                <div className="text-[13px] text-text-3 mt-1">No diagrams in this folder</div>
                <div className="text-[11.5px] text-text-4">Drop diagrams here to add them</div>
              </div>
            )}

            {/* ── List view ─────────────────────────────────────────────── */}
            {view === 'list' && !isLoading && (filtered.length > 0 || !selectedFolderFilter) && (
              <div className="flex-1 overflow-y-auto">
                {/* Column header */}
                <div
                  className="sticky top-0 bg-panel z-10 px-8 py-2 grid gap-3 border-b border-border-base"
                  style={{ gridTemplateColumns: '1.5rem 2fr 1fr 0.7fr 1fr 7rem' }}
                >
                  <div />
                  {(['DIAGRAM', 'TYPE', 'LEVEL', 'UPDATED', 'STATUS'] as const).map((col) => (
                    <div key={col} className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-text-3">
                      {col}
                    </div>
                  ))}
                </div>

                {/* Empty state */}
                {grouped.length === 0 && !selectedFolderFilter && (
                  <div className="px-8 py-6 text-[12.5px] text-text-3 italic">
                    No diagrams match the current filter.
                  </div>
                )}

                {/* Grouped rows */}
                {grouped.map(({ type, label, items }) => (
                  <div key={type}>
                    {/* Group header */}
                    <div className="px-8 py-2 bg-surface border-b border-border-base flex items-center gap-2">
                      <ChevronDown />
                      <span className="font-mono text-[11.5px] tracking-[0.04em] uppercase text-text-2">
                        {label}
                      </span>
                      <span className="font-mono text-[10.5px] text-text-3 ml-1">· {items.length}</span>
                    </div>

                    {/* Rows */}
                    {items.map((d) => {
                      const level = C4_LEVEL[d.type]?.level ?? 4
                      const status = diagramStatus(d)
                      const slug = slugify(d.name)

                      return (
                        <div
                          key={d.id}
                          draggable
                          onDragStart={() => handleDragStart(d.id)}
                          className="grid gap-3 px-8 py-2.5 items-center border-b border-border-base cursor-pointer text-[13px] hover:bg-surface transition-colors duration-[80ms] group"
                          style={{ gridTemplateColumns: '1.5rem 2fr 1fr 0.7fr 1fr 7rem' }}
                          onClick={() => navigate(`/diagram/${d.id}`)}
                        >
                          {/* Icon well */}
                          <TypeIcon type={d.type} />

                          {/* Name */}
                          <div className="min-w-0">
                            <div className="text-[13.5px] font-medium text-text-base truncate">
                              {d.name}
                              {d.draft_id && (
                                <span className="font-mono text-[10px] text-text-3 ml-2">(modified)</span>
                              )}
                            </div>
                            <div className="font-mono text-[10.5px] text-text-3 truncate">
                              {slug}
                            </div>
                          </div>

                          {/* Type */}
                          <div className="text-[12px] text-text-2">{TYPE_LABELS[d.type] ?? d.type}</div>

                          {/* Level */}
                          <div>
                            <LevelBar level={level} />
                          </div>

                          {/* Updated */}
                          <div className="font-mono text-[11.5px] text-text-3">{timeAgo(d.updated_at)}</div>

                          {/* Status + row actions */}
                          <div className="flex items-center justify-end gap-1.5" onClick={(e) => e.stopPropagation()}>
                            <StatusPill status={status}>
                              {status === 'done' ? 'LIVE' : status.toUpperCase()}
                            </StatusPill>

                            {/* Pin toggle — hover-reveal */}
                            <button
                              onClick={() => updateDiagram.mutate({ id: d.id, pinned: !d.pinned })}
                              title={d.pinned ? 'Unpin' : 'Pin'}
                              className={cn(
                                'w-6 h-6 flex items-center justify-center rounded transition-all',
                                d.pinned
                                  ? 'text-coral opacity-100'
                                  : 'opacity-0 group-hover:opacity-100 text-text-3 hover:text-text-base hover:bg-surface-hi',
                              )}
                            >
                              <IconPin filled={d.pinned} />
                            </button>

                            {/* 3-dot row menu — hover-reveal */}
                            <div className="opacity-0 group-hover:opacity-100 transition-opacity">
                              <RowMenu
                                packs={packs}
                                currentPackId={d.pack_id}
                                isPinned={d.pinned}
                                diagramName={d.name}
                                onMoveToFolder={(packId) => setDiagramPack.mutate({ diagramId: d.id, packId })}
                                onTogglePin={() => updateDiagram.mutate({ id: d.id, pinned: !d.pinned })}
                                onDelete={() => deleteDiagram.mutate(d.id)}
                              />
                            </div>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                ))}
              </div>
            )}

            {/* ── Grid view ─────────────────────────────────────────────── */}
            {view === 'grid' && !isLoading && (
              <div className="flex-1 overflow-y-auto">
                <div className="grid grid-cols-3 gap-4 p-8">
                  {filtered.map((d) => {
                    const status = diagramStatus(d)
                    return (
                      <div
                        key={d.id}
                        draggable
                        onDragStart={() => handleDragStart(d.id)}
                        className="relative group"
                      >
                        <PreviewCard
                          name={d.name}
                          typeLabel={TYPE_LABELS[d.type] ?? d.type}
                          slug={slugify(d.name)}
                          updatedLabel={timeAgo(d.updated_at)}
                          status={status}
                          isModified={!!d.draft_id}
                          diagramId={d.id}
                          diagramType={d.type}
                          draftId={d.draft_id}
                          onClick={() => navigate(`/diagram/${d.id}`)}
                        />
                        {/* Card overlay actions */}
                        <div
                          className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-1"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <button
                            onClick={() => updateDiagram.mutate({ id: d.id, pinned: !d.pinned })}
                            title={d.pinned ? 'Unpin' : 'Pin'}
                            className={cn(
                              'w-6 h-6 flex items-center justify-center rounded bg-panel/80 backdrop-blur-sm border border-border-base transition-colors',
                              d.pinned ? 'text-coral' : 'text-text-3 hover:text-text-base',
                            )}
                          >
                            <IconPin filled={d.pinned} />
                          </button>
                          <RowMenu
                            packs={packs}
                            currentPackId={d.pack_id}
                            isPinned={d.pinned}
                            diagramName={d.name}
                            onMoveToFolder={(packId) => setDiagramPack.mutate({ diagramId: d.id, packId })}
                            onTogglePin={() => updateDiagram.mutate({ id: d.id, pinned: !d.pinned })}
                            onDelete={() => deleteDiagram.mutate(d.id)}
                          />
                        </div>
                      </div>
                    )
                  })}
                  {filtered.length === 0 && !selectedFolderFilter && (
                    <div className="col-span-3 text-[12.5px] text-text-3 italic py-6">
                      No diagrams match the current filter.
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* ── Bottom status strip ──────────────────────────────────── */}
            <div className="px-8 py-2 border-t border-border-base flex items-center justify-between flex-shrink-0">
              <span className="font-mono text-[11px] text-text-3">
                {filtered.length} total
                {selectedTypeFilter || selectedFolderFilter || search ? ` · ${filtered.length} filtered` : ''}
                {' '}· {diagrams.length} in workspace
              </span>
              <div className="flex items-center gap-1.5 font-mono text-[10.5px] text-text-3">
                <Kbd>↑↓</Kbd>
                <span>navigate</span>
                <Kbd>↵</Kbd>
                <span>open</span>
              </div>
            </div>
          </section>
        </div>
      </div>

      {/* ── Create folder modal ──────────────────────────────────────────── */}
      <CreateFolderModal
        open={showCreateFolder}
        onClose={() => setShowCreateFolder(false)}
        onCreate={handleCreatePack}
        isPending={createPack.isPending}
      />

      {/* ── New diagram modal ─────────────────────────────────────────────── */}
      <NewDiagramModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        defaultPackId={selectedFolderFilter}
        onCreated={(d) => navigate(`/diagram/${d.id}`)}
      />
    </div>
  )
}
