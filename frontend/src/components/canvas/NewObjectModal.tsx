import { useEffect, useRef, useState } from 'react'
import { Modal } from '../common/Modal'
import { Button } from '../ui/Button'
import { SectionLabel } from '../ui/SectionLabel'
import type { ObjectType } from '../../types/model'
import { TYPE_LABELS } from './node-utils'

interface NewObjectModalProps {
  open: boolean
  onClose: () => void
  objectType: ObjectType
  /** Existing object names (for soft duplicate warning). */
  existingNames?: string[]
  onSubmit: (name: string) => void
}

export function NewObjectModal({
  open,
  onClose,
  objectType,
  existingNames = [],
  onSubmit,
}: NewObjectModalProps) {
  const [name, setName] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  // Reset on open
  useEffect(() => {
    if (open) {
      setName('')
      // Autofocus — defer one tick so Modal's mount animation doesn't swallow it
      setTimeout(() => inputRef.current?.focus(), 0)
    }
  }, [open])

  const trimmed = name.trim()
  const isDuplicate =
    trimmed.length > 0 &&
    existingNames.some((n) => n.toLowerCase() === trimmed.toLowerCase())

  const handleSubmit = () => {
    if (!trimmed) return
    onSubmit(trimmed)
    onClose()
  }

  const typeLabel = TYPE_LABELS[objectType] ?? objectType

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`New ${typeLabel}`}
      width={360}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" disabled={!trimmed} onClick={handleSubmit}>
            Create
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <div>
          <SectionLabel className="mb-1.5">Name</SectionLabel>
          <input
            ref={inputRef}
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleSubmit()
              if (e.key === 'Escape') onClose()
            }}
            placeholder={`e.g. My ${typeLabel}`}
            className="w-full bg-surface border border-border-base rounded-md px-3 py-2 text-[13px] text-text-base outline-none focus:border-border-hi placeholder:text-text-4 transition-colors"
          />
        </div>

        {isDuplicate && (
          <div className="flex items-center gap-1.5 text-[11.5px] text-accent-amber font-mono">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
              <line x1="12" y1="9" x2="12" y2="13" />
              <line x1="12" y1="17" x2="12.01" y2="17" />
            </svg>
            Name already exists — are you sure?
          </div>
        )}
      </div>
    </Modal>
  )
}
