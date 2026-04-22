import { QueryClient, QueryClientProvider, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthPage } from './components/auth/AuthPage'
import { AuthCallback } from './components/auth/AuthCallback'
import { ActivityPage } from './pages/ActivityPage'
import { ConnectionsPage } from './pages/ConnectionsPage'
import { DiagramPage } from './pages/DiagramPage'
import { DiagramsPage } from './pages/DiagramsPage'
import { DraftDetailPage } from './pages/DraftDetailPage'
import { DraftsPage } from './pages/DraftsPage'
import { MembersPage } from './pages/MembersPage'
import { MyInvitesPage } from './pages/MyInvitesPage'
import { LandingPage } from './pages/LandingPage'
import { ObjectsPage } from './pages/ObjectsPage'
import { OverviewPage } from './pages/OverviewPage'
import { PrivacyPage } from './pages/PrivacyPage'
import { SettingsPage } from './pages/SettingsPage'
import { TermsPage } from './pages/TermsPage'
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

// Workspace-scoped endpoints authorize via the X-Workspace-ID header set in
// the axios interceptor — the header is NOT part of the React Query cache key.
// On workspace switch we therefore drop the cache so the UI doesn't show the
// previous workspace's data until the background refetch lands.
function WorkspaceCacheReset() {
  const queryClient = useQueryClient()
  const workspaceId = useWorkspaceStore((s) => s.currentWorkspaceId)
  const prev = useRef(workspaceId)
  useEffect(() => {
    if (prev.current !== null && prev.current !== workspaceId) {
      queryClient.removeQueries()
    }
    prev.current = workspaceId
  }, [workspaceId, queryClient])
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
      {isAuthenticated && <WorkspaceCacheReset />}
      {isAuthenticated && workspaceId && <WorkspaceSocketGate />}
      <BrowserRouter>
        <Routes>
          <Route
            path="/login"
            element={isAuthenticated ? <Navigate to="/" replace /> : <AuthPage />}
          />
          <Route path="/auth/callback" element={<AuthCallback />} />
          {/* Public legal pages — must be reachable from the Google OAuth
              consent screen without requiring an account. */}
          <Route path="/terms" element={<TermsPage />} />
          <Route path="/privacy" element={<PrivacyPage />} />
          <Route
            path="/"
            element={isAuthenticated ? <OverviewPage /> : <LandingPage />}
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
            path="/invites"
            element={
              <ProtectedRoute>
                <MyInvitesPage />
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
