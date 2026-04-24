import axios, { AxiosError, type AxiosRequestConfig } from 'axios'

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

// Rotate the pair of JWTs through POST /auth/refresh and return the new
// access token, or null if the refresh token itself is invalid/expired.
// Parallel 401s dedupe onto the same promise — otherwise a page that
// fires twenty queries at once would fire twenty refreshes, most of
// which would fail because refresh tokens rotate on every call.
let refreshInFlight: Promise<string | null> | null = null

async function refreshAccessToken(): Promise<string | null> {
  if (refreshInFlight) return refreshInFlight
  const refreshToken = useAuthStore.getState().refreshToken
  if (!refreshToken) return null

  refreshInFlight = (async () => {
    try {
      // Use a bare axios call (not `api`) so this request never goes
      // through the 401 interceptor itself — otherwise a failing
      // refresh would recurse into another refresh attempt.
      const resp = await axios.post(
        '/api/v1/auth/refresh',
        null,
        { params: { refresh_token: refreshToken } },
      )
      const { access_token, refresh_token } = resp.data as {
        access_token: string
        refresh_token: string
      }
      useAuthStore.getState().setTokens(access_token, refresh_token)
      return access_token
    } catch {
      return null
    } finally {
      refreshInFlight = null
    }
  })()

  return refreshInFlight
}

// Global 401 handler: try to swap the refresh token for a fresh access
// token and replay the original request. Only after that attempt fails
// do we tear down the session — otherwise a user would get logged out
// every 15 minutes (the access-token TTL).
api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config as
      | (AxiosRequestConfig & { _retry?: boolean })
      | undefined
    const status = error.response?.status

    if (
      status === 401 &&
      originalRequest &&
      !originalRequest._retry &&
      // Never retry the refresh endpoint itself: if /auth/refresh 401s,
      // the refresh token is dead and we have to log the user out.
      !originalRequest.url?.includes('/auth/refresh')
    ) {
      originalRequest._retry = true
      const fresh = await refreshAccessToken()
      if (fresh) {
        originalRequest.headers = originalRequest.headers ?? {}
        ;(originalRequest.headers as Record<string, string>).Authorization =
          `Bearer ${fresh}`
        return api(originalRequest)
      }
      // Refresh failed (or no refresh token) — drop the session so
      // ProtectedRoute can bounce us to /login on the next render.
      if (useAuthStore.getState().isAuthenticated) {
        useAuthStore.getState().logout()
      }
    }

    return Promise.reject(error)
  },
)
