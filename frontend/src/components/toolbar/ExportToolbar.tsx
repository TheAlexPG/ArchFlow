import { useEffect, useRef, useState } from 'react'
import {
  fetchDiagramExport,
  type DiagramExportFormat,
} from '../../hooks/use-api'
import { useDiagram } from '../../hooks/use-diagrams'

interface ExportToolbarProps {
  diagramId: string | undefined
}

interface FormatRow {
  id: DiagramExportFormat
  label: string
  ext: string
  hint: string
}

const FORMATS: FormatRow[] = [
  { id: 'mermaid', label: 'Mermaid', ext: 'mmd', hint: 'C4 / flowchart' },
  { id: 'plantuml', label: 'PlantUML', ext: 'puml', hint: 'C4-PlantUML' },
  { id: 'structurizr', label: 'Structurizr', ext: 'dsl', hint: 'DSL' },
  { id: 'json', label: 'JSON', ext: 'json', hint: 'Full payload' },
]

type FlashKind = 'copy' | 'download' | 'error'

interface FlashState {
  format: DiagramExportFormat
  kind: FlashKind
  text: string
}

function safeFilename(name: string | undefined, fallback: string): string {
  const base = (name || fallback).trim()
  // Limit to characters safe across Windows / macOS / Linux. Anything else
  // collapses to a single hyphen so the file is still recognisable.
  const slug = base
    .replace(/[^A-Za-z0-9 _.-]+/g, '-')
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '')
  return slug || fallback
}

function describeError(err: unknown): string {
  const e = err as { response?: { status?: number; data?: { detail?: string } }; message?: string }
  const status = e?.response?.status
  if (status === 401) return 'Sign in required'
  if (status === 403) return 'No access'
  if (status === 404) return 'Diagram not found'
  return e?.response?.data?.detail || e?.message || 'Export failed'
}

export function ExportToolbar({ diagramId }: ExportToolbarProps) {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState<DiagramExportFormat | null>(null)
  const [flash, setFlash] = useState<FlashState | null>(null)
  const flashTimer = useRef<number | null>(null)
  const { data: diagram } = useDiagram(diagramId)

  useEffect(() => {
    return () => {
      if (flashTimer.current !== null) window.clearTimeout(flashTimer.current)
    }
  }, [])

  const showFlash = (state: FlashState) => {
    setFlash(state)
    if (flashTimer.current !== null) window.clearTimeout(flashTimer.current)
    flashTimer.current = window.setTimeout(() => setFlash(null), 1800)
  }

  const handleCopy = async (fmt: DiagramExportFormat) => {
    if (!diagramId || busy) return
    setBusy(fmt)
    try {
      const text = await fetchDiagramExport(diagramId, fmt)
      await navigator.clipboard.writeText(text)
      showFlash({ format: fmt, kind: 'copy', text: 'Copied' })
    } catch (err) {
      showFlash({ format: fmt, kind: 'error', text: describeError(err) })
    } finally {
      setBusy(null)
    }
  }

  const handleDownload = async (fmt: DiagramExportFormat, ext: string) => {
    if (!diagramId || busy) return
    setBusy(fmt)
    try {
      const text = await fetchDiagramExport(diagramId, fmt)
      const mime = fmt === 'json' ? 'application/json' : 'text/plain'
      const blob = new Blob([text], { type: `${mime};charset=utf-8` })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${safeFilename(diagram?.name, 'diagram')}.${ext}`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
      showFlash({ format: fmt, kind: 'download', text: 'Downloaded' })
    } catch (err) {
      showFlash({ format: fmt, kind: 'error', text: describeError(err) })
    } finally {
      setBusy(null)
    }
  }

  if (!diagramId) return null

  return (
    <div style={{ position: 'relative' }}>
      <button
        onClick={() => setOpen((v) => !v)}
        title="Export diagram"
        style={{
          height: 32,
          padding: '0 12px',
          borderRadius: 8,
          background: open ? 'var(--control-button-hover)' : 'var(--control-button-bg)',
          border: `1px solid ${open ? 'var(--color-border-hi)' : 'var(--control-border)'}`,
          color: 'var(--color-text-base)',
          cursor: 'pointer',
          fontSize: 12,
          display: 'flex',
          alignItems: 'center',
          gap: 6,
        }}
      >
        <DownloadIcon />
        Export
      </button>

      {open && (
        <>
          <div
            style={{ position: 'fixed', inset: 0, zIndex: 9 }}
            onClick={() => setOpen(false)}
          />
          <div
            style={{
              position: 'absolute',
              right: 0,
              top: 38,
              width: 280,
              background: 'var(--color-panel)',
              border: '1px solid var(--color-border-base)',
              borderRadius: 8,
              zIndex: 10,
              overflow: 'hidden',
            }}
          >
            <div
              style={{
                padding: '8px 12px',
                borderBottom: '1px solid var(--color-border-base)',
                fontSize: 11,
                color: 'var(--color-text-3)',
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
              }}
            >
              Export as
            </div>
            <div>
              {FORMATS.map((f) => {
                const isBusy = busy === f.id
                const flashed = flash?.format === f.id ? flash : null
                return (
                  <div
                    key={f.id}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 8,
                      padding: '8px 12px',
                      borderBottom: '1px solid var(--color-border-base)',
                    }}
                  >
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 12, color: 'var(--color-text-base)' }}>
                        {f.label}
                      </div>
                      <div style={{ fontSize: 10, color: 'var(--color-text-4)' }}>
                        {flashed
                          ? flashed.text
                          : `${f.hint} · .${f.ext}`}
                      </div>
                    </div>
                    <FormatActionButton
                      label="Copy"
                      onClick={() => handleCopy(f.id)}
                      disabled={isBusy || !!busy}
                      active={flashed?.kind === 'copy'}
                      error={flashed?.kind === 'error'}
                    />
                    <FormatActionButton
                      label="Save"
                      onClick={() => handleDownload(f.id, f.ext)}
                      disabled={isBusy || !!busy}
                      active={flashed?.kind === 'download'}
                      error={flashed?.kind === 'error'}
                    />
                  </div>
                )
              })}
            </div>
          </div>
        </>
      )}
    </div>
  )
}

function FormatActionButton({
  label,
  onClick,
  disabled,
  active,
  error,
}: {
  label: string
  onClick: () => void
  disabled?: boolean
  active?: boolean
  error?: boolean
}) {
  let bg = 'var(--control-button-hover)'
  let border = 'var(--control-border)'
  let color = 'var(--color-text-base)'
  if (active) {
    bg = '#1f3a23'
    border = '#2f6b3a'
    color = '#86efac'
  } else if (error) {
    bg = '#3a1f1f'
    border = '#6b2f2f'
    color = '#fca5a5'
  }
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      style={{
        fontSize: 11,
        padding: '4px 10px',
        borderRadius: 4,
        background: bg,
        border: `1px solid ${border}`,
        color,
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled && !active && !error ? 0.6 : 1,
      }}
    >
      {label}
    </button>
  )
}

function DownloadIcon() {
  return (
    <svg
      width="12"
      height="12"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <polyline points="7 10 12 15 17 10" />
      <line x1="12" y1="15" x2="12" y2="3" />
    </svg>
  )
}
