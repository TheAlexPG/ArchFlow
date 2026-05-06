// ─── canvas-events: lightweight pub/sub for imperative canvas commands ────────
//
// The agent chat panel lives outside the ReactFlowProvider tree, so it cannot
// call `useReactFlow()` directly. This module provides a minimal event bus that
// lets any component emit a "focus node" or "focus connection" command and lets
// ArchFlowCanvas (which IS inside the provider) listen and act on it.
//
// Pattern:
//   1. ArchflowLink calls `emitFocusObject(id)` / `emitFocusConnection(id)`.
//   2. CanvasInner calls `useFocusObjectListener` / `useFocusConnectionListener`
//      which subscribe on mount and call `fitView({ nodes: [{ id }] })`.
//
// This is intentionally simpler than a Zustand slice: the canvas action is
// fire-and-forget with no persistent state — a one-time imperative command,
// not a derived view.

import { useEffect } from 'react'

// ─── Event names ─────────────────────────────────────────────────────────────

const FOCUS_OBJECT_EVENT = 'archflow:focus-object'
const FOCUS_CONNECTION_EVENT = 'archflow:focus-connection'

// ─── Emitters (call from outside the canvas) ─────────────────────────────────

/** Tell the active canvas to centre on and select an object node. */
export function emitFocusObject(id: string): void {
  window.dispatchEvent(new CustomEvent(FOCUS_OBJECT_EVENT, { detail: { id } }))
}

/** Tell the active canvas to centre on and select a connection edge. */
export function emitFocusConnection(id: string): void {
  window.dispatchEvent(new CustomEvent(FOCUS_CONNECTION_EVENT, { detail: { id } }))
}

// ─── Listeners (mount inside CanvasInner / ReactFlowProvider tree) ────────────

/**
 * Subscribe to `archflow:focus-object` events.
 * The callback receives the object UUID to focus on.
 * Automatically unsubscribes on unmount.
 */
export function useFocusObjectListener(callback: (id: string) => void): void {
  useEffect(() => {
    const handler = (e: Event) => {
      const id = (e as CustomEvent<{ id: string }>).detail?.id
      if (id) callback(id)
    }
    window.addEventListener(FOCUS_OBJECT_EVENT, handler)
    return () => window.removeEventListener(FOCUS_OBJECT_EVENT, handler)
  }, [callback])
}

/**
 * Subscribe to `archflow:focus-connection` events.
 * The callback receives the connection UUID to focus on.
 * Automatically unsubscribes on unmount.
 */
export function useFocusConnectionListener(callback: (id: string) => void): void {
  useEffect(() => {
    const handler = (e: Event) => {
      const id = (e as CustomEvent<{ id: string }>).detail?.id
      if (id) callback(id)
    }
    window.addEventListener(FOCUS_CONNECTION_EVENT, handler)
    return () => window.removeEventListener(FOCUS_CONNECTION_EVENT, handler)
  }, [callback])
}
