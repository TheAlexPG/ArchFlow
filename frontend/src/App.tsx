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
          <div className="flex flex-col h-full bg-neutral-950 text-neutral-100">
            <TopBar />
            <div className="flex flex-1 overflow-hidden">
              <ObjectTree />
              <div className="flex-1 relative">
                <AddObjectToolbar />
                <ArchFlowCanvas />
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
