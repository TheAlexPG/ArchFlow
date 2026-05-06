import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { AgentsSection } from '../AgentsSection'
import { AgentsA2ASection } from '../AgentsA2ASection'
import { DocsPage } from '../../../DocsPage'

// DocsLayout uses IntersectionObserver and scrollTo which are not in jsdom.
const mockObserve = vi.fn()
const mockDisconnect = vi.fn()
vi.stubGlobal(
  'IntersectionObserver',
  vi.fn().mockImplementation(() => ({
    observe: mockObserve,
    disconnect: mockDisconnect,
    unobserve: vi.fn(),
  })),
)

// jsdom does not implement scrollTo on elements — stub it globally.
Element.prototype.scrollTo = vi.fn()

describe('AgentsSection', () => {
  it('renders key headings and content', () => {
    render(<AgentsSection />)

    expect(screen.getByRole('heading', { name: /AI Agents/i })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /Available agents/i })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /How to use/i })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /Permissions/i })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /Drafts/i })).toBeInTheDocument()
    expect(screen.getByText(/General/)).toBeInTheDocument()
    expect(screen.getByText(/Researcher/)).toBeInTheDocument()
    expect(screen.getByText(/Diagram-explainer/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /recommended workflow/i })).toHaveAttribute(
      'href',
      '#agents-recommended-workflow',
    )
  })
})

describe('AgentsA2ASection', () => {
  it('renders key headings and the curl code block', () => {
    render(<AgentsA2ASection />)

    expect(screen.getByRole('heading', { name: /Agent-to-Agent/i })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /Quick start/i })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /Event protocol/i })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /Idempotency/i })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /Reconnect/i })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /Rate limits/i })).toBeInTheDocument()

    // Code block should contain curl commands
    const pre = document.querySelector('pre')
    expect(pre).toBeInTheDocument()
    expect(pre?.textContent).toContain('curl')
    expect(pre?.textContent).toContain('agents:read')
    expect(pre?.textContent).toContain('agents:write')
  })
})

describe('DocsPage TOC', () => {
  it('includes agents, agents-recommended-workflow, and agents-a2a entries', () => {
    render(
      <MemoryRouter>
        <DocsPage />
      </MemoryRouter>,
    )

    // The TOC renders anchor links — check for the label text
    const tocLinks = screen.getAllByRole('link')
    const labels = tocLinks.map((l) => l.textContent?.trim())

    expect(labels).toContain('AI Agents')
    expect(labels).toContain('Agent workflow')
    expect(labels).toContain('A2A API')
  })
})
