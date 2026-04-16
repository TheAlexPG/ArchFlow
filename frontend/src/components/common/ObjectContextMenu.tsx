import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
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
  const [coords, setCoords] = useState<{ top: number; left: number } | null>(null)
  const btnRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const navigate = useNavigate()
  const { data: objectDiagrams = [] } = useObjectDiagrams(object.id)
  const createObject = useCreateObject()
  const addToDiagram = useAddObjectToDiagram()
  const deleteObject = useDeleteObject()
  const { selectNode } = useCanvasStore()

  // Position menu near button, flip if near edges
  useLayoutEffect(() => {
    if (!open || !btnRef.current) return
    const rect = btnRef.current.getBoundingClientRect()
    const menuWidth = 200
    const menuHeight = 250
    let left = rect.right + 4
    let top = rect.top
    if (left + menuWidth > window.innerWidth) {
      left = rect.left - menuWidth - 4
    }
    if (top + menuHeight > window.innerHeight) {
      top = window.innerHeight - menuHeight - 8
    }
    setCoords({ top, left })
  }, [open])

  // Close on outside click
  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      const target = e.target as Node
      if (
        btnRef.current &&
        !btnRef.current.contains(target) &&
        menuRef.current &&
        !menuRef.current.contains(target)
      ) {
        setOpen(false)
      }
    }
    // Delay to avoid catching the click that opened the menu
    setTimeout(() => window.addEventListener('click', handler), 0)
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
    setOpen(!open)
  }

  return (
    <>
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

      {open && coords && createPortal(
        <div
          ref={menuRef}
          onClick={(e) => e.stopPropagation()}
          style={{
            position: 'fixed',
            top: coords.top,
            left: coords.left,
            minWidth: 200,
            background: '#1a1a1a',
            border: '1px solid #333',
            borderRadius: 6,
            boxShadow: '0 8px 24px rgba(0,0,0,0.5)',
            zIndex: 10000,
            padding: 4,
          }}
        >
          <MenuItem icon="🎯" label="View in model" onClick={handleViewInModel} />
          <MenuItem icon="🔗" label="View dependencies" onClick={() => { alert('Coming in Phase 7 (Overlays + Flows)'); setOpen(false) }} />
          <MenuItem icon="⧉" label="Duplicate object" onClick={handleDuplicate} />
          <MenuItem icon="✨" label="Get insights" onClick={() => { alert('Coming in Phase 6 (AI Features)'); setOpen(false) }} />
          <div style={{ height: 1, background: '#333', margin: '4px 0' }} />
          <MenuItem
            icon="🗑"
            label="Delete object"
            onClick={handleDelete}
            danger
          />
        </div>,
        document.body,
      )}
    </>
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
