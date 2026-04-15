import { useParams, useNavigate } from 'react-router-dom'
import { ReactFlowProvider } from '@xyflow/react'
import { ArchFlowCanvas } from '../components/canvas/ArchFlowCanvas'
import { AddObjectToolbar } from '../components/toolbar/AddObjectToolbar'
import { ObjectSidebar } from '../components/sidebar/ObjectSidebar'
import { ObjectTree } from '../components/tree/ObjectTree'
import { useAuthStore } from '../stores/auth-store'

export function DiagramPage() {
  const { diagramId } = useParams<{ diagramId: string }>()
  const navigate = useNavigate()
  const { logout } = useAuthStore()

  return (
    <ReactFlowProvider>
      <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: '#0a0a0a', color: '#f5f5f5' }}>
        {/* Top bar */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '8px 16px', borderBottom: '1px solid #262626', background: '#111',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <button
              onClick={() => navigate('/')}
              style={{
                background: 'none', border: 'none', color: '#a3a3a3', cursor: 'pointer',
                fontSize: 14, padding: '4px 8px',
              }}
            >
              ← Back
            </button>
            <span style={{ color: '#404040' }}>|</span>
            <span style={{ fontWeight: 600, fontSize: 14 }}>ArchFlow</span>
            <span style={{ color: '#525252', fontSize: 13 }}>
              Diagram
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
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
          <ObjectTree />
          <div style={{ flex: 1, position: 'relative', minWidth: 0 }}>
            <AddObjectToolbar />
            <div style={{ position: 'absolute', inset: 0 }}>
              <ArchFlowCanvas />
            </div>
          </div>
          <ObjectSidebar />
        </div>
      </div>
    </ReactFlowProvider>
  )
}
