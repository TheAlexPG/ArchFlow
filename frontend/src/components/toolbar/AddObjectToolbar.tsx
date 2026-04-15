import { useState } from 'react'
import { useAddObjectToDiagram, useCreateObject } from '../../hooks/use-api'
import type { ObjectType } from '../../types/model'
import { TYPE_ICONS, TYPE_LABELS } from '../canvas/node-utils'

const OBJECT_TYPES: ObjectType[] = ['system', 'actor', 'external_system', 'app', 'store', 'component', 'group']

interface AddObjectToolbarProps {
  diagramId?: string
}

export function AddObjectToolbar({ diagramId }: AddObjectToolbarProps) {
  const [isOpen, setIsOpen] = useState(false)
  const createObject = useCreateObject()
  const addToDiagram = useAddObjectToDiagram()

  const handleAdd = (type: ObjectType) => {
    const name = prompt(`New ${TYPE_LABELS[type]} name:`)
    if (!name?.trim()) return
    createObject.mutate(
      { name: name.trim(), type },
      {
        onSuccess: (obj) => {
          if (diagramId) {
            addToDiagram.mutate({
              diagramId,
              objectId: obj.id,
              x: 100 + Math.random() * 400,
              y: 100 + Math.random() * 300,
            })
          }
        },
      },
    )
    setIsOpen(false)
  }

  return (
    <div style={{ position: 'absolute', left: 16, top: '50%', transform: 'translateY(-50%)', zIndex: 10, display: 'flex', flexDirection: 'column', gap: 8 }}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        style={{
          width: 40, height: 40, borderRadius: 8, background: '#262626', border: '1px solid #404040',
          color: '#a3a3a3', cursor: 'pointer', fontSize: 20, display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}
        title="Add object"
      >
        +
      </button>

      {isOpen && (
        <div style={{
          background: '#262626', border: '1px solid #404040', borderRadius: 8, padding: 6, minWidth: 180,
        }}>
          <div style={{ fontSize: 10, color: '#737373', padding: '4px 8px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            Add object
          </div>
          {OBJECT_TYPES.map((type) => (
            <button
              key={type}
              onClick={() => handleAdd(type)}
              style={{
                width: '100%', textAlign: 'left', padding: '6px 8px', borderRadius: 4, fontSize: 13,
                color: '#d4d4d4', background: 'transparent', border: 'none', cursor: 'pointer',
                display: 'flex', alignItems: 'center', gap: 8,
              }}
              onMouseEnter={(e) => (e.currentTarget.style.background = '#333')}
              onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
            >
              <span style={{ width: 20, textAlign: 'center', opacity: 0.6 }}>{TYPE_ICONS[type]}</span>
              {TYPE_LABELS[type]}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
