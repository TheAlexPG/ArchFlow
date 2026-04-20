import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthPage } from './components/auth/AuthPage'
import { ActivityPage } from './pages/ActivityPage'
import { ConnectionsPage } from './pages/ConnectionsPage'
import { DiagramPage } from './pages/DiagramPage'
import { DiagramsPage } from './pages/DiagramsPage'
import { DraftDetailPage } from './pages/DraftDetailPage'
import { DraftsPage } from './pages/DraftsPage'
import { MembersPage } from './pages/MembersPage'
import { ObjectsPage } from './pages/ObjectsPage'
import { OverviewPage } from './pages/OverviewPage'
import { SettingsPage } from './pages/SettingsPage'
import { TeamsPage } from './pages/TeamsPage'
import { VersionsPage } from './pages/VersionsPage'
import { useAuthStore } from './stores/auth-store'
import { useWorkspaceStore } from './stores/workspace-store'
import { useWorkspaceSocket } from './hooks/use-realtime'
import './index.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5000,
      retry: 1,
    },
  },
})

// Mounts the workspace firehose socket for all authenticated pages.
// Returns null — only side-effects (query invalidation on WS events).
function WorkspaceSocketGate() {
  useWorkspaceSocket()
  return null
}

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { isAuthenticated } = useAuthStore()
  if (!isAuthenticated) return <Navigate to="/login" replace />
  return <>{children}</>
}

function App() {
  const { isAuthenticated } = useAuthStore()
  const workspaceId = useWorkspaceStore((s) => s.currentWorkspaceId)

  return (
    <QueryClientProvider client={queryClient}>
      {isAuthenticated && workspaceId && <WorkspaceSocketGate />}
      <BrowserRouter>
        <Routes>
          <Route
            path="/login"
            element={isAuthenticated ? <Navigate to="/" replace /> : <AuthPage />}
          />
          <Route
            path="/"
            element={
              <ProtectedRoute>
                <OverviewPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/diagram/:diagramId"
            element={
              <ProtectedRoute>
                <DiagramPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/diagrams"
            element={
              <ProtectedRoute>
                <DiagramsPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/objects"
            element={
              <ProtectedRoute>
                <ObjectsPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/connections"
            element={
              <ProtectedRoute>
                <ConnectionsPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/drafts"
            element={
              <ProtectedRoute>
                <DraftsPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/drafts/:draftId"
            element={
              <ProtectedRoute>
                <DraftDetailPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/activity"
            element={
              <ProtectedRoute>
                <ActivityPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/versions"
            element={
              <ProtectedRoute>
                <VersionsPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/members"
            element={
              <ProtectedRoute>
                <MembersPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/teams"
            element={
              <ProtectedRoute>
                <TeamsPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/settings"
            element={
              <ProtectedRoute>
                <SettingsPage />
              </ProtectedRoute>
            }
          />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}

export default App
