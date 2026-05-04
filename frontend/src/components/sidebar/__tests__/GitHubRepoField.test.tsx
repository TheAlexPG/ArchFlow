import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mockPost = vi.fn()

vi.mock('../../../lib/api-client', () => ({
  api: {
    get: vi.fn(),
    put: vi.fn(),
    post: (...args: unknown[]) => mockPost(...args),
    delete: vi.fn(),
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

import { GitHubRepoField } from '../GitHubRepoField'

function makeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
}

interface RenderArgs {
  type?: string
  repo_url?: string | null
  repo_branch?: string | null
  onChange?: (
    patch: { repo_url?: string | null; repo_branch?: string | null },
  ) => void
}

function renderField({
  type = 'app',
  repo_url = null,
  repo_branch = null,
  onChange = vi.fn(),
}: RenderArgs = {}) {
  const qc = makeClient()
  return render(
    <QueryClientProvider client={qc}>
      <GitHubRepoField
        obj={{ id: 'obj-1', type, repo_url, repo_branch }}
        onChange={onChange}
      />
    </QueryClientProvider>,
  )
}

describe('GitHubRepoField', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockPost.mockImplementation((url: string) => {
      // Default token-status reply: linked.
      if (url.endsWith('/github-token/test')) {
        return Promise.resolve({
          data: { linked: true, github_login: 'octocat' },
        })
      }
      throw new Error(`Unexpected POST ${url}`)
    })
  })

  it('renders nothing for non-Container/System types', () => {
    const { container } = renderField({ type: 'component' })
    expect(container).toBeEmptyDOMElement()
  })

  it('renders the input for system type', async () => {
    renderField({ type: 'system' })
    await waitFor(() => {
      expect(screen.getByTestId('github-repo-field')).toBeInTheDocument()
    })
  })

  it('disables the input when the workspace has no token', async () => {
    mockPost.mockImplementation((url: string) => {
      if (url.endsWith('/github-token/test')) {
        return Promise.resolve({ data: { linked: false, github_login: null } })
      }
      throw new Error(`Unexpected POST ${url}`)
    })
    renderField({ type: 'app' })
    await waitFor(() => {
      const input = screen.getByTestId('github-repo-url-input') as HTMLInputElement
      expect(input.disabled).toBe(true)
    })
  })

  it('validates-on-blur and shows ✓ on a 200 lookup', async () => {
    const onChange = vi.fn()
    mockPost.mockImplementation((url: string) => {
      if (url.endsWith('/github-token/test')) {
        return Promise.resolve({
          data: { linked: true, github_login: 'octocat' },
        })
      }
      if (url === '/repos/lookup') {
        return Promise.resolve({
          data: {
            repo_url: 'https://github.com/microsoft/typescript',
            full_name: 'microsoft/typescript',
            description: 'TypeScript repo',
            default_branch: 'main',
            stargazers_count: 1,
            private: false,
            html_url: 'https://github.com/microsoft/typescript',
          },
        })
      }
      throw new Error(`Unexpected POST ${url}`)
    })

    renderField({ type: 'app', onChange })

    await waitFor(() => screen.getByTestId('github-repo-url-input'))

    const input = screen.getByTestId('github-repo-url-input') as HTMLInputElement
    fireEvent.change(input, {
      target: { value: 'https://github.com/microsoft/typescript' },
    })
    fireEvent.blur(input)

    await waitFor(() => {
      expect(screen.getByTestId('github-repo-valid')).toBeInTheDocument()
    })
    expect(screen.getByTestId('github-repo-valid')).toHaveTextContent(
      'microsoft/typescript',
    )

    // onChange should have fired with the canonical url.
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        repo_url: 'https://github.com/microsoft/typescript',
      }),
    )
  })

  it('shows ✗ with the not-found message on 404', async () => {
    mockPost.mockImplementation((url: string) => {
      if (url.endsWith('/github-token/test')) {
        return Promise.resolve({
          data: { linked: true, github_login: 'octocat' },
        })
      }
      if (url === '/repos/lookup') {
        return Promise.reject({
          response: {
            status: 404,
            data: { detail: { error: 'not_found', message: 'gone' } },
          },
        })
      }
      throw new Error(`Unexpected POST ${url}`)
    })

    renderField({ type: 'app' })
    await waitFor(() => screen.getByTestId('github-repo-url-input'))

    const input = screen.getByTestId('github-repo-url-input') as HTMLInputElement
    fireEvent.change(input, {
      target: { value: 'https://github.com/owner/missing' },
    })
    fireEvent.blur(input)

    await waitFor(() => {
      expect(screen.getByTestId('github-repo-invalid')).toBeInTheDocument()
    })
    expect(screen.getByTestId('github-repo-invalid')).toHaveTextContent(
      /not found/i,
    )
  })

  it('clearing the URL triggers an onChange with null repo_url + null branch', async () => {
    const onChange = vi.fn()
    renderField({
      type: 'app',
      repo_url: 'https://github.com/owner/repo',
      repo_branch: 'main',
      onChange,
    })
    await waitFor(() => screen.getByTestId('github-repo-url-input'))

    const input = screen.getByTestId('github-repo-url-input') as HTMLInputElement
    fireEvent.change(input, { target: { value: '' } })
    fireEvent.blur(input)

    expect(onChange).toHaveBeenCalledWith({
      repo_url: null,
      repo_branch: null,
    })
  })

  it('reveals the branch input when toggling Show advanced', async () => {
    renderField({ type: 'app' })
    await waitFor(() => screen.getByTestId('github-repo-url-input'))

    expect(
      screen.queryByTestId('github-repo-branch-input'),
    ).not.toBeInTheDocument()

    fireEvent.click(screen.getByText(/Show advanced/i))
    expect(screen.getByTestId('github-repo-branch-input')).toBeInTheDocument()
  })
})
