import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useDiagrams, useCreateDiagram, useDeleteDiagram } from '../hooks/use-diagrams'
import { AppSidebar } from '../components/nav/AppSidebar'
import { SearchModal } from '../components/nav/SearchModal'

const DIAGRAM_TYPE_LABELS: Record<string, string> = {
  system_landscape: 'L1 — System Landscape',
  system_context: 'L1 — System Context',
  container: 'L2 — Container',
  component: 'L3 — Component',
  custom: 'Custom',
}

const DIAGRAM_TYPE_ICONS: Record<string, string> = {
  system_landscape: '🌐',
  system_context: '◉',
  container: '▦',
  component: '◧',
  custom: '✦',
}

export function OverviewPage() {
  const { data: diagrams = [] } = useDiagrams()
  const createDiagram = useCreateDiagram()
  const deleteDiagram = useDeleteDiagram()
  const navigate = useNavigate()
  const [showCreate, setShowCreate] = useState(false)
  const [newName, setNewName] = useState('')
  const [newType, setNewType] = useState('system_landscape')
  const [searchOpen, setSearchOpen] = useState(false)
  const toggleSearch = useCallback(() => setSearchOpen((v) => !v), [])

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        setSearchOpen((v) => !v)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  const handleCreate = () => {
    if (!newName.trim()) return
    createDiagram.mutate(
      { name: newName.trim(), type: newType },
      {
        onSuccess: (diagram) => {
          setShowCreate(false)
          setNewName('')
          navigate(`/diagram/${diagram.id}`)
        },
      },
    )
  }

  const grouped = diagrams.reduce<Record<string, typeof diagrams>>((acc, d) => {
    const group = DIAGRAM_TYPE_LABELS[d.type] || d.type
    if (!acc[group]) acc[group] = []
    acc[group].push(d)
    return acc
  }, {})

  return (
    <div style={{ display: 'flex', height: '100vh', background: '#0a0a0a', color: '#f5f5f5' }}>
      <AppSidebar />
      {/* Main content */}
      <div style={{ flex: 1, overflow: 'auto', padding: 32 }}>
        <div style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 32
        }}>
          <h1 style={{ fontSize: 24, fontWeight: 600, margin: 0 }}>Diagrams</h1>
          <button
            onClick={() => setShowCreate(true)}
            style={{
              background: '#2563eb', color: 'white', border: 'none', borderRadius: 8,
              padding: '8px 16px', cursor: 'pointer', fontSize: 13, fontWeight: 500,
            }}
          >
            + Create diagram
          </button>
        </div>

        {/* Create dialog */}
        {showCreate && (
          <div style={{
            background: '#171717', border: '1px solid #333', borderRadius: 12,
            padding: 20, marginBottom: 24, maxWidth: 400,
          }}>
            <div style={{ fontSize: 14, fontWeight: 500, marginBottom: 12 }}>New diagram</div>
            <input
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="Diagram name..."
              autoFocus
              onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
              style={{
                width: '100%', background: '#0a0a0a', border: '1px solid #333', borderRadius: 6,
                padding: '8px 12px', color: '#f5f5f5', fontSize: 13, marginBottom: 8,
                boxSizing: 'border-box',
              }}
            />
            <select
              value={newType}
              onChange={(e) => setNewType(e.target.value)}
              style={{
                width: '100%', background: '#0a0a0a', border: '1px solid #333', borderRadius: 6,
                padding: '8px 12px', color: '#f5f5f5', fontSize: 13, marginBottom: 12,
                boxSizing: 'border-box',
              }}
            >
              {Object.entries(DIAGRAM_TYPE_LABELS).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
            <div style={{ display: 'flex', gap: 8 }}>
              <button
                onClick={handleCreate}
                style={{
                  background: '#2563eb', color: 'white', border: 'none', borderRadius: 6,
                  padding: '6px 14px', cursor: 'pointer', fontSize: 13,
                }}
              >
                Create
              </button>
              <button
                onClick={() => setShowCreate(false)}
                style={{
                  background: 'none', color: '#737373', border: '1px solid #333', borderRadius: 6,
                  padding: '6px 14px', cursor: 'pointer', fontSize: 13,
                }}
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {/* Diagrams by type */}
        {Object.entries(grouped).map(([group, items]) => (
          <div key={group} style={{ marginBottom: 32 }}>
            <h2 style={{ fontSize: 14, fontWeight: 500, color: '#a3a3a3', marginBottom: 12 }}>
              {group}
            </h2>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: 12 }}>
              {items.map((d) => (
                <div
                  key={d.id}
                  onClick={() => navigate(`/diagram/${d.id}`)}
                  style={{
                    background: '#171717', border: '1px solid #262626', borderRadius: 10,
                    padding: 16, cursor: 'pointer', transition: 'border-color 0.15s',
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.borderColor = '#404040')}
                  onMouseLeave={(e) => (e.currentTarget.style.borderColor = '#262626')}
                >
                  <div style={{
                    height: 100, background: '#0a0a0a', borderRadius: 6, marginBottom: 12,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontSize: 32, opacity: 0.3,
                  }}>
                    {DIAGRAM_TYPE_ICONS[d.type] || '▦'}
                  </div>
                  <div style={{ fontSize: 13, fontWeight: 500 }}>{d.name}</div>
                  <div style={{ fontSize: 11, color: '#737373', marginTop: 4 }}>
                    {DIAGRAM_TYPE_LABELS[d.type] || d.type}
                  </div>
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      if (confirm(`Delete "${d.name}"?`)) deleteDiagram.mutate(d.id)
                    }}
                    style={{
                      background: 'none', border: 'none', color: '#525252', cursor: 'pointer',
                      fontSize: 11, padding: '4px 0', marginTop: 8,
                    }}
                  >
                    Delete
                  </button>
                </div>
              ))}
            </div>
          </div>
        ))}

        {diagrams.length === 0 && !showCreate && (
          <div style={{ textAlign: 'center', padding: 60, color: '#525252' }}>
            <div style={{ fontSize: 40, marginBottom: 12 }}>▦</div>
            <div style={{ fontSize: 14 }}>No diagrams yet</div>
            <div style={{ fontSize: 12, marginTop: 4 }}>Click "+ Create diagram" to get started</div>
          </div>
        )}
      </div>
      <SearchModal open={searchOpen} onClose={toggleSearch} />
    </div>
  )
}
