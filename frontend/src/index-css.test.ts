import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const css = readFileSync('src/index.css', 'utf8')
const exportToolbar = readFileSync('src/components/toolbar/ExportToolbar.tsx', 'utf8')
const flowsPanel = readFileSync('src/components/toolbar/FlowsPanel.tsx', 'utf8')
const filterToolbar = readFileSync('src/components/toolbar/FilterToolbar.tsx', 'utf8')

describe('light theme legacy control compatibility CSS', () => {
  it('keeps legacy dark button/control utilities scoped to light theme tokens', () => {
    expect(css).toContain(":root[data-theme='light'] .bg-blue-600")
    expect(css).toContain(":root[data-theme='light'] .hover\\:bg-blue-500:hover")
    expect(css).toContain(":root[data-theme='light'] .bg-amber-600")
    expect(css).toContain(":root[data-theme='light'] .bg-neutral-600")
    expect(css).toContain(":root[data-theme='light'] .bg-black\\/60")
    expect(css).toContain(":root[data-theme='light'] .disabled\\:opacity-40:disabled")
    expect(css).toContain('--context-menu-bg: var(--color-panel)')
  })

  it('does not add unscoped overrides for legacy button fills', () => {
    expect(css).not.toMatch(/^\.bg-blue-600\s*\{/m)
    expect(css).not.toMatch(/^\.bg-amber-600\s*\{/m)
    expect(css).not.toMatch(/^\.bg-black\\\/60\s*\{/m)
  })

  it('keeps inline diagram toolbar controls on theme tokens', () => {
    expect(exportToolbar).toContain("background: open ? 'var(--control-button-hover)' : 'var(--control-button-bg)'")
    expect(exportToolbar).toContain("background: 'var(--color-panel)'")
    expect(flowsPanel).toContain("background: open ? 'var(--control-button-hover)' : 'var(--control-button-bg)'")
    expect(flowsPanel).toContain("background: 'var(--color-panel)'")
    expect(filterToolbar).toContain("background: 'var(--color-panel)'")
    expect(filterToolbar).not.toContain("background: '#171717'")
    expect(flowsPanel).not.toContain("background: open ? '#333' : '#262626'")
  })
})
