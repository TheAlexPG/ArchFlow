import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useObjects } from '../../hooks/use-api'
import { useDiagrams } from '../../hooks/use-diagrams'
import { TYPE_ICONS } from '../canvas/node-utils'
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

  useEffect(() => {
    if (open) {
      setQuery('')
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
  const filteredObjects = q
    ? objects.filter(
        (o) =>
          o.name.toLowerCase().includes(q) ||
          o.description?.toLowerCase().includes(q) ||
          // TODO(tech-catalog): match by resolved catalog name/aliases (M7).
          o.technology_ids?.some((t) => t.toLowerCase().includes(q)),
      )
    : []
  const filteredDiagrams = q
    ? diagrams.filter((d) => d.name.toLowerCase().includes(q))
    : diagrams.slice(0, 5)

  return (
    <div
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 100,
        display: 'flex', alignItems: 'flex-start', justifyContent: 'center', paddingTop: 120,
      }}
      onClick={onClose}
    >
      <div
        style={{
          background: '#171717', border: '1px solid #333', borderRadius: 12,
          width: 500, maxHeight: 400, overflow: 'hidden',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{ padding: 12, borderBottom: '1px solid #262626' }}>
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search objects, diagrams..."
            style={{
              width: '100%', background: 'transparent', border: 'none', outline: 'none',
              color: '#f5f5f5', fontSize: 14, boxSizing: 'border-box',
            }}
          />
        </div>
        <div style={{ maxHeight: 320, overflow: 'auto' }}>
          {filteredDiagrams.length > 0 && (
            <div style={{ padding: '8px 0' }}>
              <div style={{ fontSize: 10, color: '#525252', padding: '4px 16px', textTransform: 'uppercase' }}>
                Diagrams
              </div>
              {filteredDiagrams.map((d) => (
                <div
                  key={d.id}
                  onClick={() => { navigate(`/diagram/${d.id}`); onClose() }}
                  style={{
                    padding: '8px 16px', cursor: 'pointer', fontSize: 13,
                    display: 'flex', alignItems: 'center', gap: 8,
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = '#262626')}
                  onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                >
                  <span style={{ opacity: 0.5 }}>▦</span>
                  {d.name}
                </div>
              ))}
            </div>
          )}
          {filteredObjects.length > 0 && (
            <div style={{ padding: '8px 0' }}>
              <div style={{ fontSize: 10, color: '#525252', padding: '4px 16px', textTransform: 'uppercase' }}>
                Objects
              </div>
              {filteredObjects.slice(0, 10).map((o) => (
                <div
                  key={o.id}
                  onClick={() => { onClose() }}
                  style={{
                    padding: '8px 16px', cursor: 'pointer', fontSize: 13,
                    display: 'flex', alignItems: 'center', gap: 8,
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = '#262626')}
                  onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                >
                  <span style={{ opacity: 0.5 }}>{TYPE_ICONS[o.type as ObjectType]}</span>
                  {o.name}
                  {/* TODO(tech-catalog): render TechBadge row (M7). */}
                  {o.technology_ids && o.technology_ids.length > 0 && (
                    <span style={{ fontSize: 10, color: '#525252' }}>
                      {o.technology_ids.join(', ')}
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}
          {query && filteredObjects.length === 0 && filteredDiagrams.length === 0 && (
            <div style={{ padding: 24, textAlign: 'center', color: '#525252', fontSize: 13 }}>
              No results for "{query}"
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
