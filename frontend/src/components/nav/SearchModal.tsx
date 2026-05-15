import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useObjects, useTechnologies } from '../../hooks/use-api'
import { useDiagrams } from '../../hooks/use-diagrams'
import { useWorkspaceStore } from '../../stores/workspace-store'
import { TYPE_ICONS } from '../canvas/node-utils'
import { TechIcon } from '../tech'
import type { ObjectType } from '../../types/model'

interface SearchModalProps {
  open: boolean
  onClose: () => void
}

export function SearchModal({ open, onClose }: SearchModalProps) {
  const [query, setQuery] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)
  const navigate = useNavigate()
  const { data: objects = [] } = useObjects()
  const { data: diagrams = [] } = useDiagrams()
  const workspaceId = useWorkspaceStore((s) => s.currentWorkspaceId)
  const { data: catalog = [] } = useTechnologies(workspaceId)
  const catalogMap = useMemo(() => new Map(catalog.map((t) => [t.id, t])), [catalog])

  useEffect(() => {
    if (open) {
      setTimeout(() => inputRef.current?.focus(), 50)
    }
  }, [open])

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        if (open) onClose()
        else onClose() // parent toggles
      }
      if (e.key === 'Escape' && open) onClose()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [open, onClose])

  if (!open) return null

  const q = query.toLowerCase()
  const matchesTech = (ids: string[] | null | undefined) => {
    if (!ids || ids.length === 0) return false
    for (const id of ids) {
      const t = catalogMap.get(id)
      if (!t) continue
      if (t.name.toLowerCase().includes(q)) return true
      if (t.slug.toLowerCase().includes(q)) return true
      if (t.aliases?.some((a) => a.toLowerCase().includes(q))) return true
    }
    return false
  }
  const filteredObjects = q
    ? objects.filter(
        (o) =>
          o.name.toLowerCase().includes(q) ||
          o.description?.toLowerCase().includes(q) ||
          matchesTech(o.technology_ids),
      )
    : []
  const filteredDiagrams = q
    ? diagrams.filter((d) => d.name.toLowerCase().includes(q))
    : diagrams.slice(0, 5)

  return (
    <div
      className="fixed inset-0 z-[100] flex items-start justify-center bg-black/50 px-4 pt-[120px] backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-[500px] max-w-full max-h-[400px] overflow-hidden rounded-xl border border-border-base bg-panel text-text-base shadow-popup"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="border-b border-border-base p-3">
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search objects, diagrams..."
            className="w-full bg-transparent text-sm text-text-base placeholder:text-text-4 outline-none"
          />
        </div>
        <div className="max-h-[320px] overflow-auto">
          {filteredDiagrams.length > 0 && (
            <div className="py-2">
              <div className="px-4 py-1 text-[10px] uppercase tracking-[0.08em] text-text-3">
                Diagrams
              </div>
              {filteredDiagrams.map((d) => (
                <button
                  key={d.id}
                  type="button"
                  onClick={() => { navigate(`/diagram/${d.id}`); onClose() }}
                  className="flex w-full cursor-pointer items-center gap-2 px-4 py-2 text-left text-[13px] text-text-base transition-colors hover:bg-surface-hi focus-visible:bg-surface-hi focus-visible:outline-none"
                >
                  <span className="text-text-3">▦</span>
                  <span className="truncate">{d.name}</span>
                </button>
              ))}
            </div>
          )}
          {filteredObjects.length > 0 && (
            <div className="py-2">
              <div className="px-4 py-1 text-[10px] uppercase tracking-[0.08em] text-text-3">
                Objects
              </div>
              {filteredObjects.slice(0, 10).map((o) => (
                <button
                  key={o.id}
                  type="button"
                  onClick={() => { onClose() }}
                  className="flex w-full cursor-pointer items-center gap-2 px-4 py-2 text-left text-[13px] text-text-base transition-colors hover:bg-surface-hi focus-visible:bg-surface-hi focus-visible:outline-none"
                >
                  <span className="text-text-3">{TYPE_ICONS[o.type as ObjectType]}</span>
                  <span className="truncate">{o.name}</span>
                  {(() => {
                    const techs = (o.technology_ids ?? [])
                      .map((id) => catalogMap.get(id))
                      .filter((t): t is NonNullable<typeof t> => Boolean(t))
                    if (techs.length === 0) return null
                    return (
                      <span className="ml-1 inline-flex items-center gap-1">
                        {techs.slice(0, 3).map((t) => (
                          <TechIcon key={t.id} technology={t} size={12} />
                        ))}
                      </span>
                    )
                  })()}
                </button>
              ))}
            </div>
          )}
          {query && filteredObjects.length === 0 && filteredDiagrams.length === 0 && (
            <div className="px-6 py-7 text-center text-[13px] text-text-3">
              No results for &quot;{query}&quot;
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
