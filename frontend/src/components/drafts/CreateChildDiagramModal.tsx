import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useCreateDiagram } from '../../hooks/use-diagrams'
import type { ModelObject } from '../../types/model'
import { Modal } from '../common/Modal'

// Object types that can have child diagrams.
const DRILLABLE_TYPES = new Set(['system', 'app', 'store'])

function childDiagramType(objectType: string): 'container' | 'component' {
  return objectType === 'system' ? 'container' : 'component'
}

function defaultChildDiagramName(objectName: string, objectType: string): string {
  return objectType === 'system'
    ? `${objectName} · Containers`
    : `${objectName} · Components`
}

function levelLabel(objectType: string): string {
  return objectType === 'system' ? 'L2 · Container' : 'L3 · Component'
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
          <button
            onClick={onClose}
            disabled={creating}
            style={{
              background: 'transparent',
              border: '1px solid #333',
              borderRadius: 6,
              color: '#a3a3a3',
              cursor: 'pointer',
              fontSize: 13,
              padding: '6px 14px',
              opacity: creating ? 0.5 : 1,
            }}
          >
            Cancel
          </button>
          <button
            onClick={handleCreate}
            disabled={creating || !name.trim()}
            style={{
              background: '#2563eb',
              border: '1px solid #1d4ed8',
              borderRadius: 6,
              color: 'white',
              cursor: 'pointer',
              fontSize: 13,
              padding: '6px 14px',
              opacity: creating || !name.trim() ? 0.5 : 1,
            }}
          >
            {creating ? 'Creating...' : 'Create'}
          </button>
        </>
      }
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {/* Level label */}
        <div
          style={{
            fontSize: 10,
            color: '#525252',
            textTransform: 'uppercase',
            letterSpacing: '0.05em',
            marginBottom: 2,
          }}
        >
          {levelLabel(object.type)}
        </div>

        <label style={{ fontSize: 12, color: '#a3a3a3' }}>Diagram name</label>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') handleCreate()
          }}
          autoFocus
          placeholder="Enter diagram name..."
          style={{
            background: '#0a0a0a',
            border: '1px solid #333',
            borderRadius: 6,
            color: '#e5e5e5',
            fontSize: 13,
            padding: '8px 10px',
            outline: 'none',
            width: '100%',
            boxSizing: 'border-box',
          }}
        />
        <div style={{ fontSize: 11, color: '#525252' }}>Scoped to: {object.name}</div>
      </div>
    </Modal>
  )
}
