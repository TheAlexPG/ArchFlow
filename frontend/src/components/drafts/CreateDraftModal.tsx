import { useEffect, useState } from 'react'
import { Modal } from '../common/Modal'

interface CreateDraftModalProps {
  open: boolean
  onClose: () => void
  onSubmit: (name: string, description: string | null) => void
  submitting?: boolean
  /** Name of the diagram being forked — shown as context. */
  sourceName?: string
}

export function CreateDraftModal({
  open,
  onClose,
  onSubmit,
  submitting,
  sourceName,
}: CreateDraftModalProps) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')

  useEffect(() => {
    if (open) {
      setName('')
      setDescription('')
    }
  }, [open])

  const canSubmit = name.trim().length > 0 && !submitting
  const submit = () => {
    if (!canSubmit) return
    onSubmit(name.trim(), description.trim() || null)
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Draft new feature"
      footer={
        <>
          <button
            onClick={onClose}
            disabled={submitting}
            style={{
              fontSize: 12,
              padding: '7px 14px',
              background: 'transparent',
              border: '1px solid #404040',
              color: '#a3a3a3',
              borderRadius: 6,
              cursor: submitting ? 'default' : 'pointer',
            }}
          >
            Cancel
          </button>
          <button
            onClick={submit}
            disabled={!canSubmit}
            style={{
              fontSize: 12,
              padding: '7px 14px',
              background: canSubmit ? '#3b82f6' : '#1e3a5f',
              border: '1px solid #3b82f6',
              color: '#fff',
              borderRadius: 6,
              cursor: canSubmit ? 'pointer' : 'default',
              opacity: submitting ? 0.6 : 1,
            }}
          >
            {submitting ? 'Creating…' : 'Create draft'}
          </button>
        </>
      }
    >
      {sourceName && (
        <div style={{ fontSize: 12, color: '#737373', marginBottom: 14 }}>
          Forking <span style={{ color: '#d4d4d4' }}>{sourceName}</span> — you'll
          edit a private copy. Apply when ready to merge.
        </div>
      )}
      <label style={{ display: 'block', fontSize: 11, color: '#a3a3a3', marginBottom: 4 }}>
        Draft name
      </label>
      <input
        autoFocus
        value={name}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && canSubmit) submit()
        }}
        placeholder="e.g. Add payments service"
        style={{
          width: '100%',
          padding: '8px 10px',
          fontSize: 13,
          background: '#0a0a0a',
          border: '1px solid #333',
          borderRadius: 6,
          color: '#f5f5f5',
          outline: 'none',
          marginBottom: 14,
          boxSizing: 'border-box',
        }}
      />
      <label style={{ display: 'block', fontSize: 11, color: '#a3a3a3', marginBottom: 4 }}>
        What are you trying? <span style={{ color: '#525252' }}>(optional)</span>
      </label>
      <textarea
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        placeholder="Short description of the change you're proposing."
        rows={4}
        style={{
          width: '100%',
          padding: '8px 10px',
          fontSize: 13,
          background: '#0a0a0a',
          border: '1px solid #333',
          borderRadius: 6,
          color: '#f5f5f5',
          outline: 'none',
          resize: 'vertical',
          fontFamily: 'inherit',
          boxSizing: 'border-box',
        }}
      />
    </Modal>
  )
}
