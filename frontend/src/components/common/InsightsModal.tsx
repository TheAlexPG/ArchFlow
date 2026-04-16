import { useEffect } from 'react'
import { createPortal } from 'react-dom'
import { useGetInsights, type ObjectInsights } from '../../hooks/use-api'
import type { ModelObject } from '../../types/model'

interface InsightsModalProps {
  object: ModelObject
  onClose: () => void
}

export function InsightsModal({ object, onClose }: InsightsModalProps) {
  const mutation = useGetInsights()

  // Kick off the AI call on mount.
  useEffect(() => {
    mutation.mutate(object.id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [object.id])

  // ESC closes
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  return createPortal(
    <div
      onClick={onClose}
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.7)',
        zIndex: 10001,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 24,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: 'min(640px, 100%)',
          maxHeight: '85vh',
          background: '#171717',
          border: '1px solid #333',
          borderRadius: 10,
          boxShadow: '0 12px 40px rgba(0,0,0,0.6)',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '14px 18px',
            borderBottom: '1px solid #262626',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontSize: 18 }}>✨</span>
            <div>
              <div style={{ fontSize: 11, color: '#737373', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                Insights
              </div>
              <div style={{ fontSize: 14, color: '#f5f5f5', fontWeight: 600 }}>
                {object.name}
              </div>
            </div>
          </div>
          <button
            onClick={onClose}
            style={{
              background: 'transparent',
              border: 'none',
              color: '#737373',
              fontSize: 20,
              cursor: 'pointer',
            }}
          >
            ×
          </button>
        </div>

        <div
          style={{
            padding: 18,
            overflowY: 'auto',
            color: '#d4d4d4',
            fontSize: 13,
            lineHeight: 1.55,
          }}
        >
          {mutation.isPending && <LoadingView />}
          {mutation.isError && (
            <ErrorView error={(mutation.error as Error)?.message || 'Unknown error'} />
          )}
          {mutation.data && <InsightsView data={mutation.data} />}
        </div>
      </div>
    </div>,
    document.body,
  )
}

function LoadingView() {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: '#a3a3a3' }}>
      <span className="animate-pulse">●</span>
      <span>Analyzing the object and its connections…</span>
    </div>
  )
}

function ErrorView({ error }: { error: string }) {
  const isDisabled = error.includes('503') || error.toLowerCase().includes('disabled')
  return (
    <div style={{ color: '#fca5a5' }}>
      <div style={{ fontWeight: 600, marginBottom: 6 }}>
        {isDisabled ? 'AI features are disabled' : 'Analysis failed'}
      </div>
      <div style={{ fontSize: 12, color: '#a3a3a3' }}>
        {isDisabled
          ? 'Set ANTHROPIC_API_KEY in the backend .env and restart the server to enable Get insights.'
          : error}
      </div>
    </div>
  )
}

function InsightsView({ data }: { data: ObjectInsights }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
      <section>
        <SectionTitle>Summary</SectionTitle>
        <p style={{ margin: 0 }}>{data.summary}</p>
      </section>
      {data.observations?.length > 0 && (
        <section>
          <SectionTitle>Observations</SectionTitle>
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {data.observations.map((o, i) => (
              <li key={i} style={{ marginBottom: 4 }}>
                {o}
              </li>
            ))}
          </ul>
        </section>
      )}
      {data.recommendations?.length > 0 && (
        <section>
          <SectionTitle>Recommendations</SectionTitle>
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {data.recommendations.map((r, i) => (
              <li key={i} style={{ marginBottom: 4 }}>
                {r}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        fontSize: 10,
        textTransform: 'uppercase',
        letterSpacing: '0.08em',
        color: '#737373',
        marginBottom: 6,
      }}
    >
      {children}
    </div>
  )
}
