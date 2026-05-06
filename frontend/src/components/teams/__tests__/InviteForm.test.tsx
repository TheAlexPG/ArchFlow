/**
 * InviteForm tests — exercises the invite section of MembersPage.
 *
 * The MembersPage owns the invite form inline (no separate InviteForm component).
 * These tests cover the agent_access select field behaviour in the invite flow.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// ─── Mocks ───────────────────────────────────────────────────────────────────

const mockInviteMutateAsync = vi.fn()
const mockInviteMutation = {
  mutateAsync: mockInviteMutateAsync,
  isPending: false,
}

const mockMembers = [
  {
    user_id: 'u-admin',
    name: 'Admin User',
    email: 'admin@example.com',
    role: 'admin' as const,
    agent_access: 'full' as const,
  },
]

vi.mock('../../../hooks/use-api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../hooks/use-api')>()
  return {
    ...actual,
    useInviteMember: () => mockInviteMutation,
    useRemoveMember: () => ({ mutate: vi.fn() }),
    useRevokeInvite: () => ({ mutate: vi.fn() }),
    useTeams: () => ({ data: [] }),
    useUpdateMemberRole: () => ({ mutate: vi.fn() }),
    useWorkspaceInvites: () => ({ data: [] }),
    useWorkspaceMembers: () => ({ data: mockMembers, isLoading: false }),
    useMe: () => ({ data: { id: 'u-admin', email: 'admin@example.com', name: 'Admin User' } }),
    useMyInvites: () => ({ data: [] }),
    useDrafts: () => ({ data: [] }),
    useNotifications: () => ({ data: [] }),
    useUnreadNotificationCount: () => ({ data: 0 }),
    useWorkspaces: () => ({ data: [] }),
    useCurrentMemberAgentAccess: () => 'full' as const,
  }
})

vi.mock('../../../stores/workspace-store', () => {
  const state = { currentWorkspaceId: 'ws-1', setCurrentWorkspaceId: vi.fn() }
  const useWorkspaceStore = (sel?: (s: typeof state) => unknown) =>
    sel ? sel(state) : state
  return { useWorkspaceStore }
})

vi.mock('../../../stores/auth-store', () => {
  const state = { logout: vi.fn(), accessToken: 'tok', refreshToken: null, isAuthenticated: true, setTokens: vi.fn() }
  const useAuthStore = (sel?: (s: typeof state) => unknown) =>
    sel ? sel(state) : state
  return { useAuthStore }
})

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>()
  return { ...actual }
})

// ─── Render helpers ──────────────────────────────────────────────────────────

function makeQueryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } })
}

function Wrapper({ children }: { children: ReactNode }) {
  return (
    <MemoryRouter>
      <QueryClientProvider client={makeQueryClient()}>
        {children}
      </QueryClientProvider>
    </MemoryRouter>
  )
}

function renderPage() {
  return render(<MembersPage />, { wrapper: Wrapper })
}

// ─── Import component under test ─────────────────────────────────────────────

import { MembersPage } from '../../../pages/MembersPage'

// ─── Suite ───────────────────────────────────────────────────────────────────

describe('InviteForm — agent_access field', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockInviteMutation.isPending = false
    mockInviteMutateAsync.mockResolvedValue({
      type: 'invite_created',
      invite: { id: 'inv-1', email: 'bob@example.com', role: 'editor', token: 'tok123', team_ids: [] },
    })
  })

  it('renders the agent_access select with read_only default', () => {
    renderPage()

    const select = screen.getByTestId('invite-agent-access')
    expect(select).toBeInTheDocument()
    expect((select as HTMLSelectElement).value).toBe('read_only')
  })

  it('agent_access select has all three options', () => {
    renderPage()

    const select = screen.getByTestId('invite-agent-access') as HTMLSelectElement
    const values = Array.from(select.options).map((o) => o.value)
    expect(values).toEqual(['read_only', 'full', 'none'])
  })

  it('shows hint text for the currently selected access level', () => {
    renderPage()

    // Default hint for read_only
    expect(
      screen.getByText('User can chat with the agent in read-only mode.'),
    ).toBeInTheDocument()
  })

  it('changing selection updates the hint text', () => {
    renderPage()

    const select = screen.getByTestId('invite-agent-access')
    fireEvent.change(select, { target: { value: 'full' } })

    expect(
      screen.getByText(
        'User can chat and let the agent modify diagrams (subject to drafts policy).',
      ),
    ).toBeInTheDocument()
  })

  it('submits invite with the chosen agent_access value', async () => {
    renderPage()

    // Fill in email
    fireEvent.change(screen.getByPlaceholderText('teammate@company.com'), {
      target: { value: 'bob@example.com' },
    })

    // Change agent_access to full
    fireEvent.change(screen.getByTestId('invite-agent-access'), {
      target: { value: 'full' },
    })

    // Submit
    fireEvent.click(screen.getByRole('button', { name: /invite/i }))

    await waitFor(() => {
      expect(mockInviteMutateAsync).toHaveBeenCalledWith(
        expect.objectContaining({
          email: 'bob@example.com',
          agent_access: 'full',
        }),
      )
    })
  })

  it('submits with read_only when access is not changed', async () => {
    renderPage()

    fireEvent.change(screen.getByPlaceholderText('teammate@company.com'), {
      target: { value: 'charlie@example.com' },
    })

    fireEvent.click(screen.getByRole('button', { name: /invite/i }))

    await waitFor(() => {
      expect(mockInviteMutateAsync).toHaveBeenCalledWith(
        expect.objectContaining({
          email: 'charlie@example.com',
          agent_access: 'read_only',
        }),
      )
    })
  })

  it('resets agent_access to read_only after successful invite', async () => {
    renderPage()

    const emailInput = screen.getByPlaceholderText('teammate@company.com')
    const accessSelect = screen.getByTestId('invite-agent-access') as HTMLSelectElement

    fireEvent.change(emailInput, { target: { value: 'dave@example.com' } })
    fireEvent.change(accessSelect, { target: { value: 'none' } })
    fireEvent.click(screen.getByRole('button', { name: /invite/i }))

    await waitFor(() => {
      expect(accessSelect.value).toBe('read_only')
    })
  })
})
