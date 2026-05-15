import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const css = readFileSync('src/index.css', 'utf8')
const exportToolbar = readFileSync('src/components/toolbar/ExportToolbar.tsx', 'utf8')
const flowsPanel = readFileSync('src/components/toolbar/FlowsPanel.tsx', 'utf8')
const filterToolbar = readFileSync('src/components/toolbar/FilterToolbar.tsx', 'utf8')
const addObjectToolbar = readFileSync('src/components/toolbar/AddObjectToolbar.tsx', 'utf8')
const addObjectFab = readFileSync('src/components/canvas/AddObjectFAB.tsx', 'utf8')
const richTextEditor = readFileSync('src/components/common/RichTextEditor.tsx', 'utf8')

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

  it('keeps the add-object popover viewport constrained and theme-tokened', () => {
    expect(css).toContain('.add-object-toolbar__popover')
    expect(css).toContain('position: fixed')
    expect(css).toContain('top: clamp(12px, calc(50vh - 220px), calc(100vh - 452px))')
    expect(css).toContain('max-height: calc(100vh - 24px)')
    expect(css).toContain('min-height: 0')
    expect(css).toContain('overflow-y: auto')
    expect(css).toContain('background: var(--color-panel)')
    expect(addObjectToolbar).toContain('className="add-object-toolbar__popover"')
    expect(addObjectToolbar).not.toContain("background: '#171717'")
    expect(addObjectToolbar).not.toContain("background: '#262626'")
    expect(addObjectFab).toContain('popupMetrics')
    expect(addObjectFab).toContain('window.innerHeight')
    expect(addObjectFab).toContain('window.innerWidth')
    expect(addObjectFab).toContain('bottom = 12')
    expect(addObjectFab).not.toContain('top: 72,')
    expect(addObjectFab).not.toContain('bottom: 72,')
  })

  it('keeps the rich text editor on theme classes instead of dark inline colors', () => {
    expect(css).toContain('.rich-text-editor')
    expect(css).toContain('color: var(--color-text-base)')
    expect(css).toContain('background: var(--color-panel)')
    expect(richTextEditor).toContain("className=\"rich-text-editor\"")
    expect(richTextEditor).toContain("class: 'rich-text-editor__content'")
    expect(richTextEditor).not.toContain('#171717')
    expect(richTextEditor).not.toContain('#e5e5e5')
    expect(richTextEditor).not.toContain('#333')
  })
})
