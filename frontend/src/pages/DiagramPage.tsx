import { useCallback, useState, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ReactFlowProvider } from '@xyflow/react'
import { ArchFlowCanvas } from '../components/canvas/ArchFlowCanvas'
import { AddObjectToolbar } from '../components/toolbar/AddObjectToolbar'
import { FilterToolbar } from '../components/toolbar/FilterToolbar'
import { EdgeSidebar } from '../components/sidebar/EdgeSidebar'
import { ObjectSidebar } from '../components/sidebar/ObjectSidebar'
import { ObjectTree } from '../components/tree/ObjectTree'
import { SearchModal } from '../components/nav/SearchModal'
import { useDiagram } from '../hooks/use-diagrams'
import { useAuthStore } from '../stores/auth-store'
import { useCanvasStore } from '../stores/canvas-store'

export function DiagramPage() {
  const { diagramId } = useParams<{ diagramId: string }>()
  const { data: diagram } = useDiagram(diagramId)
  const navigate = useNavigate()
  const { logout } = useAuthStore()
  const { selectedEdgeId, treeOpen, toggleTree } = useCanvasStore()
  const [searchOpen, setSearchOpen] = useState(false)

  const toggleSearch = useCallback(() => setSearchOpen((v) => !v), [])

  return (
    <ReactFlowProvider>
      <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: '#0a0a0a', color: '#f5f5f5' }}>
        {/* Top bar with breadcrumbs */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '8px 16px', borderBottom: '1px solid #262626', background: '#111',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <button
              onClick={() => navigate('/')}
              style={{
                background: 'none', border: 'none', color: '#a3a3a3', cursor: 'pointer',
                fontSize: 16, padding: '2px 6px',
              }}
              title="Home"
            >
              ⌂
            </button>
            <span style={{ color: '#333' }}>›</span>
            <button
              onClick={() => navigate('/')}
              style={{
                background: 'none', border: 'none', color: '#a3a3a3', cursor: 'pointer',
                fontSize: 13, padding: '2px 6px',
              }}
            >
              Diagrams
            </button>
            <span style={{ color: '#333' }}>›</span>
            <span style={{ fontSize: 13, fontWeight: 500 }}>
              {diagram?.name || 'Loading...'}
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <button
              onClick={toggleTree}
              style={{
                background: treeOpen ? '#333' : '#1a1a1a',
                border: '1px solid #333', borderRadius: 6,
                color: treeOpen ? '#f5f5f5' : '#737373',
                cursor: 'pointer', fontSize: 12, padding: '4px 10px',
              }}
              title="Toggle object tree"
            >
              ☰
            </button>
            <button
              onClick={toggleSearch}
              style={{
                background: '#1a1a1a', border: '1px solid #333', borderRadius: 6,
                color: '#737373', cursor: 'pointer', fontSize: 12, padding: '4px 10px',
                display: 'flex', alignItems: 'center', gap: 6,
              }}
            >
              🔍 Search
              <span style={{
                background: '#262626', borderRadius: 3, padding: '1px 4px',
                fontSize: 10, color: '#525252',
              }}>
                ⌘K
              </span>
            </button>
            <button
              onClick={async () => {
                const { toPng } = await import('html-to-image')
                const el = document.querySelector('.react-flow') as HTMLElement
                if (!el) return
                const dataUrl = await toPng(el, { backgroundColor: '#0a0a0a' })
                const a = document.createElement('a')
                a.href = dataUrl
                a.download = `archflow-${new Date().toISOString().slice(0, 10)}.png`
                a.click()
              }}
              style={{
                background: '#1a1a1a', border: '1px solid #333', borderRadius: 6,
                color: '#737373', cursor: 'pointer', fontSize: 12, padding: '4px 10px',
              }}
              title="Export as PNG"
            >
              📷
            </button>
            <button
              onClick={logout}
              style={{
                background: 'none', border: 'none', color: '#525252', cursor: 'pointer',
                fontSize: 12,
              }}
            >
              Sign out
            </button>
          </div>
        </div>

        {/* Canvas area */}
        <div style={{ display: 'flex', flex: 1, minHeight: 0, overflow: 'hidden' }}>
          {treeOpen && <ObjectTree diagramId={diagramId} />}
          <div style={{ flex: 1, position: 'relative', minWidth: 0 }}>
            <AddObjectToolbar diagramId={diagramId} />
            <div style={{ position: 'absolute', inset: 0 }}>
              <ArchFlowCanvas diagramId={diagramId} />
            </div>
            <FilterToolbar />
          </div>
          {selectedEdgeId ? <EdgeSidebar /> : <ObjectSidebar />}
        </div>
      </div>

      <SearchModal open={searchOpen} onClose={toggleSearch} />
    </ReactFlowProvider>
  )
}
