import axios from 'axios'

import { useAuthStore } from '../stores/auth-store'
import { useWorkspaceStore } from '../stores/workspace-store'

// Single shared axios instance for all React Query hooks. Attaches the
// user's JWT + currently-selected workspace so the backend can scope
// writes/reads without each caller threading it through. Two separate
// instances previously existed (use-api.ts and use-diagrams.ts), and the
// diagrams one silently dropped the X-Workspace-ID header — which made
// workspace switching leak the default workspace's diagrams everywhere.
export const api = axios.create({ baseURL: '/api/v1' })

api.interceptors.request.use((config) => {
  const token = useAuthStore.getState().accessToken
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  const wsId = useWorkspaceStore.getState().currentWorkspaceId
  if (wsId) {
    config.headers['X-Workspace-ID'] = wsId
  }
  return config
})

// Global 401 handler: an expired/invalid token leaves the SPA rendering empty
// data because every hook fails silently. Flipping isAuthenticated to false
// lets ProtectedRoute in App.tsx redirect to /login on the next render — no
// manual navigation needed here (router state inside an interceptor is
// awkward). Guarded so a burst of concurrent 401s doesn't stomp the store
// repeatedly.
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error?.response?.status === 401) {
      if (useAuthStore.getState().isAuthenticated) {
        useAuthStore.getState().logout()
      }
    }
    return Promise.reject(error)
  },
)
