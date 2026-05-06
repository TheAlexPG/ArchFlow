import { cn } from '../../../utils/cn'

// ─── UserMessage ────────────────────────────────────────────────────────────
//
// Right-aligned bubble for user-authored input. Phase 1 has no markdown for
// the user side — we render text verbatim, preserving newlines.

interface UserMessageProps {
  text: string
}

export function UserMessage({ text }: UserMessageProps) {
  return (
    <div className="flex justify-end" data-testid="user-message">
      <div
        className={cn(
          'max-w-[80%] rounded-lg px-3 py-2',
          'bg-coral/15 border border-coral/25',
          'text-[13px] text-text-base leading-snug whitespace-pre-wrap break-words',
        )}
      >
        {text}
      </div>
    </div>
  )
}
