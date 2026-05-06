// Inline popover exports + singleton portal helpers.
//
// openInlineExplainer / openInlineResearcher mount exactly one popover at a
// time via a dedicated container div appended to document.body.  A second
// call before the first is closed will unmount the previous instance first.

import { createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { InlineExplainerPopover } from './InlineExplainerPopover'
import { InlineResearcherPopover } from './InlineResearcherPopover'

export { InlineExplainerPopover } from './InlineExplainerPopover'
export { InlineResearcherPopover } from './InlineResearcherPopover'

// ─── Singleton state ───────────────────────────────────────────────────────

let activeRoot: Root | null = null
let activeContainer: HTMLDivElement | null = null

function mountSingleton(element: React.ReactElement) {
  // Unmount any existing popover before mounting a new one.
  destroySingleton()

  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)
  root.render(element)
  activeRoot = root
  activeContainer = container
}

function destroySingleton() {
  if (activeRoot) {
    // Schedule unmount on the next microtask so React can flush cleanly.
    const root = activeRoot
    const container = activeContainer
    activeRoot = null
    activeContainer = null
    setTimeout(() => {
      root.unmount()
      container?.remove()
    }, 0)
  }
}

// ─── Public openers ────────────────────────────────────────────────────────

export function openInlineExplainer(objectId: string, anchorEl: HTMLElement): void {
  mountSingleton(
    createElement(InlineExplainerPopover, {
      objectId,
      anchorEl,
      onClose: destroySingleton,
    }),
  )
}

export function openInlineResearcher(objectId: string, anchorEl: HTMLElement): void {
  mountSingleton(
    createElement(InlineResearcherPopover, {
      objectId,
      anchorEl,
      onClose: destroySingleton,
    }),
  )
}
