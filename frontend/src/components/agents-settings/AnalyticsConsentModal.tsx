import { useState, useEffect } from 'react'
import type { AnalyticsConsent } from '../../hooks/use-agents-settings'

// Spec §2.5.1 mandates the modal text word-for-word — keep Ukrainian.
// If we ever localise, the dictionary key for this whole block is
// "agents.consent.modal".

interface Props {
  open: boolean
  /** Initial radio selection — "full" by default if user toggled to opt-in. */
  initialValue?: Exclude<AnalyticsConsent, 'off'> | 'full' | 'errors_only'
  onConfirm: (value: AnalyticsConsent) => void
  onCancel: () => void
}

// Inner component owns the `value` state. Wrapping it in a parent that
// only mounts it when `open` is true means each open is a fresh mount —
// no need for a useEffect to "reset on reopen", which would trip the
// react-hooks/set-state-in-effect lint rule.
export function AnalyticsConsentModal(props: Props) {
  if (!props.open) return null
  return <ModalBody {...props} />
}

function ModalBody({
  initialValue = 'full',
  onConfirm,
  onCancel,
}: Omit<Props, 'open'>) {
  const [value, setValue] = useState<AnalyticsConsent>(initialValue)

  // Esc closes; mirrors the `Modal` common component's behaviour.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCancel()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onCancel])

  return (
    <div
      data-testid="analytics-consent-modal"
      onClick={onCancel}
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/65 backdrop-blur-sm"
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-[520px] max-h-[85vh] overflow-y-auto rounded-lg border border-border-base bg-panel text-text-base shadow-popup"
      >
        <div className="px-5 py-4 border-b border-border-base">
          <h3 className="text-sm font-semibold">Включити аналітику агентів?</h3>
        </div>

        <div className="px-5 py-4 space-y-4 text-[12.5px] leading-relaxed text-text-2">
          <p>
            Це допомагає нам зробити агентів кращими: ми бачимо які запити погано
            спрацьовують і покращуємо логіку.
          </p>

          <div>
            <h4 className="text-[11px] uppercase tracking-wider text-text-3 mb-1">
              Що збирається
            </h4>
            <ul className="list-disc list-inside space-y-0.5">
              <li>Повідомлення між вами і агентом</li>
              <li>Виклики тулів (назви, аргументи, результати)</li>
              <li>Час виконання, кількість токенів, помилки</li>
            </ul>
          </div>

          <div>
            <h4 className="text-[11px] uppercase tracking-wider text-text-3 mb-1">
              Що НЕ збирається
            </h4>
            <ul className="list-disc list-inside space-y-0.5">
              <li>Жодних raw blob&apos;ів моделі окремо від ваших повідомлень</li>
              <li>Жодних credentials, API keys</li>
              <li>Жодних ваших файлів чи git-вмісту (Phase 2+)</li>
            </ul>
          </div>

          <div>
            <h4 className="text-[11px] uppercase tracking-wider text-text-3 mb-1">
              Куди йде
            </h4>
            <ul className="list-disc list-inside space-y-0.5">
              <li>Self-hosted Langfuse адмінів цього інстансу ArchFlow.</li>
              <li>Не передається третім сторонам.</li>
              <li>Не використовується для тренування моделей.</li>
            </ul>
          </div>

          <div className="pt-1">
            <h4 className="text-[11px] uppercase tracking-wider text-text-3 mb-2">
              Виберіть рівень
            </h4>
            <div className="space-y-1.5">
              <ConsentOption
                checked={value === 'full'}
                onSelect={() => setValue('full')}
                label="Повна"
                hint="всі агентні запити"
                testId="consent-radio-full"
              />
              <ConsentOption
                checked={value === 'errors_only'}
                onSelect={() => setValue('errors_only')}
                label="Лише з помилками"
                hint="тільки коли агент зламався"
                testId="consent-radio-errors_only"
              />
              <ConsentOption
                checked={value === 'off'}
                onSelect={() => setValue('off')}
                label="Вимкнути"
                hint="нічого не надсилати"
                testId="consent-radio-off"
              />
            </div>
          </div>
        </div>

        <div className="px-5 py-3 border-t border-border-base flex justify-end gap-2">
          <button
            onClick={onCancel}
            data-testid="consent-cancel"
            className="text-xs text-text-2 hover:text-text-base px-3 py-1.5"
          >
            Скасувати
          </button>
          <button
            onClick={() => onConfirm(value)}
            data-testid="consent-confirm"
            className="bg-coral hover:bg-coral-2 text-on-accent text-xs font-medium rounded px-3 py-1.5"
          >
            Підтвердити
          </button>
        </div>
      </div>
    </div>
  )
}

function ConsentOption({
  checked,
  onSelect,
  label,
  hint,
  testId,
}: {
  checked: boolean
  onSelect: () => void
  label: string
  hint: string
  testId: string
}) {
  return (
    <label className="flex items-start gap-2 cursor-pointer">
      <input
        type="radio"
        checked={checked}
        onChange={onSelect}
        data-testid={testId}
        className="mt-0.5"
      />
      <span>
        <span className="text-text-base">{label}</span>
        <span className="text-text-3"> — {hint}</span>
      </span>
    </label>
  )
}
