import { useNavigate } from 'react-router-dom'
import { useDraftsForDiagram } from '../../hooks/use-api'
import { cn } from '../../utils/cn'
import { useChatContext } from './hooks/use-chat-context'
import { type ChatMode, useAgentChatStore } from './store'
import { SessionPicker } from './SessionPicker'

// ─── ModeToggle ─────────────────────────────────────────────────────────────

interface ModeToggleProps {
  value: ChatMode
  onChange: (mode: ChatMode) => void
}

function ModeToggle({ value, onChange }: ModeToggleProps) {
  return (
    <div className="flex items-center gap-0.5 mt-0.5" role="radiogroup" aria-label="Chat mode">
      {(['full', 'read_only'] as const).map((m) => {
        const label = m === 'full' ? 'Full' : 'Read-only'
        const active = value === m
        return (
          <button
            key={m}
            role="radio"
            aria-checked={active}
            data-testid={`mode-toggle-${m}`}
            onClick={() => onChange(m)}
            className={cn(
              'px-1.5 py-0.5 rounded text-[10px] font-mono transition-all duration-100',
              active
                ? 'bg-coral/20 text-coral border border-coral/30'
                : 'text-text-3 hover:text-text-2 border border-transparent hover:border-border-base',
            )}
          >
            {active ? '◉' : '○'} {label}
          </button>
        )
      })}
    </div>
  )
}

// ─── IconButton ─────────────────────────────────────────────────────────────

interface IconButtonProps {
  title: string
  onClick: () => void
  children: React.ReactNode
  'data-testid'?: string
}

function IconButton({ title, onClick, children, 'data-testid': testId }: IconButtonProps) {
  return (
    <button
      title={title}
      aria-label={title}
      data-testid={testId}
      onClick={onClick}
      className={cn(
        'w-6 h-6 flex items-center justify-center rounded',
        'text-text-3 hover:text-text-base hover:bg-surface-hi',
        'transition-colors duration-100 text-[12px]',
        'focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-coral/50',
      )}
    >
      {children}
    </button>
  )
}

// ─── WorkingInDropdown ───────────────────────────────────────────────────────
//
// Shown only on diagram pages. Lets the user switch the agent context between
// the live diagram and any open drafts without leaving the chat bubble.

function WorkingInDropdown() {
  const ctx = useChatContext()
  const navigate = useNavigate()
  const { data: drafts } = useDraftsForDiagram(
    ctx.kind === 'diagram' || ctx.kind === 'object' ? (ctx.kind === 'diagram' ? ctx.id : ctx.parent_diagram_id) : undefined,
  )

  const diagramId =
    ctx.kind === 'diagram'
      ? ctx.id
      : ctx.kind === 'object'
        ? ctx.parent_diagram_id
        : undefined

  if (!diagramId) return null

  const currentDraftId = ctx.draft_id ?? 'live'

  function handleChange(e: React.ChangeEvent<HTMLSelectElement>) {
    const v = e.target.value
    if (v === 'live') {
      // Strip ?draft= param while keeping other params
      const url = new URL(window.location.href)
      url.searchParams.delete('draft')
      navigate(url.pathname + (url.search ? url.search : ''))
    } else {
      navigate(`?draft=${v}`)
    }
  }

  return (
    <div
      data-testid="working-in-dropdown"
      className="flex items-center gap-1 mt-1"
    >
      <span className="text-[10px] text-text-3 font-mono shrink-0">Working in:</span>
      <select
        data-testid="working-in-select"
        value={currentDraftId}
        onChange={handleChange}
        className={cn(
          'text-[10px] font-mono rounded px-1 py-0.5 max-w-[130px] truncate',
          'bg-surface-hi border border-border-base text-text-base',
          'focus:outline-none focus:ring-1 focus:ring-coral/50',
          'cursor-pointer',
        )}
      >
        <option value="live">Live diagram</option>
        {drafts?.map((d) => (
          <option key={d.draft_id} value={d.draft_id}>
            {d.draft_name}
          </option>
        ))}
      </select>
    </div>
  )
}

// ─── ChatHeader ─────────────────────────────────────────────────────────────
//
// Slot note for task-041 (ContextResolver):
//   Add <ChatContextPill /> (from hooks/use-chat-context) between ModeToggle
//   and the window-control buttons. The pill reads the current route + canvas
//   selection via useChatContext() and needs a <Router> ancestor — hence it is
//   deferred to task-041 rather than bundled here.

export function ChatHeader() {
  const { mode, setMode, expand, open, close, bubbleState } = useAgentChatStore()

  return (
    <div
      data-testid="chat-header"
      className={cn(
        'flex items-center justify-between px-3 py-2',
        'border-b border-border-base',
        'bg-panel rounded-t-xl',
        'flex-shrink-0',
      )}
    >
      {/* Left: title + session picker + mode toggle + working-in */}
      <div className="flex flex-col gap-0">
        <h3 className="text-[13px] font-medium text-text-base leading-tight flex items-center gap-1.5">
          <span aria-hidden="true">🤖</span>
          ArchFlow Agent
          <SessionPicker />
        </h3>
        <ModeToggle value={mode} onChange={setMode} />
        <WorkingInDropdown />
      </div>

      {/* Right: window controls */}
      <div className="flex items-center gap-0.5">
        {bubbleState !== 'expanded' && (
          <IconButton title="Expand" onClick={expand} data-testid="btn-expand">
            ⛶
          </IconButton>
        )}
        {bubbleState === 'expanded' && (
          <IconButton title="Restore" onClick={open} data-testid="btn-restore">
            —
          </IconButton>
        )}
        {bubbleState === 'open' && (
          <IconButton title="Minimize" onClick={close} data-testid="btn-minimize">
            —
          </IconButton>
        )}
        <IconButton title="Close" onClick={close} data-testid="btn-close">
          ✕
        </IconButton>
      </div>
    </div>
  )
}
