import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  useAddObjectToDiagram,
  useCreateObject,
  useDeleteObject,
} from '../../hooks/use-api'
import { useObjectDiagrams } from '../../hooks/use-diagrams'
import { useCanvasStore } from '../../stores/canvas-store'
import type { ModelObject } from '../../types/model'

interface ObjectContextMenuProps {
  object: ModelObject
  diagramId?: string
}

export function ObjectContextMenu({ object, diagramId }: ObjectContextMenuProps) {
  const [open, setOpen] = useState(false)
  const [position, setPosition] = useState<'right' | 'left'>('right')
  const btnRef = useRef<HTMLButtonElement>(null)
  const navigate = useNavigate()
  const { data: objectDiagrams = [] } = useObjectDiagrams(object.id)
  const createObject = useCreateObject()
  const addToDiagram = useAddObjectToDiagram()
  const deleteObject = useDeleteObject()
  const { selectNode } = useCanvasStore()

  // Close on outside click
  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (btnRef.current && !btnRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    window.addEventListener('click', handler)
    return () => window.removeEventListener('click', handler)
  }, [open])

  const handleViewInModel = () => {
    if (diagramId && objectDiagrams.some((d) => d.id === diagramId)) {
      selectNode(object.id)
    } else if (objectDiagrams.length > 0) {
      navigate(`/diagram/${objectDiagrams[0].id}`)
    } else {
      alert('This object is not in any diagram yet')
    }
    setOpen(false)
  }

  const handleDuplicate = () => {
    createObject.mutate(
      {
        name: `${object.name} (copy)`,
        type: object.type,
        scope: object.scope,
        status: object.status,
        description: object.description,
        icon: object.icon,
        technology: object.technology,
        tags: object.tags,
        owner_team: object.owner_team,
      },
      {
        onSuccess: (newObj) => {
          if (diagramId) {
            addToDiagram.mutate({
              diagramId,
              objectId: newObj.id,
              x: 200 + Math.random() * 300,
              y: 150 + Math.random() * 250,
            })
          }
        },
      },
    )
    setOpen(false)
  }

  const handleDelete = () => {
    if (!confirm(`Delete "${object.name}"? This cannot be undone.`)) return
    deleteObject.mutate(object.id)
    setOpen(false)
  }

  const handleClick = (e: React.MouseEvent) => {
    e.stopPropagation()
    // Detect position — if near right edge, open menu to the left
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
    setPosition(window.innerWidth - rect.right < 220 ? 'left' : 'right')
    setOpen(!open)
  }

  return (
    <div style={{ position: 'relative', display: 'inline-block' }}>
      <button
        ref={btnRef}
        onClick={handleClick}
        style={{
          background: 'transparent',
          border: 'none',
          color: '#737373',
          cursor: 'pointer',
          fontSize: 14,
          padding: '0 4px',
          lineHeight: 1,
        }}
        title="More actions"
      >
        ⋯
      </button>

      {open && (
        <div
          onClick={(e) => e.stopPropagation()}
          style={{
            position: 'absolute',
            top: '100%',
            [position]: 0,
            marginTop: 4,
            minWidth: 180,
            background: '#1a1a1a',
            border: '1px solid #333',
            borderRadius: 6,
            boxShadow: '0 8px 24px rgba(0,0,0,0.5)',
            zIndex: 100,
            padding: 4,
          }}
        >
          <MenuItem icon="🎯" label="View in model" onClick={handleViewInModel} />
          <MenuItem icon="🔗" label="View dependencies" onClick={() => alert('Coming in Phase 7 (Overlays + Flows)')} />
          <MenuItem icon="⧉" label="Duplicate object" onClick={handleDuplicate} />
          <MenuItem icon="✨" label="Get insights" onClick={() => alert('Coming in Phase 6 (AI Features)')} />
          <div style={{ height: 1, background: '#333', margin: '4px 0' }} />
          <MenuItem
            icon="🗑"
            label="Delete object"
            onClick={handleDelete}
            danger
          />
        </div>
      )}
    </div>
  )
}

function MenuItem({
  icon,
  label,
  onClick,
  danger,
}: {
  icon: string
  label: string
  onClick: () => void
  danger?: boolean
}) {
  return (
    <button
      onClick={onClick}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        width: '100%',
        padding: '6px 10px',
        background: 'transparent',
        border: 'none',
        borderRadius: 4,
        color: danger ? '#f87171' : '#d4d4d4',
        cursor: 'pointer',
        fontSize: 12,
        textAlign: 'left',
      }}
      onMouseEnter={(e) => (e.currentTarget.style.background = danger ? 'rgba(239,68,68,0.1)' : '#262626')}
      onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
    >
      <span style={{ width: 16, textAlign: 'center', opacity: 0.8 }}>{icon}</span>
      {label}
    </button>
  )
}
