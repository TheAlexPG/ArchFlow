import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useCreateDiagram } from '../../hooks/use-diagrams'
import type { ModelObject } from '../../types/model'
import { Modal } from '../common/Modal'
import { Button } from '../ui/Button'

// Object types that can have child diagrams.
// system → L2 Container, app/store → L3 Component, component → L4 Code.
const DRILLABLE_TYPES = new Set(['system', 'app', 'store', 'component'])

function childDiagramType(objectType: string): 'container' | 'component' | 'custom' {
  if (objectType === 'system') return 'container'
  if (objectType === 'component') return 'custom'
  return 'component'
}

function defaultChildDiagramName(objectName: string, objectType: string): string {
  if (objectType === 'system') return `${objectName} · Containers`
  if (objectType === 'component') return `${objectName} · Code`
  return `${objectName} · Components`
}

function levelLabel(objectType: string): string {
  if (objectType === 'system') return 'L2 · Container'
  if (objectType === 'component') return 'L4 · Code'
  return 'L3 · Component'
}

export { DRILLABLE_TYPES, childDiagramType, defaultChildDiagramName }

interface CreateChildDiagramModalProps {
  object: ModelObject
  open: boolean
  onClose: () => void
  /** Called after the diagram is created (before navigation). */
  onCreated?: (diagramId: string) => void
}

/**
 * Compact modal that creates a child (container or component) diagram for a
 * given object, then navigates to it.  Shared by C4Node and ObjectSidebar.
 */
export function CreateChildDiagramModal({
  object,
  open,
  onClose,
  onCreated,
}: CreateChildDiagramModalProps) {
  const navigate = useNavigate()
  const createDiagram = useCreateDiagram()
  const [name, setName] = useState(() => defaultChildDiagramName(object.name, object.type))
  const [creating, setCreating] = useState(false)

  // Reset name each time the modal opens (object may have changed between opens).
  useEffect(() => {
    if (open) setName(defaultChildDiagramName(object.name, object.type))
  }, [open, object.name, object.type])

  const handleCreate = () => {
    if (!name.trim()) return
    setCreating(true)
    createDiagram.mutate(
      {
        name: name.trim(),
        type: childDiagramType(object.type),
        scope_object_id: object.id,
      },
      {
        onSuccess: (diagram) => {
          setCreating(false)
          onCreated?.(diagram.id)
          onClose()
          navigate(`/diagram/${diagram.id}`)
        },
        onError: () => {
          setCreating(false)
        },
      },
    )
  }

  return (
    <Modal
      open={open}
      onClose={() => !creating && onClose()}
      title={`Create ${childDiagramType(object.type)} diagram`}
      width={360}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={creating}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={handleCreate}
            disabled={creating || !name.trim()}
          >
            {creating ? 'Creating…' : 'Create'}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        {/* Level + scope pill */}
        <div className="flex items-center gap-2">
          <span className="font-mono text-[10px] uppercase tracking-[0.06em] text-text-3 bg-surface border border-border-base rounded px-2 py-0.5">
            {levelLabel(object.type)}
          </span>
          <span className="font-mono text-[10.5px] text-text-3">
            scoped to <span className="text-text-2">{object.name}</span>
          </span>
        </div>

        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') handleCreate()
          }}
          autoFocus
          placeholder="Enter diagram name…"
          className="w-full bg-surface border border-border-base rounded-md px-3 py-2 text-[13px] text-text-base outline-none focus:border-border-hi placeholder:text-text-4 transition-colors"
        />
      </div>
    </Modal>
  )
}
