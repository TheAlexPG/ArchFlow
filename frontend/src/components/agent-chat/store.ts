import { create } from 'zustand'
import { persist } from 'zustand/middleware'

import type { ChatMode } from './types'

// ─── Types ─────────────────────────────────────────────────────────────────

export type BubbleState = 'closed' | 'open' | 'expanded'
export type { ChatMode }

interface AgentChatStore {
  // UI state — persisted to localStorage
  bubbleState: BubbleState
  size: { width: number; height: number }
  mode: ChatMode

  // Ephemeral — session identity, not persisted
  activeSessionId: string | null

  // Actions
  open: () => void
  close: () => void
  expand: () => void
  setMode: (mode: ChatMode) => void
  setSize: (size: { width: number; height: number }) => void
  setActiveSessionId: (id: string | null) => void
}

// ─── Defaults ──────────────────────────────────────────────────────────────

const DEFAULT_SIZE = { width: 480, height: 640 }

// ─── Store ─────────────────────────────────────────────────────────────────

export const useAgentChatStore = create<AgentChatStore>()(
  persist(
    (set) => ({
      // Persisted UI defaults
      bubbleState: 'closed',
      size: DEFAULT_SIZE,
      // Default to Full so the agent operates in the user's current context
      // out of the box; users can downshift to read_only manually.
      mode: 'full',

      // Ephemeral
      activeSessionId: null,

      // Actions
      open: () => set({ bubbleState: 'open' }),
      close: () => set({ bubbleState: 'closed' }),
      expand: () => set({ bubbleState: 'expanded' }),
      setMode: (mode) => set({ mode }),
      setSize: (size) => set({ size }),
      setActiveSessionId: (id) => set({ activeSessionId: id }),
    }),
    {
      name: 'agent-chat-ui',
      // Only persist the UI state — session identity is ephemeral
      partialize: (s) => ({
        bubbleState: s.bubbleState,
        size: s.size,
        mode: s.mode,
      }),
    },
  ),
)
