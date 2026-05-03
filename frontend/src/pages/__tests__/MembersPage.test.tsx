/**
 * MembersPage tests — agent_access column in the members table.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// ─── Shared mock state ────────────────────────────────────────────────────────

const mockUpdateRoleMutate = vi.fn()
const mockUpdateRoleMutation = { mutate: mockUpdateRoleMutate }

let mockCurrentUserId = 'u-admin'

const mockMembersBase = [
  {
    user_id: 'u-admin',
    name: 'Admin User',
    email: 'admin@example.com',
    role: 'admin' as const,
    agent_access: 'full' as const,
  },
  {
    user_id: 'u-editor',
    name: 'Editor User',
    email: 'editor@example.com',
    role: 'editor' as const,
    agent_access: 'read_only' as const,
  },
  {
    user_id: 'u-viewer',
    name: 'Viewer User',
    email: 'viewer@example.com',
    role: 'viewer' as const,
    agent_access: 'none' as const,
  },
]

vi.mock('../../hooks/use-api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../hooks/use-api')>()
  return {
    ...actual,
    useInviteMember: () => ({
      mutateAsync: vi.fn().mockResolvedValue({
        type: 'invite_created',
        invite: { id: 'i1', email: 'x@x.com', role: 'editor', token: 'tok', team_ids: [] },
      }),
      isPending: false,
    }),
    useRemoveMember: () => ({ mutate: vi.fn() }),
    useRevokeInvite: () => ({ mutate: vi.fn() }),
    useTeams: () => ({ data: [] }),
    useUpdateMemberRole: () => mockUpdateRoleMutation,
    useWorkspaceInvites: () => ({ data: [] }),
    useWorkspaceMembers: () => ({ data: mockMembersBase, isLoading: false }),
    useMe: () => ({ data: { id: mockCurrentUserId, email: 'admin@example.com', name: 'Admin User' } }),
    useMyInvites: () => ({ data: [] }),
    useDrafts: () => ({ data: [] }),
    useNotifications: () => ({ data: [] }),
    useUnreadNotificationCount: () => ({ data: 0 }),
    useWorkspaces: () => ({ data: [] }),
    useCurrentMemberAgentAccess: () => 'full' as const,
  }
})

vi.mock('../../stores/workspace-store', () => {
  const state = { currentWorkspaceId: 'ws-1', setCurrentWorkspaceId: vi.fn() }
  const useWorkspaceStore = (sel?: (s: typeof state) => unknown) =>
    sel ? sel(state) : state
  return { useWorkspaceStore }
})

vi.mock('../../stores/auth-store', () => {
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

import { MembersPage } from '../MembersPage'

// ─── Suite ───────────────────────────────────────────────────────────────────

describe('MembersPage — Agent access column', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockCurrentUserId = 'u-admin'
  })

  it('renders Agent access column header', () => {
    renderPage()
    // The column header "Agent access" appears in the <th> element
    const headers = screen.getAllByText('Agent access')
    // At least one should be a <th>
    expect(headers.some((el) => el.tagName === 'TH')).toBe(true)
  })

  it('admin sees editable selects for other members', () => {
    renderPage()

    // Other members (editor, viewer) should have selects visible to admin
    const editorSelect = screen.getByTestId('agent-access-select-u-editor')
    const viewerSelect = screen.getByTestId('agent-access-select-u-viewer')

    expect(editorSelect).toBeInTheDocument()
    expect(viewerSelect).toBeInTheDocument()
  })

  it('admin sees their own agent_access as a read-only badge (not editable)', () => {
    renderPage()

    // The current user (u-admin) should see a badge, not a select
    const adminBadge = screen.getByTestId('agent-access-badge-u-admin')
    expect(adminBadge).toBeInTheDocument()
    expect(screen.queryByTestId('agent-access-select-u-admin')).not.toBeInTheDocument()
  })

  it('editor (non-admin) sees read-only badges for all agent_access values', () => {
    mockCurrentUserId = 'u-editor'
    renderPage()

    // Non-admin users see badges, not selects for other members
    const badges = screen.getAllByTestId(/^agent-access-badge-/)
    expect(badges.length).toBe(mockMembersBase.length)

    // No selects should appear
    expect(screen.queryAllByTestId(/^agent-access-select-/).length).toBe(0)
  })

  it('changing agent_access select calls PATCH with new value', () => {
    renderPage()

    const editorSelect = screen.getByTestId('agent-access-select-u-editor')
    fireEvent.change(editorSelect, { target: { value: 'none' } })

    expect(mockUpdateRoleMutate).toHaveBeenCalledWith({
      userId: 'u-editor',
      agent_access: 'none',
    })
  })

  it('changing agent_access to full calls PATCH with full', () => {
    renderPage()

    const viewerSelect = screen.getByTestId('agent-access-select-u-viewer')
    fireEvent.change(viewerSelect, { target: { value: 'full' } })

    expect(mockUpdateRoleMutate).toHaveBeenCalledWith({
      userId: 'u-viewer',
      agent_access: 'full',
    })
  })

  it('badge for disabled agent_access shows "Disabled"', () => {
    // Switch to viewer perspective so badges are shown
    mockCurrentUserId = 'u-viewer'
    renderPage()

    // The viewer member's own badge should say "Disabled"
    const viewerBadge = screen.getByTestId('agent-access-badge-u-viewer')
    expect(viewerBadge).toHaveTextContent('Disabled')
  })

  it('badge for full agent_access shows "Full"', () => {
    mockCurrentUserId = 'u-viewer'
    renderPage()

    const adminBadge = screen.getByTestId('agent-access-badge-u-admin')
    expect(adminBadge).toHaveTextContent('Full')
  })

  it('badge for read_only shows "Read-only"', () => {
    mockCurrentUserId = 'u-viewer'
    renderPage()

    const editorBadge = screen.getByTestId('agent-access-badge-u-editor')
    expect(editorBadge).toHaveTextContent('Read-only')
  })
})
