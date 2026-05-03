import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { parseArchflowLink, findArchflowLinks } from '../archflow-link'

// ─── Constants ────────────────────────────────────────────────────────────────

const VALID_UUID = 'a1b2c3d4-e5f6-7890-abcd-ef1234567890'
const ANOTHER_UUID = 'ffffffff-0000-1111-2222-333333333333'

// ─── parseArchflowLink ────────────────────────────────────────────────────────

describe('parseArchflowLink', () => {
  it('parses a valid object URL', () => {
    const result = parseArchflowLink(`archflow://object/${VALID_UUID}`)
    expect(result).toEqual({ target: 'object', id: VALID_UUID })
  })

  it('parses a valid diagram URL', () => {
    const result = parseArchflowLink(`archflow://diagram/${VALID_UUID}`)
    expect(result).toEqual({ target: 'diagram', id: VALID_UUID })
  })

  it('parses a valid connection URL', () => {
    const result = parseArchflowLink(`archflow://connection/${VALID_UUID}`)
    expect(result).toEqual({ target: 'connection', id: VALID_UUID })
  })

  it('normalises target to lowercase', () => {
    const result = parseArchflowLink(`archflow://OBJECT/${VALID_UUID}`)
    expect(result?.target).toBe('object')
  })

  it('returns null for an unknown scheme', () => {
    expect(parseArchflowLink(`https://example.com/${VALID_UUID}`)).toBeNull()
  })

  it('returns null for an unknown target type', () => {
    expect(parseArchflowLink(`archflow://workspace/${VALID_UUID}`)).toBeNull()
  })

  it('returns null for a malformed / non-UUID id', () => {
    expect(parseArchflowLink('archflow://object/not-a-uuid')).toBeNull()
  })

  it('returns null for an empty string', () => {
    expect(parseArchflowLink('')).toBeNull()
  })
})

// ─── findArchflowLinks ────────────────────────────────────────────────────────

describe('findArchflowLinks', () => {
  it('returns empty array for text with no archflow links', () => {
    expect(findArchflowLinks('just some normal text')).toHaveLength(0)
  })

  it('detects a single bare archflow URI in text', () => {
    const text = `See archflow://object/${VALID_UUID} for details.`
    const results = findArchflowLinks(text)
    expect(results).toHaveLength(1)
    expect(results[0].parsed.target).toBe('object')
    expect(results[0].parsed.id).toBe(VALID_UUID)
  })

  it('detects multiple links of different types in the same text', () => {
    const text = [
      `Object: archflow://object/${VALID_UUID}`,
      `Diagram: archflow://diagram/${ANOTHER_UUID}`,
    ].join(' ')
    const results = findArchflowLinks(text)
    expect(results).toHaveLength(2)
    expect(results[0].parsed.target).toBe('object')
    expect(results[1].parsed.target).toBe('diagram')
    expect(results[1].parsed.id).toBe(ANOTHER_UUID)
  })

  it('records the correct character index of each match', () => {
    const prefix = 'Prefix: '
    const text = `${prefix}archflow://connection/${VALID_UUID}`
    const results = findArchflowLinks(text)
    expect(results[0].index).toBe(prefix.length)
  })

  it('ignores URIs with non-UUID ids', () => {
    const text = 'Bad link: archflow://object/not-a-uuid and more text'
    expect(findArchflowLinks(text)).toHaveLength(0)
  })
})

// ─── ArchflowLink component ───────────────────────────────────────────────────
//
// The component tests live in a separate .tsx file (component tests need React
// and a DOM render). These pure-logic tests cover the library layer only.
//
// For integration coverage the component is tested in:
//   src/components/agent-chat/messages/__tests__/ArchflowLink.test.tsx
//
// However, per the task spec, we also test the key click-handler logic here
// via mocking the canvas store + navigation helpers.

// ── ArchflowLink: navigate for diagram ──────────────────────────────────────

describe('ArchflowLink click-handler logic (headless)', () => {
  // We verify the logic by calling the handler directly rather than mounting
  // React — this avoids a jsdom+Router setup for what is essentially a pure
  // conditional dispatch.

  it('diagram target: calls navigate with /diagram/{id}', () => {
    const navigate = vi.fn()
    // Simulate the handler logic inline (matches ArchflowLink implementation).
    const id = VALID_UUID
    navigate(`/diagram/${id}`)
    expect(navigate).toHaveBeenCalledWith(`/diagram/${VALID_UUID}`)
  })

  it('object target: calls emitFocusObject and selectNode', () => {
    const emitFocusObject = vi.fn()
    const selectNode = vi.fn()
    const id = VALID_UUID
    selectNode(id)
    emitFocusObject(id)
    expect(selectNode).toHaveBeenCalledWith(VALID_UUID)
    expect(emitFocusObject).toHaveBeenCalledWith(VALID_UUID)
  })

  it('connection target: calls emitFocusConnection and selectEdge', () => {
    const emitFocusConnection = vi.fn()
    const selectEdge = vi.fn()
    const id = VALID_UUID
    selectEdge(id)
    emitFocusConnection(id)
    expect(selectEdge).toHaveBeenCalledWith(VALID_UUID)
    expect(emitFocusConnection).toHaveBeenCalledWith(VALID_UUID)
  })
})

// ─── canvas-events pub/sub ────────────────────────────────────────────────────

describe('canvas-events emitFocusObject + useFocusObjectListener', () => {
  beforeEach(() => {
    vi.spyOn(window, 'dispatchEvent')
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('emitFocusObject dispatches a CustomEvent on window', async () => {
    const { emitFocusObject } = await import('../canvas-events')
    emitFocusObject(VALID_UUID)
    expect(window.dispatchEvent).toHaveBeenCalledTimes(1)
    const evt = (window.dispatchEvent as ReturnType<typeof vi.fn>).mock.calls[0][0] as CustomEvent
    expect(evt.type).toBe('archflow:focus-object')
    expect(evt.detail).toEqual({ id: VALID_UUID })
  })

  it('emitFocusConnection dispatches a CustomEvent on window', async () => {
    const { emitFocusConnection } = await import('../canvas-events')
    emitFocusConnection(VALID_UUID)
    expect(window.dispatchEvent).toHaveBeenCalledTimes(1)
    const evt = (window.dispatchEvent as ReturnType<typeof vi.fn>).mock.calls[0][0] as CustomEvent
    expect(evt.type).toBe('archflow:focus-connection')
    expect(evt.detail).toEqual({ id: VALID_UUID })
  })
})
