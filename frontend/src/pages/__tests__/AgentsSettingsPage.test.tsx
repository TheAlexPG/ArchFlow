import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, act } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// ─── Mock api-client ─────────────────────────────────────────────────────────

const mockGet = vi.fn()
const mockPut = vi.fn()

vi.mock('../../lib/api-client', () => ({
  api: {
    get: (...args: unknown[]) => mockGet(...args),
    put: (...args: unknown[]) => mockPut(...args),
    post: vi.fn(),
    delete: vi.fn(),
    patch: vi.fn(),
  },
}))

// ─── Mock the workspace + auth stores ────────────────────────────────────────

vi.mock('../../stores/workspace-store', () => ({
  useWorkspaceStore: (selector: (s: { currentWorkspaceId: string }) => unknown) =>
    selector({ currentWorkspaceId: 'ws-1' }),
}))

vi.mock('../../stores/auth-store', () => ({
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

// ─── Stub the AppSidebar (it pulls in many unrelated queries) ────────────────

vi.mock('../../components/nav/AppSidebar', () => ({
  AppSidebar: () => <div data-testid="sidebar-stub" />,
}))

// ─── Stub useWorkspaces — it lives in use-api ───────────────────────────────

let mockRole: 'owner' | 'admin' | 'editor' | 'viewer' = 'admin'
const mockWorkspaces = () => [
  { id: 'ws-1', org_id: 'o-1', name: 'Test', slug: 'test', role: mockRole },
]
vi.mock('../../hooks/use-api', () => ({
  useWorkspaces: () => ({ data: mockWorkspaces() }),
}))

// ─── Import the page AFTER mocks ────────────────────────────────────────────

import { AgentsSettingsPage } from '../AgentsSettingsPage'

// ─── Fixtures ───────────────────────────────────────────────────────────────

const SETTINGS_FIXTURE = {
  litellm: {
    provider: 'openai',
    base_url: 'https://api.openai.com/v1',
    model_default: 'openai/gpt-4o-mini',
    has_key: false,
  },
  context: {
    threshold: 0.8,
    strategy: 'ladder',
    tool_result_trim_threshold_tokens: 4000,
  },
  analytics_consent: 'off',
  agent_edits_policy: 'ask',
  agents: {},
  model_pricing: {},
}

// ─── Helpers ────────────────────────────────────────────────────────────────

function makeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
}

function renderPage() {
  const client = makeClient()
  return render(
    <MemoryRouter>
      <QueryClientProvider client={client}>
        <AgentsSettingsPage />
      </QueryClientProvider>
    </MemoryRouter>,
  )
}

// ─── Suite ──────────────────────────────────────────────────────────────────

describe('AgentsSettingsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockRole = 'admin'
    mockGet.mockResolvedValue({ data: SETTINGS_FIXTURE })
    mockPut.mockImplementation((_url, body) => {
      // The backend returns the merged result; for the diff-only assertions
      // below we only need a sane shape.
      return Promise.resolve({
        data: { ...SETTINGS_FIXTURE, ...body },
      })
    })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('shows a loading state before settings resolve', () => {
    // Suspend the GET so the loading state stays visible.
    mockGet.mockImplementation(() => new Promise(() => {}))
    renderPage()
    expect(screen.getByTestId('agents-settings-loading')).toBeInTheDocument()
  })

  it('renders all the major sections after settings load', async () => {
    renderPage()
    await waitFor(() => {
      expect(screen.getByTestId('llm-provider')).toBeInTheDocument()
    })
    expect(screen.getByTestId('llm-base-url')).toBeInTheDocument()
    expect(screen.getByTestId('llm-model-default')).toBeInTheDocument()
    expect(screen.getByTestId('analytics-current-mode')).toHaveTextContent('off')
    expect(screen.getByTestId('per-agent-table')).toBeInTheDocument()
    expect(screen.getByTestId('model-pricing-table')).toBeInTheDocument()
    // Section 1 LLM provider value pre-filled from settings.
    expect(screen.getByTestId('llm-provider')).toHaveValue('openai')
    expect(screen.getByTestId('llm-model-default')).toHaveValue('openai/gpt-4o-mini')
  })

  it('shows the permission gate for non-admin users', () => {
    mockRole = 'editor'
    renderPage()
    expect(screen.getByTestId('permission-gate')).toBeInTheDocument()
    expect(screen.queryByTestId('llm-provider')).not.toBeInTheDocument()
    // Non-admin must not even fire the GET.
    expect(mockGet).not.toHaveBeenCalled()
  })

  it('opens the consent modal when toggling analytics from off → full and Cancel keeps original', async () => {
    renderPage()
    await waitFor(() => screen.getByTestId('analytics-full'))

    fireEvent.click(screen.getByTestId('analytics-full'))
    expect(screen.getByTestId('analytics-consent-modal')).toBeInTheDocument()

    fireEvent.click(screen.getByTestId('consent-cancel'))
    expect(screen.queryByTestId('analytics-consent-modal')).not.toBeInTheDocument()

    // Original consent value (off) preserved — `off` radio still checked.
    expect(screen.getByTestId('analytics-off')).toBeChecked()
    expect(screen.getByTestId('analytics-full')).not.toBeChecked()

    // Save should be disabled (no diff).
    expect(screen.getByTestId('save-btn')).toBeDisabled()
  })

  it('confirming the consent modal updates the consent value', async () => {
    renderPage()
    await waitFor(() => screen.getByTestId('analytics-full'))

    fireEvent.click(screen.getByTestId('analytics-full'))
    expect(screen.getByTestId('analytics-consent-modal')).toBeInTheDocument()

    // The radio inside the modal defaults to "full"; just confirm.
    fireEvent.click(screen.getByTestId('consent-confirm'))

    expect(screen.queryByTestId('analytics-consent-modal')).not.toBeInTheDocument()
    expect(screen.getByTestId('analytics-full')).toBeChecked()
    // Save now enabled because we have a diff.
    expect(screen.getByTestId('save-btn')).not.toBeDisabled()
  })

  it('Save sends only changed fields in the PUT body', async () => {
    renderPage()
    await waitFor(() => screen.getByTestId('llm-provider'))

    // Switching provider auto-derives base_url, so both fields end up in
    // the diff payload.
    fireEvent.change(screen.getByTestId('llm-provider'), {
      target: { value: 'anthropic' },
    })

    expect(screen.getByTestId('save-btn')).not.toBeDisabled()

    await act(async () => {
      fireEvent.click(screen.getByTestId('save-btn'))
    })

    await waitFor(() => expect(mockPut).toHaveBeenCalledOnce())
    const [url, body] = mockPut.mock.calls[0]
    expect(url).toBe('/agents/settings')
    expect(body).toEqual({
      litellm: {
        provider: 'anthropic',
        base_url: 'https://api.anthropic.com/v1',
      },
    })
  })

  it('Discard resets the draft to the original settings', async () => {
    renderPage()
    await waitFor(() => screen.getByTestId('llm-provider'))

    fireEvent.change(screen.getByTestId('llm-provider'), {
      target: { value: 'anthropic' },
    })
    expect(screen.getByTestId('llm-provider')).toHaveValue('anthropic')
    expect(screen.getByTestId('save-btn')).not.toBeDisabled()

    fireEvent.click(screen.getByTestId('discard-btn'))

    expect(screen.getByTestId('llm-provider')).toHaveValue('openai')
    expect(screen.getByTestId('save-btn')).toBeDisabled()
  })

  it('per-agent table edits update draft state and PUT body', async () => {
    renderPage()
    await waitFor(() => screen.getByTestId('agent-row-general'))

    fireEvent.change(screen.getByTestId('agent-general-model'), {
      target: { value: 'gpt-4o' },
    })
    expect(screen.getByTestId('agent-general-model')).toHaveValue('gpt-4o')

    await act(async () => {
      fireEvent.click(screen.getByTestId('save-btn'))
    })

    await waitFor(() => expect(mockPut).toHaveBeenCalledOnce())
    const [, body] = mockPut.mock.calls[0]
    expect(body.agents).toBeDefined()
    expect(body.agents.general.model).toBe('gpt-4o')
  })

  it('model pricing add row stores the entry and Save sends it', async () => {
    renderPage()
    await waitFor(() => screen.getByTestId('pricing-new-id'))

    fireEvent.change(screen.getByTestId('pricing-new-id'), {
      target: { value: 'claude-haiku-3-5' },
    })
    fireEvent.change(screen.getByTestId('pricing-new-input'), {
      target: { value: '0.80' },
    })
    fireEvent.change(screen.getByTestId('pricing-new-output'), {
      target: { value: '4.00' },
    })

    fireEvent.click(screen.getByTestId('pricing-add'))

    // Row now visible.
    expect(
      screen.getByTestId('pricing-row-claude-haiku-3-5'),
    ).toBeInTheDocument()

    await act(async () => {
      fireEvent.click(screen.getByTestId('save-btn'))
    })

    await waitFor(() => expect(mockPut).toHaveBeenCalledOnce())
    const [, body] = mockPut.mock.calls[0]
    expect(body.model_pricing).toEqual({
      'claude-haiku-3-5': {
        input_per_million: '0.80',
        output_per_million: '4.00',
      },
    })
  })

  it('shows "Saved" indicator when has_key is true', async () => {
    mockGet.mockResolvedValue({
      data: { ...SETTINGS_FIXTURE, litellm: { ...SETTINGS_FIXTURE.litellm, has_key: true } },
    })
    renderPage()
    await waitFor(() => {
      expect(screen.getByTestId('llm-api-key-saved')).toBeInTheDocument()
    })
    expect(screen.getByTestId('llm-api-key-saved')).toHaveTextContent('Saved')
  })

  it('selecting "off" from a non-off mode does NOT open the modal', async () => {
    mockGet.mockResolvedValue({
      data: { ...SETTINGS_FIXTURE, analytics_consent: 'full' },
    })
    renderPage()
    await waitFor(() => screen.getByTestId('analytics-off'))

    fireEvent.click(screen.getByTestId('analytics-off'))
    // No modal — opting out is a free action per spec.
    expect(screen.queryByTestId('analytics-consent-modal')).not.toBeInTheDocument()
    expect(screen.getByTestId('analytics-off')).toBeChecked()
  })
})
