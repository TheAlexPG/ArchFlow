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
  mode: PickerMode
  /** Restrict results to a single category (e.g. `protocol`). */
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
 *
 * Multi mode always renders selected badges above a dedicated
 * "+ Add another technology" trigger, so the "you can pick several"
 * affordance is visually obvious. Single mode shows the current pick (or
 * a prompt) in the same spot.
 *
 * The popup stops propagation on its own `mousedown` so the outside-close
 * listener doesn't fire before the child buttons' `click` resolves — a
 * prior version got that wrong and clicks silently did nothing.
 */
export function TechnologyPicker({
  mode,
  restrictCategory,
  placeholder,
  className,
  allowCreateCustom = true,
}: TechnologyPickerProps) {
  const workspaceId = useWorkspaceStore((s) => s.currentWorkspaceId)
  const { data: catalog = [] } = useTechnologies(workspaceId, {
    category: restrictCategory,
  })

  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [activeIdx, setActiveIdx] = useState(0)
  const [modalOpen, setModalOpen] = useState(false)
  const [anchorRect, setAnchorRect] = useState<DOMRect | null>(null)
  const anchorRef = useRef<HTMLDivElement | null>(null)
  const popupRef = useRef<HTMLDivElement | null>(null)
  const inputRef = useRef<HTMLInputElement | null>(null)

  const selectedIds = mode.multi
    ? mode.value
    : mode.value
      ? [mode.value]
      : []
  const selectedTech = useMemo(
    () =>
      selectedIds
        .map((id) => catalog.find((t) => t.id === id))
        .filter((t): t is Technology => Boolean(t)),
    [selectedIds, catalog],
  )

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

  useEffect(() => {
    if (!open) return
    // Ref-based — each picker identifies its own popup, so multiple pickers
    // on the page don't race on `document.getElementById`.
    const onDown = (e: MouseEvent) => {
      const target = e.target as Node
      if (anchorRef.current?.contains(target)) return
      if (popupRef.current?.contains(target)) return
      setOpen(false)
    }
    window.addEventListener('mousedown', onDown)
    return () => window.removeEventListener('mousedown', onDown)
  }, [open])

  useEffect(() => {
    if (open) requestAnimationFrame(() => inputRef.current?.focus())
  }, [open])

  useEffect(() => {
    setActiveIdx(0)
  }, [query, open])

  const flatVisible = useMemo(() => {
    const q = query.trim().toLowerCase()
    const hide = new Set(mode.multi ? selectedIds : [])
    return catalog
      .filter((t) => !hide.has(t.id))
      .filter((t) => {
        if (!q) return true
        if (t.name.toLowerCase().includes(q)) return true
        if (t.slug.toLowerCase().includes(q)) return true
        return t.aliases?.some((a) => a.toLowerCase().includes(q)) ?? false
      })
  }, [catalog, query, selectedIds, mode.multi])

  const grouped = useMemo(() => {
    const map = new Map<TechCategory, Technology[]>()
    for (const t of flatVisible) {
      const arr = map.get(t.category) ?? []
      arr.push(t)
      map.set(t.category, arr)
    }
    return CATEGORY_ORDER.map((c) => ({
      category: c,
      items: (map.get(c) ?? []).sort((a, b) => a.name.localeCompare(b.name)),
    })).filter((g) => g.items.length > 0)
  }, [flatVisible])

  const handlePick = (tech: Technology) => {
    if (mode.multi) {
      if (mode.value.includes(tech.id)) return
      mode.onChange([...mode.value, tech.id])
      setQuery('')
      requestAnimationFrame(() => inputRef.current?.focus())
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

  const handleKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Escape') {
      e.preventDefault()
      setOpen(false)
      return
    }
    if (e.key === 'Enter') {
      e.preventDefault()
      const pick = flatVisible[activeIdx] ?? flatVisible[0]
      if (pick) handlePick(pick)
      return
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActiveIdx((i) => Math.min(i + 1, flatVisible.length - 1))
      return
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActiveIdx((i) => Math.max(i - 1, 0))
      return
    }
    if (e.key === 'Backspace' && !query && mode.multi && selectedTech.length) {
      handleRemove(selectedTech[selectedTech.length - 1].id)
    }
  }

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

  const effectivePlaceholder =
    placeholder ?? (mode.multi ? 'Search technology…' : 'Pick a technology…')

  const triggerLabel = mode.multi
    ? selectedTech.length > 0
      ? 'Add another technology'
      : 'Add technology'
    : selectedTech[0]
      ? 'Change technology'
      : 'Pick a technology'

  return (
    <div className={cn('flex flex-col gap-2', className)}>
      {/* Selected badges — always above the trigger in multi mode so the
          "you can stack several" affordance is visible before the user
          even opens the dropdown. */}
      {mode.multi && selectedTech.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {selectedTech.map((t) => (
            <TechBadge
              key={t.id}
              technology={t}
              size="md"
              onRemove={() => handleRemove(t.id)}
            />
          ))}
        </div>
      )}

      {!mode.multi && selectedTech[0] && (
        <div className="flex items-center">
          <TechBadge
            technology={selectedTech[0]}
            size="md"
            onRemove={() => handleRemove(selectedTech[0].id)}
          />
        </div>
      )}

      {/* Trigger button — explicit "click to add" instead of a free-text
          input, so the affordance matches what the popup actually does. */}
      <div ref={anchorRef}>
        <button
          type="button"
          onClick={() => setOpen(true)}
          className={cn(
            'w-full flex items-center gap-2 px-2.5 py-[7px]',
            'rounded-md border bg-surface',
            'font-mono text-[11.5px] leading-none text-left transition-colors',
            open
              ? 'border-coral text-text-base'
              : 'border-dashed border-border-hi text-text-3 hover:border-coral hover:text-text-base',
          )}
        >
          <span className="text-[14px] leading-none">+</span>
          <span>{triggerLabel}</span>
        </button>
      </div>

      {open &&
        anchorRect &&
        createPortal(
          <div
            ref={popupRef}
            style={popupStyle}
            className={cn(
              'bg-panel border border-border-base rounded-md shadow-popup',
              'flex flex-col overflow-hidden',
              'animate-[popup-in_0.22s_cubic-bezier(0.16,1,0.3,1)_forwards]',
            )}
            // Stop the outside-close listener from firing off a bubbled
            // mousedown before child button clicks resolve.
            onMouseDown={(e) => e.stopPropagation()}
          >
            <div className="p-2 border-b border-border-base">
              <input
                ref={inputRef}
                className={cn(
                  'w-full bg-surface border border-border-base rounded px-2 py-1.5',
                  'font-mono text-[11.5px] text-text-base placeholder:text-text-4',
                  'outline-none focus:border-coral',
                )}
                placeholder={effectivePlaceholder}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={handleKey}
              />
              {mode.multi && selectedTech.length > 0 && (
                <div className="mt-2 font-mono text-[9.5px] text-text-3 uppercase tracking-[0.06em]">
                  {selectedTech.length} selected · keep picking to stack more
                </div>
              )}
            </div>

            <div className="flex-1 overflow-y-auto">
              {grouped.length === 0 ? (
                <div className="px-3 py-6 font-mono text-[11px] text-text-3 text-center">
                  No matches.{' '}
                  {allowCreateCustom ? 'Create a custom tech instead?' : null}
                </div>
              ) : (
                grouped.map((g) => (
                  <div key={g.category}>
                    <div className="font-mono text-[9.5px] uppercase tracking-[0.08em] text-text-3 px-3 pt-2 pb-1">
                      {CATEGORY_LABEL[g.category]}
                    </div>
                    {g.items.slice(0, 40).map((t) => {
                      const flatIdx = flatVisible.indexOf(t)
                      const isActive = flatIdx === activeIdx
                      return (
                        <button
                          key={t.id}
                          type="button"
                          onMouseEnter={() => setActiveIdx(flatIdx)}
                          onClick={() => handlePick(t)}
                          className={cn(
                            'w-full text-left flex items-center gap-2 px-3 py-1.5',
                            'outline-none text-[12px] text-text-base',
                            isActive ? 'bg-surface-hi' : 'hover:bg-surface-hi',
                          )}
                        >
                          <TechIcon technology={t} size={16} />
                          <span className="flex-1 truncate">{t.name}</span>
                          <span className="font-mono text-[10px] text-text-3 truncate max-w-[120px]">
                            {t.slug}
                          </span>
                        </button>
                      )
                    })}
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
