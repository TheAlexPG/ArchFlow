import { render, screen, fireEvent, act } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// Mocks must come before imports of the SUT.
let mockAgentAccess: 'full' | 'read_only' | 'none' = 'full'
let mockRole: 'owner' | 'admin' | 'editor' | 'reviewer' | 'viewer' | null = 'editor'
const mockNavigate = vi.fn()

vi.mock('../../../hooks/use-api', () => ({
  useDraftsForDiagram: () => ({ data: undefined }),
  useCurrentMemberAgentAccess: () => mockAgentAccess,
  useCurrentMemberRole: () => mockRole,
}))

vi.mock('../hooks/use-chat-context', () => ({
  useChatContext: () => ({ kind: 'workspace', id: 'ws-1' }),
}))

vi.mock('../SessionPicker', () => ({
  SessionPicker: () => null,
}))

vi.mock('react-router-dom', async () => {
  const actual: object = await vi.importActual('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
})

import { ChatHeader } from '../ChatHeader'
import { useAgentChatStore } from '../store'

function wrap(children: ReactNode) {
  return <MemoryRouter>{children}</MemoryRouter>
}

beforeEach(() => {
  mockAgentAccess = 'full'
  mockRole = 'editor'
  mockNavigate.mockReset()
  // Reset zustand store mode to 'full' between tests.
  useAgentChatStore.setState({ mode: 'full' })
})

describe('ChatHeader access gating', () => {
  it('keeps Full toggle clickable when agent_access=full', () => {
    mockAgentAccess = 'full'
    render(wrap(<ChatHeader />))
    const fullBtn = screen.getByTestId('mode-toggle-full')
    expect(fullBtn).toHaveAttribute('aria-checked', 'true')
    expect(fullBtn).not.toHaveAttribute('aria-disabled', 'true')
    expect(screen.queryByTestId('agent-access-upgrade-modal')).toBeNull()
  })

  it('downgrades store mode to read_only when membership is read_only', async () => {
    mockAgentAccess = 'read_only'
    render(wrap(<ChatHeader />))
    // useEffect runs once after mount; verify the store was clamped.
    expect(useAgentChatStore.getState().mode).toBe('read_only')
    const readBtn = screen.getByTestId('mode-toggle-read_only')
    expect(readBtn).toHaveAttribute('aria-checked', 'true')
  })

  it('disables Full toggle when membership is read_only', () => {
    mockAgentAccess = 'read_only'
    render(wrap(<ChatHeader />))
    const fullBtn = screen.getByTestId('mode-toggle-full')
    expect(fullBtn).toHaveAttribute('aria-disabled', 'true')
    expect(fullBtn.textContent).toMatch(/🔒/)
  })

  it('opens upgrade modal on disabled Full click', () => {
    mockAgentAccess = 'read_only'
    render(wrap(<ChatHeader />))
    expect(screen.queryByTestId('agent-access-upgrade-modal')).toBeNull()
    fireEvent.click(screen.getByTestId('mode-toggle-full'))
    expect(screen.getByTestId('agent-access-upgrade-modal')).toBeInTheDocument()
  })

  it('shows self-serve CTA for owner/admin', () => {
    mockAgentAccess = 'read_only'
    mockRole = 'owner'
    render(wrap(<ChatHeader />))
    fireEvent.click(screen.getByTestId('mode-toggle-full'))
    const cta = screen.getByTestId('agent-access-upgrade-cta')
    expect(cta).toBeInTheDocument()
    fireEvent.click(cta)
    expect(mockNavigate).toHaveBeenCalledWith('/members')
  })

  it('hides self-serve CTA for non-admin members', () => {
    mockAgentAccess = 'read_only'
    mockRole = 'editor'
    render(wrap(<ChatHeader />))
    fireEvent.click(screen.getByTestId('mode-toggle-full'))
    expect(screen.getByTestId('agent-access-upgrade-modal')).toBeInTheDocument()
    expect(screen.queryByTestId('agent-access-upgrade-cta')).toBeNull()
  })

  it('Dismiss button closes the modal', () => {
    mockAgentAccess = 'read_only'
    render(wrap(<ChatHeader />))
    fireEvent.click(screen.getByTestId('mode-toggle-full'))
    expect(screen.getByTestId('agent-access-upgrade-modal')).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('agent-access-upgrade-dismiss'))
    expect(screen.queryByTestId('agent-access-upgrade-modal')).toBeNull()
  })
})

// Suppress unused import warnings for `act` (kept for future async tests).
void act
