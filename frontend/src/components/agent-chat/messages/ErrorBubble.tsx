import { cn } from '../../../utils/cn'

// ─── ErrorBubble ───────────────────────────────────────────────────────────
//
// Red-tinted error card. If the server flagged the error as `retriable`,
// we expose a [Retry] button — the actual retry logic is delegated to the
// caller via `onRetry` (typically wired to `stream.retry()`).

interface ErrorBubbleProps {
  code: string
  message: string
  retriable?: boolean
  onRetry?: () => void
}

export function ErrorBubble({ code, message, retriable, onRetry }: ErrorBubbleProps) {
  return (
    <div
      data-testid="error-bubble"
      data-error-code={code}
      data-retriable={retriable ? 'true' : 'false'}
      className={cn(
        'flex flex-col gap-2 px-3 py-2 rounded-lg',
        'bg-red-500/10 border border-red-500/40',
        'text-[12px] text-red-300',
      )}
    >
      <div className="flex items-start gap-2">
        <span aria-hidden="true" className="mt-0.5">
          ✗
        </span>
        <div className="flex-1 leading-snug">
          <div className="font-medium font-mono text-[11px] uppercase tracking-wide text-red-400">
            {code}
          </div>
          <div className="text-text-base mt-0.5">{message}</div>
        </div>
      </div>
      {retriable && onRetry && (
        <div>
          <button
            type="button"
            onClick={onRetry}
            data-testid="error-bubble-retry"
            className={cn(
              'px-2.5 py-1 rounded text-[11px] font-medium',
              'bg-red-500/15 text-red-300 border border-red-500/40',
              'hover:bg-red-500/25 transition-colors duration-100',
            )}
          >
            Retry
          </button>
        </div>
      )}
    </div>
  )
}
