import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'

// ─── Mocks (must come before the import under test) ─────────────────────────

const mockPost = vi.fn()
const mockDelete = vi.fn()

vi.mock('../../../lib/api-client', () => ({
  api: {
    get: vi.fn(),
    put: vi.fn(),
    post: (...args: unknown[]) => mockPost(...args),
    delete: (...args: unknown[]) => mockDelete(...args),
    patch: vi.fn(),
  },
}))

vi.mock('../../../stores/workspace-store', () => ({
  useWorkspaceStore: (selector: (s: { currentWorkspaceId: string }) => unknown) =>
    selector({ currentWorkspaceId: 'ws-1' }),
}))

vi.mock('../../../stores/auth-store', () => ({
  useAuthStore: Object.assign(
    (selector: (s: { accessToken: string; isAuthenticated: boolean }) => unknown) =>
      selector({ accessToken: 'tok', isAuthenticated: true }),
    {
      getState: () => ({
        accessToken: 'tok',
        refreshToken: 'rtok',
        isAuthenticated: true,
        setTokens: vi.fn(),
        logout: vi.fn(),
      }),
    },
  ),
}))

import { GitHubTokenSection } from '../GitHubTokenSection'

function makeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
}

function renderBlock() {
  const qc = makeClient()
  return render(
    <QueryClientProvider client={qc}>
      <GitHubTokenSection />
    </QueryClientProvider>,
  )
}

// Mark the initial /test call (status fetch) so it is distinguishable from
// later mutation calls in the same test.
function statusReply(linked: boolean, login: string | null = null) {
  return Promise.resolve({ data: { linked, github_login: login } })
}

describe('GitHubTokenSection', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders not-linked state and disables Save until a token is typed', async () => {
    mockPost.mockImplementation((url: string) => {
      if (url.endsWith('/github-token/test')) return statusReply(false)
      throw new Error(`Unexpected POST ${url}`)
    })

    renderBlock()

    await waitFor(() => {
      expect(screen.getByText('Not linked')).toBeInTheDocument()
    })

    // Save is disabled while the input is empty.
    expect(screen.getByText('Save').closest('button')).toBeDisabled()
  })

  it('renders linked state with the github login', async () => {
    mockPost.mockImplementation((url: string) => {
      if (url.endsWith('/github-token/test')) return statusReply(true, 'octocat')
      throw new Error(`Unexpected POST ${url}`)
    })

    renderBlock()

    await waitFor(() => {
      expect(screen.getByText('octocat')).toBeInTheDocument()
    })
    expect(screen.getByText('Linked', { exact: false })).toBeInTheDocument()
    // Clear button only shows in linked state.
    expect(screen.getByText('Clear')).toBeInTheDocument()
  })

  it('toggles the show/hide secret button', async () => {
    mockPost.mockImplementation(() => statusReply(false))
    renderBlock()
    await waitFor(() => screen.getByText('Not linked'))

    const input = screen.getByPlaceholderText('ghp_…') as HTMLInputElement
    expect(input.type).toBe('password')

    fireEvent.click(screen.getByText('Show'))
    expect(input.type).toBe('text')
    fireEvent.click(screen.getByText('Hide'))
    expect(input.type).toBe('password')
  })

  it('saves a token and surfaces success message', async () => {
    let calls = 0
    mockPost.mockImplementation((url: string, body?: unknown) => {
      if (url.endsWith('/github-token/test') && (!body || Object.keys(body).length === 0)) {
        // First call = initial status fetch (not linked).
        // Subsequent test calls keep returning whatever's relevant.
        calls += 1
        return statusReply(calls > 1)
      }
      if (url.endsWith('/github-token')) {
        return Promise.resolve({
          data: { linked: true, github_login: 'octocat' },
        })
      }
      throw new Error(`Unexpected POST ${url}`)
    })

    renderBlock()
    await waitFor(() => screen.getByText('Not linked'))

    fireEvent.change(screen.getByPlaceholderText('ghp_…'), {
      target: { value: 'ghp_real_token_value' },
    })
    fireEvent.click(screen.getByText('Save'))

    await waitFor(() => {
      expect(screen.getByText('Token saved.')).toBeInTheDocument()
    })

    // Save endpoint was hit with the correct body.
    expect(
      mockPost.mock.calls.some(
        ([url, body]) =>
          url === '/workspaces/ws-1/github-token' &&
          (body as { token?: string })?.token === 'ghp_real_token_value',
      ),
    ).toBe(true)
  })

  it('clears a token via the DELETE endpoint', async () => {
    mockPost.mockImplementation(() => statusReply(true, 'octocat'))
    mockDelete.mockResolvedValue({ data: undefined })

    // confirm() returns true to proceed with deletion.
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)

    renderBlock()
    await waitFor(() => screen.getByText('octocat'))

    fireEvent.click(screen.getByText('Clear'))

    await waitFor(() => {
      expect(mockDelete).toHaveBeenCalledWith('/workspaces/ws-1/github-token')
    })

    confirmSpy.mockRestore()
  })

  it('shows the inline error when GitHub rejects the token', async () => {
    let calls = 0
    mockPost.mockImplementation((url: string) => {
      if (url.endsWith('/github-token/test')) {
        calls += 1
        // First call = initial status fetch (not linked).
        if (calls === 1) return statusReply(false)
        // Test button explicitly hits the test endpoint with the typed
        // token. Backend reports linked=false on a 401-from-GitHub.
        return statusReply(false)
      }
      throw new Error(`Unexpected POST ${url}`)
    })

    renderBlock()
    await waitFor(() => screen.getByText('Not linked'))

    fireEvent.change(screen.getByPlaceholderText('ghp_…'), {
      target: { value: 'ghp_bogus' },
    })
    fireEvent.click(screen.getByText('Test'))

    await waitFor(() => {
      expect(screen.getByText(/did not accept this token/i)).toBeInTheDocument()
    })
  })
})
