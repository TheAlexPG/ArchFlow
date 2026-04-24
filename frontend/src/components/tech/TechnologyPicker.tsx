import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useWorkspaceStore } from '../../stores/workspace-store'
import { useTechnologies } from '../../hooks/use-api'
import type { TechCategory, Technology } from '../../types/model'
import { cn } from '../../utils/cn'
import { TechBadge } from './TechBadge'
import { TechIcon } from './TechIcon'
import { CustomTechModal } from './CustomTechModal'

export type PickerMode =
  | { multi: true; value: string[]; onChange: (ids: string[]) => void }
  | { multi: false; value: string | null; onChange: (id: string | null) => void }

export interface TechnologyPickerProps {
  /** Single- or multi-select, distinguished at the type level. */
  mode: PickerMode
  /** Restrict results to a single category (e.g. `protocol` for edge pickers). */
  restrictCategory?: TechCategory
  placeholder?: string
  className?: string
  /** Disable the "+ Create custom" footer — useful for protocol pickers. */
  allowCreateCustom?: boolean
}

const CATEGORY_ORDER: TechCategory[] = [
  'language',
  'framework',
  'database',
  'cloud',
  'saas',
  'tool',
  'protocol',
  'other',
]

const CATEGORY_LABEL: Record<TechCategory, string> = {
  language: 'Languages',
  framework: 'Frameworks',
  database: 'Databases',
  cloud: 'Cloud',
  saas: 'SaaS',
  tool: 'Tools',
  protocol: 'Protocols',
  other: 'Other',
}

/**
 * Combobox for picking one or many technologies from the catalog.
 * The anchor renders selected items as `<TechBadge>`s (multi) or a single row
 * with icon + name (single). Click opens a portal dropdown with fuzzy search
 * and category sections. "+ Create custom" opens the CustomTechModal.
 */
export function TechnologyPicker({
  mode,
  restrictCategory,
  placeholder = 'Add technology…',
  className,
  allowCreateCustom = true,
}: TechnologyPickerProps) {
  const workspaceId = useWorkspaceStore((s) => s.currentWorkspaceId)
  const { data: catalog = [] } = useTechnologies(workspaceId, {
    category: restrictCategory,
  })

  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [modalOpen, setModalOpen] = useState(false)
  const [anchorRect, setAnchorRect] = useState<DOMRect | null>(null)
  const anchorRef = useRef<HTMLDivElement | null>(null)
  const inputRef = useRef<HTMLInputElement | null>(null)

  const selectedIds = useMemo(
    () => (mode.multi ? mode.value : mode.value ? [mode.value] : []),
    [mode],
  )
  const selectedTech = useMemo(
    () =>
      selectedIds
        .map((id) => catalog.find((t) => t.id === id))
        .filter((t): t is Technology => Boolean(t)),
    [selectedIds, catalog],
  )

  // Repositioning: recompute the anchor rect whenever we open + on scroll /
  // resize while open. Keeps the dropdown glued to its input.
  useEffect(() => {
    if (!open) return
    const update = () => {
      if (anchorRef.current) setAnchorRect(anchorRef.current.getBoundingClientRect())
    }
    update()
    window.addEventListener('scroll', update, true)
    window.addEventListener('resize', update)
    return () => {
      window.removeEventListener('scroll', update, true)
      window.removeEventListener('resize', update)
    }
  }, [open])

  // Click-outside closes the popup.
  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      const target = e.target as Node
      if (anchorRef.current?.contains(target)) return
      const popup = document.getElementById('tech-picker-popup')
      if (popup?.contains(target)) return
      setOpen(false)
    }
    window.addEventListener('mousedown', onDown)
    return () => window.removeEventListener('mousedown', onDown)
  }, [open])

  // Focus the search input on open so typing feels instant.
  useEffect(() => {
    if (open) requestAnimationFrame(() => inputRef.current?.focus())
  }, [open])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return catalog
    return catalog.filter((t) => {
      if (t.name.toLowerCase().includes(q)) return true
      if (t.slug.toLowerCase().includes(q)) return true
      return t.aliases?.some((a) => a.toLowerCase().includes(q)) ?? false
    })
  }, [catalog, query])

  const grouped = useMemo(() => {
    const map = new Map<TechCategory, Technology[]>()
    for (const t of filtered) {
      if (selectedIds.includes(t.id) && mode.multi) continue
      const arr = map.get(t.category) ?? []
      arr.push(t)
      map.set(t.category, arr)
    }
    return CATEGORY_ORDER.map((c) => ({
      category: c,
      items: (map.get(c) ?? []).sort((a, b) => a.name.localeCompare(b.name)),
    })).filter((g) => g.items.length > 0)
  }, [filtered, selectedIds, mode.multi])

  const handlePick = (tech: Technology) => {
    if (mode.multi) {
      if (selectedIds.includes(tech.id)) return
      mode.onChange([...mode.value, tech.id])
      setQuery('')
      // Stay open for further multi-picks.
      inputRef.current?.focus()
    } else {
      mode.onChange(tech.id)
      setOpen(false)
    }
  }

  const handleRemove = (id: string) => {
    if (mode.multi) {
      mode.onChange(mode.value.filter((x) => x !== id))
    } else {
      mode.onChange(null)
    }
  }

  const handleCreated = (tech: Technology) => {
    setModalOpen(false)
    handlePick(tech)
  }

  // Popup coordinates. Prefer to open below the anchor; flip above when not
  // enough room. Width mirrors the anchor so it feels attached.
  const popupStyle = useMemo((): React.CSSProperties | undefined => {
    if (!anchorRect) return undefined
    const maxHeight = 360
    const marginPx = 6
    const below = window.innerHeight - anchorRect.bottom
    const openUp = below < maxHeight + 24 && anchorRect.top > below
    const top = openUp
      ? Math.max(16, anchorRect.top - maxHeight - marginPx)
      : anchorRect.bottom + marginPx
    return {
      position: 'fixed',
      top,
      left: anchorRect.left,
      width: Math.max(anchorRect.width, 280),
      maxHeight,
      zIndex: 120,
    }
  }, [anchorRect])

  return (
    <div className={cn('relative', className)}>
      <div
        ref={anchorRef}
        onClick={() => setOpen((v) => !v)}
        className={cn(
          'min-h-[34px] w-full rounded-md border bg-surface',
          'flex flex-wrap items-center gap-[5px] px-2 py-[5px]',
          'cursor-text transition-colors',
          open ? 'border-coral' : 'border-border-base hover:border-border-hi',
        )}
      >
        {mode.multi
          ? selectedTech.map((t) => (
              <TechBadge
                key={t.id}
                technology={t}
                onRemove={() => handleRemove(t.id)}
              />
            ))
          : selectedTech[0] && (
              <span className="inline-flex items-center gap-[6px] font-mono text-[11px] text-text-base">
                <TechIcon technology={selectedTech[0]} size={14} />
                {selectedTech[0].name}
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation()
                    handleRemove(selectedTech[0].id)
                  }}
                  className="text-text-4 hover:text-text-base ml-1"
                >
                  ×
                </button>
              </span>
            )}
        {(!mode.multi ? !selectedTech[0] : true) && (
          <input
            className={cn(
              'flex-1 bg-transparent outline-none',
              'font-mono text-[11.5px] text-text-base placeholder:text-text-4',
              'min-w-[80px]',
            )}
            placeholder={selectedTech.length ? '' : placeholder}
            value={open ? query : ''}
            onFocus={() => setOpen(true)}
            onChange={(e) => {
              setOpen(true)
              setQuery(e.target.value)
            }}
            onKeyDown={(e) => {
              if (e.key === 'Escape') setOpen(false)
              if (e.key === 'Backspace' && !query && mode.multi && selectedTech.length) {
                handleRemove(selectedTech[selectedTech.length - 1].id)
              }
            }}
            ref={(el) => {
              if (el) inputRef.current = el
            }}
          />
        )}
      </div>

      {open &&
        anchorRect &&
        createPortal(
          <div
            id="tech-picker-popup"
            style={popupStyle}
            className={cn(
              'bg-panel border border-border-base rounded-md shadow-popup',
              'flex flex-col overflow-hidden',
              'animate-[popup-in_0.22s_cubic-bezier(0.16,1,0.3,1)_forwards]',
            )}
          >
            <div className="flex-1 overflow-y-auto">
              {grouped.length === 0 ? (
                <div className="px-3 py-6 font-mono text-[11px] text-text-3 text-center">
                  No matches. {allowCreateCustom ? 'Create a custom tech instead?' : null}
                </div>
              ) : (
                grouped.map((g) => (
                  <div key={g.category}>
                    <div className="font-mono text-[9.5px] uppercase tracking-[0.08em] text-text-3 px-3 pt-2 pb-1">
                      {CATEGORY_LABEL[g.category]}
                    </div>
                    {g.items.slice(0, 40).map((t) => (
                      <button
                        key={t.id}
                        type="button"
                        onClick={() => handlePick(t)}
                        className={cn(
                          'w-full text-left flex items-center gap-2 px-3 py-1.5',
                          'hover:bg-surface-hi focus-visible:bg-surface-hi outline-none',
                          'text-[12px] text-text-base',
                        )}
                      >
                        <TechIcon technology={t} size={16} />
                        <span className="flex-1 truncate">{t.name}</span>
                        <span className="font-mono text-[10px] text-text-3 truncate max-w-[120px]">
                          {t.slug}
                        </span>
                      </button>
                    ))}
                  </div>
                ))
              )}
            </div>
            {allowCreateCustom && (
              <button
                type="button"
                onClick={() => {
                  setOpen(false)
                  setModalOpen(true)
                }}
                className={cn(
                  'border-t border-border-base px-3 py-2 text-left',
                  'font-mono text-[11px] text-coral hover:bg-coral-glow',
                  'flex items-center gap-2',
                )}
              >
                <span className="text-[14px] leading-none">+</span>
                Create custom technology
              </button>
            )}
          </div>,
          document.body,
        )}

      <CustomTechModal
        open={modalOpen}
        initialCategory={restrictCategory}
        initialName={query}
        onClose={() => setModalOpen(false)}
        onCreated={handleCreated}
      />
    </div>
  )
}
