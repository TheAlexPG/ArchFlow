import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ReactFlowProvider } from '@xyflow/react'
import { ArchFlowCanvas } from './components/canvas/ArchFlowCanvas'
import { AddObjectToolbar } from './components/toolbar/AddObjectToolbar'
import { ObjectSidebar } from './components/sidebar/ObjectSidebar'
import { ObjectTree } from './components/tree/ObjectTree'
import { AuthPage } from './components/auth/AuthPage'
import { TopBar } from './components/nav/TopBar'
import { useAuthStore } from './stores/auth-store'
import './index.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5000,
      retry: 1,
    },
  },
})

function App() {
  const { isAuthenticated } = useAuthStore()

  return (
    <QueryClientProvider client={queryClient}>
      {!isAuthenticated ? (
        <AuthPage />
      ) : (
        <ReactFlowProvider>
          <div
            style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: '#0a0a0a', color: '#f5f5f5' }}
          >
            <TopBar />
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
      )}
    </QueryClientProvider>
  )
}

export default App
