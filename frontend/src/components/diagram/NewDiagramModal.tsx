import { useEffect, useRef, useState } from 'react'
import { Button } from '../ui/Button'
import { SectionLabel } from '../ui/SectionLabel'
import { useCreateDiagram, type Diagram } from '../../hooks/use-diagrams'
import { usePacks } from '../../hooks/use-api'
import { useWorkspaceStore } from '../../stores/workspace-store'
import { cn } from '../../utils/cn'
import type { DiagramType } from '../../types/model'

// ─── Props ────────────────────────────────────────────────────────────────────

export interface NewDiagramModalProps {
  open: boolean
  onClose: () => void
  /** When opened from inside a folder, preselect that pack */
  defaultPackId?: string | null
  /** Called after successful creation so parent can navigate */
  onCreated?: (diagram: Diagram) => void
}

// ─── Diagram type metadata ────────────────────────────────────────────────────

interface TypeMeta {
  value: DiagramType
  label: string
  levelTag: string
  description: string
  color: string
  bgGlow: string
  borderActive: string
  icon: React.ReactNode
}

const TYPE_META: TypeMeta[] = [
  {
    value: 'system_landscape',
    label: 'System Landscape',
    levelTag: 'L1',
    description: 'High-level system view',
    color: '#c084fc',
    bgGlow: 'rgba(192,132,252,0.12)',
    borderActive: '#c084fc',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#c084fc" strokeWidth="1.8">
        <circle cx="12" cy="12" r="10" />
        <circle cx="12" cy="12" r="4" />
      </svg>
    ),
  },
  {
    value: 'system_context',
    label: 'System Context',
    levelTag: 'L1',
    description: 'Service and stakeholder scope',
    color: '#c084fc',
    bgGlow: 'rgba(192,132,252,0.12)',
    borderActive: '#c084fc',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#c084fc" strokeWidth="1.8">
        <circle cx="12" cy="12" r="10" />
        <path d="M8 12h8M12 8v8" />
      </svg>
    ),
  },
  {
    value: 'container',
    label: 'Container',
    levelTag: 'L2',
    description: 'Service and runtime architecture',
    color: '#FF6B35',
    bgGlow: 'rgba(255,107,53,0.12)',
    borderActive: '#FF6B35',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#FF6B35" strokeWidth="1.8">
        <rect x="3" y="3" width="18" height="18" rx="2" />
        <path d="M9 9h6v6H9z" />
      </svg>
    ),
  },
  {
    value: 'component',
    label: 'Component',
    levelTag: 'L3',
    description: 'Internal module structure',
    color: '#60a5fa',
    bgGlow: 'rgba(96,165,250,0.12)',
    borderActive: '#60a5fa',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#60a5fa" strokeWidth="1.8">
        <rect x="2" y="7" width="20" height="14" rx="2" />
        <path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16" />
      </svg>
    ),
  },
  {
    value: 'custom',
    label: 'Custom',
    levelTag: '—',
    description: 'Custom diagram',
    color: '#4ade80',
    bgGlow: 'rgba(74,222,128,0.12)',
    borderActive: '#4ade80',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#4ade80" strokeWidth="1.8">
        <path d="M12 2L2 7l10 5 10-5-10-5z" />
        <path d="M2 17l10 5 10-5" />
        <path d="M2 12l10 5 10-5" />
      </svg>
    ),
  },
]

// ─── NewDiagramModal ──────────────────────────────────────────────────────────

/**
 * Inner form — remounted each time the modal opens via `key` prop,
 * so all state is fresh without calling setState inside an effect.
 */
function NewDiagramForm({
  defaultPackId,
  onClose,
  onCreated,
}: {
  defaultPackId?: string | null
  onClose: () => void
  onCreated?: (diagram: Diagram) => void
}) {
  const [name, setName] = useState('')
  const [selectedType, setSelectedType] = useState<DiagramType>('system_landscape')
  const [selectedPackId, setSelectedPackId] = useState<string | null>(defaultPackId ?? null)

  const wsId = useWorkspaceStore((s) => s.currentWorkspaceId)
  const { data: packs = [] } = usePacks(wsId)
  const createDiagram = useCreateDiagram()

  const nameRef = useRef<HTMLInputElement>(null)

  // Auto-focus on mount (modal just opened)
  useEffect(() => {
    const t = setTimeout(() => nameRef.current?.focus(), 30)
    return () => clearTimeout(t)
  }, [])

  const handleCreate = () => {
    const trimmed = name.trim()
    if (!trimmed) return
    createDiagram.mutate(
      { name: trimmed, type: selectedType },
      {
        onSuccess: (diagram) => {
          onClose()
          onCreated?.(diagram)
        },
      },
    )
  }

  return (
    <>
      {/* Name input */}
      <div className="flex flex-col gap-1.5">
        <label className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-text-3">
          Name
        </label>
        <input
          ref={nameRef}
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') handleCreate()
          }}
          placeholder="Untitled diagram…"
          className="w-full bg-surface border border-border-base rounded-lg px-3 py-2 text-[13px] text-text-base placeholder:text-text-4 outline-none focus:border-border-hi transition-colors"
        />
      </div>

      {/* Type grid */}
      <div className="flex flex-col gap-1.5">
        <label className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-text-3">
          Type
        </label>
        <div className="grid grid-cols-2 gap-2">
          {TYPE_META.map((meta) => {
            const isSelected = selectedType === meta.value
            return (
              <button
                key={meta.value}
                onClick={() => setSelectedType(meta.value)}
                className={cn(
                  'flex items-start gap-3 p-3 rounded-lg border text-left transition-all duration-[120ms]',
                  isSelected
                    ? 'border-opacity-80'
                    : 'border-border-base bg-surface hover:border-border-hi hover:bg-surface-hi',
                )}
                style={
                  isSelected
                    ? {
                        borderColor: meta.borderActive,
                        background: meta.bgGlow,
                      }
                    : undefined
                }
              >
                <div className="mt-0.5 flex-shrink-0">{meta.icon}</div>
                <div className="min-w-0">
                  <div className="flex items-center gap-1.5 mb-0.5">
                    <span
                      className="font-mono text-[9.5px] px-1 py-px rounded"
                      style={
                        isSelected
                          ? { color: meta.color, background: 'rgba(0,0,0,0.3)' }
                          : { color: 'var(--color-text-3)', background: 'var(--color-surface-hi)' }
                      }
                    >
                      {meta.levelTag}
                    </span>
                  </div>
                  <div
                    className="text-[12.5px] font-medium leading-tight"
                    style={{ color: isSelected ? meta.color : 'var(--color-text-base)' }}
                  >
                    {meta.label}
                  </div>
                  <div className="font-mono text-[10.5px] text-text-3 mt-0.5 leading-tight">
                    {meta.description}
                  </div>
                </div>
              </button>
            )
          })}
        </div>
      </div>

      {/* Folder select — only when packs exist */}
      {packs.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <label className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-text-3">
            Folder
          </label>
          <select
            value={selectedPackId ?? ''}
            onChange={(e) => setSelectedPackId(e.target.value || null)}
            className="w-full bg-surface border border-border-base rounded-lg px-3 py-2 text-[13px] text-text-base outline-none focus:border-border-hi transition-colors"
          >
            <option value="">No folder</option>
            {packs.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>
      )}

      {/* Footer */}
      <div className="flex items-center justify-end gap-2 pt-1 border-t border-border-base">
        <Button variant="ghost" onClick={onClose}>
          Cancel
        </Button>
        <Button
          variant="primary"
          onClick={handleCreate}
          disabled={!name.trim() || createDiagram.isPending}
        >
          {createDiagram.isPending ? 'Creating…' : 'Create diagram'}
        </Button>
      </div>
    </>
  )
}

export function NewDiagramModal({ open, onClose, defaultPackId, onCreated }: NewDiagramModalProps) {
  // Escape key to close
  useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [open, onClose])

  if (!open) return null

  return (
    /* Backdrop */
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      {/* Panel — key forces full remount so form state resets each open */}
      <div
        key="modal-panel"
        className="relative bg-panel border border-border-base rounded-xl shadow-popup w-[440px] p-6 flex flex-col gap-5"
        style={{ animation: 'modal-scale-in 0.18s cubic-bezier(0.16,1,0.3,1) forwards' }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between">
          <SectionLabel>Create diagram</SectionLabel>
          <button
            onClick={onClose}
            className="w-6 h-6 rounded flex items-center justify-center text-text-3 hover:text-text-base hover:bg-surface transition-colors"
            aria-label="Close"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M18 6 6 18M6 6l12 12" />
            </svg>
          </button>
        </div>

        <NewDiagramForm
          defaultPackId={defaultPackId}
          onClose={onClose}
          onCreated={onCreated}
        />
      </div>
    </div>
  )
}
