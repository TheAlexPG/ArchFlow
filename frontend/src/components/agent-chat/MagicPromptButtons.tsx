import { cn } from '../../utils/cn'
import { useAgentStream } from './hooks/use-agent-stream'
import { useChatContext } from './hooks/use-chat-context'
import { useAgentChatStore } from './store'

// ─── MagicPromptButtons ─────────────────────────────────────────────────────
//
// Empty-chat affordance shown when there are zero events in the current
// session. Each button is a one-tap launcher for a canned prompt — the
// click handler hits the exact same submit path as ChatComposer.send()
// (``stream.startStream('general', { context, message, mode })``), so the
// optimistic user message echo + downstream rendering are identical to
// typing the text manually.
//
// Disabled when ``ctx.kind === 'none'`` (no workspace open) — same gating
// the composer uses, so the affordance can't fire a chat with no context.
//
// Inline SVG icons match the project's existing pattern (NodeIndicator,
// ChatComposer): no new dependency, tinted via currentColor.

interface MagicPrompt {
  id: string
  label: string
  prompt: string
  icon: 'sparkle' | 'wand' | 'compass' | 'puzzle'
}

// 4 prompts chosen to match what the General Architecture Agent
// (supervisor + researcher + planner + diagram-agent) naturally handles:
//
//   - "Describe this diagram"     → researcher's bread-and-butter (read-only fact-finding).
//   - "Suggest improvements"      → researcher + critic-style review, no mutations required.
//   - "Add a new component"       → diagram-agent flow, with planner if it's structural.
//   - "Help me design a system"   → planner-driven multi-step build, the supervisor's
//                                   marquee path.
//
// Deliberately skipping "Explain a component" because it forces the user
// to pick one in a follow-up turn before any work happens — feels more
// like a slash command than a starter.
const PROMPTS: MagicPrompt[] = [
  {
    id: 'describe',
    label: 'Describe this diagram',
    prompt:
      "Describe what's currently on this diagram. Identify the key components, their relationships, and the architectural intent.",
    icon: 'compass',
  },
  {
    id: 'design',
    label: 'Help me design a system',
    prompt:
      'Help me design a system architecture. Ask me clarifying questions about requirements, then propose a high-level structure.',
    icon: 'wand',
  },
  {
    id: 'improve',
    label: 'Suggest improvements',
    prompt:
      'Review the current architecture and suggest concrete improvements for scalability, maintainability, and clarity.',
    icon: 'sparkle',
  },
  {
    id: 'add',
    label: 'Add a new component',
    prompt:
      'I want to add a new component to this system. Walk me through the options based on the existing architecture.',
    icon: 'puzzle',
  },
]

export function MagicPromptButtons() {
  const stream = useAgentStream()
  const ctx = useChatContext()
  const mode = useAgentChatStore((s) => s.mode)

  const isDisabled = ctx.kind === 'none' || stream.isStreaming

  // Reuses the exact same submit invocation as ChatComposer.send():
  //   stream.startStream('general', { context: ctx, message, mode })
  // The optimistic user-message echo lives inside startStream itself, so
  // the transcript looks identical to a typed message.
  const send = (message: string) => {
    if (isDisabled) return
    stream.startStream('general', { context: ctx, message, mode })
  }

  return (
    <div
      data-testid="magic-prompt-buttons"
      className="flex-1 flex flex-col items-center justify-center px-6 py-8 min-h-0"
    >
      <div className="flex flex-col items-center gap-1.5 mb-5">
        <span aria-hidden="true" className="text-2xl">
          ✨
        </span>
        <p className="text-[12px] text-text-2 font-mono">How can I help?</p>
        <p className="text-[10.5px] text-text-4 font-mono">
          Pick a starter or type your own message below.
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 w-full max-w-[420px]">
        {PROMPTS.map((p) => (
          <button
            key={p.id}
            type="button"
            data-testid={`magic-prompt-${p.id}`}
            onClick={() => send(p.prompt)}
            disabled={isDisabled}
            title={p.prompt}
            className={cn(
              'group inline-flex items-center gap-2',
              'px-3 py-2 rounded-md',
              'bg-surface border border-border-base',
              'text-left text-[12px] text-text-2 font-mono',
              'hover:bg-surface-hi hover:border-coral/40 hover:text-text-1',
              'transition-colors duration-100',
              'disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-surface',
              'focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-coral/50',
            )}
          >
            <PromptIcon kind={p.icon} />
            <span className="truncate">{p.label}</span>
          </button>
        ))}
      </div>
    </div>
  )
}

// ─── PromptIcon ─────────────────────────────────────────────────────────────
//
// Inline SVGs (24×24 viewbox, 1.8 stroke). Matches the ad-hoc inline
// pattern used in NodeIndicator.tsx so we don't pull a new icon library.
// Tinted via currentColor so hover states bleed through without extra
// classes.

function PromptIcon({ kind }: { kind: MagicPrompt['icon'] }) {
  const cls = 'w-3.5 h-3.5 shrink-0 text-coral/70 group-hover:text-coral'
  switch (kind) {
    case 'sparkle':
      return (
        <svg viewBox="0 0 24 24" className={cls} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <path d="M12 3l1.8 4.5L18 9l-4.2 1.5L12 15l-1.8-4.5L6 9l4.2-1.5z" />
          <path d="M19 15l.8 2 2 .8-2 .8L19 21l-.8-2.4-2-.8 2-.8z" />
        </svg>
      )
    case 'wand':
      return (
        <svg viewBox="0 0 24 24" className={cls} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <path d="M15 4l5 5-12 12-5-5z" />
          <path d="M14 5l5 5" />
          <path d="M20 3v2M22 4h-2M3 14v2M5 15H3" />
        </svg>
      )
    case 'compass':
      return (
        <svg viewBox="0 0 24 24" className={cls} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <circle cx="12" cy="12" r="9" />
          <path d="M15.5 8.5l-2 5-5 2 2-5z" />
        </svg>
      )
    case 'puzzle':
      return (
        <svg viewBox="0 0 24 24" className={cls} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <path d="M11 4a2 2 0 1 1 4 0v1h3a1 1 0 0 1 1 1v3h1a2 2 0 1 1 0 4h-1v3a1 1 0 0 1-1 1h-3v-1a2 2 0 1 0-4 0v1H7a1 1 0 0 1-1-1v-3H5a2 2 0 1 1 0-4h1V6a1 1 0 0 1 1-1h4z" />
        </svg>
      )
  }
}
