import { useNavigate } from 'react-router-dom'
import { cn } from '../../utils/cn'
import { useCurrentMemberRole } from '../../hooks/use-api'

// ─── AgentAccessUpgradeModal ────────────────────────────────────────────────
//
// Shown when the user tries to switch the chat into Full mode but their
// workspace membership only grants `agent_access='read_only'` (or 'none').
//
// Decision tree:
//   role ∈ {owner, admin}  → CTA navigates to /members so the user can
//                            self-upgrade their own row.
//   role ∈ {editor, …}     → no self-serve path: show contact-admin copy.
//
// Backed by a simple fixed overlay; uses tailwind tokens already in use
// elsewhere in the agent-chat panel so it visually fits the bubble.

interface AgentAccessUpgradeModalProps {
  open: boolean
  onClose: () => void
}

export function AgentAccessUpgradeModal({ open, onClose }: AgentAccessUpgradeModalProps) {
  const navigate = useNavigate()
  const role = useCurrentMemberRole()
  const canSelfUpgrade = role === 'owner' || role === 'admin'

  if (!open) return null

  const handleGoToSettings = () => {
    onClose()
    navigate('/members')
  }

  return (
    <div
      data-testid="agent-access-upgrade-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="agent-access-upgrade-title"
      onClick={onClose}
      className={cn(
        'fixed inset-0 z-[60]',
        'flex items-center justify-center',
        'bg-black/50',
        'animate-[fade-in_0.15s_ease-out_forwards]',
      )}
    >
      <div
        data-testid="agent-access-upgrade-modal"
        onClick={(e) => e.stopPropagation()}
        className={cn(
          'w-[min(440px,90vw)]',
          'bg-panel border border-border-base rounded-xl',
          'shadow-window p-5',
          'flex flex-col gap-3',
        )}
      >
        <h2
          id="agent-access-upgrade-title"
          className="text-[15px] font-medium text-text-base flex items-center gap-2"
        >
          <span aria-hidden="true">🔒</span>
          Full access потрібен
        </h2>

        <p className="text-[13px] text-text-2 leading-relaxed">
          Ваш рівень доступу до агента у цьому робочому просторі —{' '}
          <span className="font-mono text-coral">read-only</span>. Це означає, що
          агент може <strong>відповідати на запитання</strong> та{' '}
          <strong>досліджувати модель</strong>, але не може створювати, редагувати
          чи видаляти об&apos;єкти й зв&apos;язки.
        </p>

        {canSelfUpgrade ? (
          <p className="text-[13px] text-text-2 leading-relaxed">
            Ви — <span className="font-mono">{role}</span> цього робочого простору
            і можете самі підвищити рівень доступу у налаштуваннях учасників.
          </p>
        ) : (
          <p className="text-[13px] text-text-2 leading-relaxed">
            Зверніться до <strong>owner</strong> або <strong>admin</strong>{' '}
            робочого простору, щоб вони підвищили вам{' '}
            <span className="font-mono">agent_access</span> до{' '}
            <span className="font-mono text-coral">full</span> у вкладці Members.
          </p>
        )}

        <div className="flex items-center justify-end gap-2 mt-2">
          <button
            data-testid="agent-access-upgrade-dismiss"
            onClick={onClose}
            className={cn(
              'px-3 py-1.5 rounded text-[12px]',
              'text-text-2 hover:text-text-base hover:bg-surface-hi',
              'transition-colors duration-100',
            )}
          >
            Зрозуміло
          </button>
          {canSelfUpgrade && (
            <button
              data-testid="agent-access-upgrade-cta"
              onClick={handleGoToSettings}
              className={cn(
                'px-3 py-1.5 rounded text-[12px] font-medium',
                'bg-coral/20 text-coral border border-coral/30',
                'hover:bg-coral/30 transition-colors duration-100',
              )}
            >
              Перейти до Members →
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
