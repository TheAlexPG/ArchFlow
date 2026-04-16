import { useMemo, useState } from 'react'
import {
  useAddObjectToDiagram,
  useCreateObject,
  useDiagramObjects,
  useObjects,
} from '../../hooks/use-api'
import { useCanvasStore } from '../../stores/canvas-store'
import type { CommentType, ObjectType } from '../../types/model'
import { TYPE_ICONS, TYPE_LABELS } from '../canvas/node-utils'
import { ObjectContextMenu } from '../common/ObjectContextMenu'

const QUICK_TYPES: ObjectType[] = ['system', 'actor', 'external_system', 'app', 'store', 'group']

// Canvas comment types — dropping one of these enters compose mode; the
// next click on empty canvas places the pin at that position.
const COMMENT_TYPES: { value: CommentType; icon: string; label: string }[] = [
  { value: 'question', icon: '❓', label: 'Question' },
  { value: 'inaccuracy', icon: '🚩', label: 'Inaccuracy' },
  { value: 'idea', icon: '💡', label: 'Idea' },
  { value: 'note', icon: '📝', label: 'Note' },
]

interface AddObjectToolbarProps {
  diagramId?: string
}

export function AddObjectToolbar({ diagramId }: AddObjectToolbarProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [search, setSearch] = useState('')
  const { data: objects = [] } = useObjects()
  const { data: diagramObjects = [] } = useDiagramObjects(diagramId)
  const createObject = useCreateObject()
  const addToDiagram = useAddObjectToDiagram()
  const { setCommentComposeType } = useCanvasStore()

  const handleStartCommentCompose = (type: CommentType) => {
    setCommentComposeType(type)
    setIsOpen(false)
  }

  const inDiagramIds = useMemo(
    () => new Set(diagramObjects.map((d) => d.object_id)),
    [diagramObjects],
  )

  // Show every model object — objects already in the diagram stay visible
  // (like IcePanel) but are flagged as "In diagram" and can't be re-added.
  const filtered = useMemo(() => {
    if (!search) return objects
    const q = search.toLowerCase()
    return objects.filter(
      (o) =>
        o.name.toLowerCase().includes(q) ||
        o.description?.toLowerCase().includes(q) ||
        o.technology?.some((t) => t.toLowerCase().includes(q)),
    )
  }, [objects, search])

  const handleAddExisting = (objectId: string) => {
    if (!diagramId) return
    if (inDiagramIds.has(objectId)) return
    addToDiagram.mutate({
      diagramId,
      objectId,
      x: 200 + Math.random() * 300,
      y: 150 + Math.random() * 250,
    })
    setIsOpen(false)
  }

  const handleCreateNew = (type: ObjectType) => {
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
              x: 200 + Math.random() * 300,
              y: 150 + Math.random() * 250,
            })
          }
        },
      },
    )
    setIsOpen(false)
  }

  return (
    <div style={{ position: 'absolute', left: 16, top: '50%', transform: 'translateY(-50%)', zIndex: 10 }}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        style={{
          width: 40, height: 40, borderRadius: 8,
          background: isOpen ? '#333' : '#262626',
          border: '1px solid #404040',
          color: '#d4d4d4', cursor: 'pointer', fontSize: 20,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          boxShadow: '0 2px 8px rgba(0,0,0,0.3)',
        }}
        title="Add object"
      >
        +
      </button>

      {isOpen && (
        <>
          <div
            style={{ position: 'fixed', inset: 0, zIndex: 9 }}
            onClick={() => setIsOpen(false)}
          />
          <div style={{
            position: 'absolute', left: 52, top: -160, width: 280, maxHeight: 440,
            background: '#171717', border: '1px solid #333', borderRadius: 8,
            boxShadow: '0 8px 24px rgba(0,0,0,0.5)', zIndex: 10,
            display: 'flex', flexDirection: 'column', overflow: 'hidden',
          }}>
            {/* Header */}
            <div style={{ padding: '10px 12px', borderBottom: '1px solid #262626' }}>
              <div style={{ fontSize: 11, color: '#737373', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                Model objects
              </div>
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search objects..."
                autoFocus
                style={{
                  width: '100%', background: '#0a0a0a', border: '1px solid #333',
                  borderRadius: 4, padding: '6px 8px', color: '#e5e5e5', fontSize: 12,
                  outline: 'none', boxSizing: 'border-box',
                }}
              />
            </div>

            {/* List */}
            <div style={{ flex: 1, overflowY: 'auto', minHeight: 100, maxHeight: 240 }}>
              {filtered.length === 0 ? (
                <div style={{ padding: 16, fontSize: 12, color: '#525252', textAlign: 'center' }}>
                  {search ? 'No matches' : 'No objects yet'}
                </div>
              ) : (
                filtered.map((obj) => {
                  const inDiagram = inDiagramIds.has(obj.id)
                  return (
                    <div
                      key={obj.id}
                      style={{
                        display: 'flex', alignItems: 'center', gap: 4,
                        padding: '2px 12px 2px 0',
                      }}
                      className="group"
                      onMouseEnter={(e) => (e.currentTarget.style.background = '#262626')}
                      onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                    >
                      <button
                        onClick={() => handleAddExisting(obj.id)}
                        disabled={inDiagram}
                        style={{
                          display: 'flex', alignItems: 'center', gap: 8,
                          flex: 1, padding: '6px 12px',
                          background: 'transparent', border: 'none',
                          color: inDiagram ? '#737373' : '#d4d4d4',
                          cursor: inDiagram ? 'default' : 'pointer',
                          fontSize: 12, textAlign: 'left',
                        }}
                        title={
                          inDiagram
                            ? 'Already in this diagram'
                            : `${TYPE_LABELS[obj.type]}${obj.technology ? ` — ${obj.technology.join(', ')}` : ''}`
                        }
                      >
                        <span style={{ opacity: 0.5 }}>{TYPE_ICONS[obj.type]}</span>
                        <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {obj.name}
                        </span>
                        {inDiagram ? (
                          <span
                            title="In this diagram"
                            style={{ fontSize: 9, color: '#60a5fa' }}
                          >
                            ●
                          </span>
                        ) : (
                          <span style={{ fontSize: 10, color: '#525252' }}>
                            {TYPE_LABELS[obj.type]}
                          </span>
                        )}
                      </button>
                      <ObjectContextMenu object={obj} diagramId={diagramId} />
                    </div>
                  )
                })
              )}
            </div>

            {/* Quick create */}
            <div style={{ borderTop: '1px solid #262626', padding: '8px 12px' }}>
              <div style={{ fontSize: 10, color: '#737373', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                Or create new
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                {QUICK_TYPES.map((type) => (
                  <button
                    key={type}
                    onClick={() => handleCreateNew(type)}
                    style={{
                      fontSize: 11, padding: '3px 8px', borderRadius: 4,
                      background: '#262626', border: '1px solid #333',
                      color: '#a3a3a3', cursor: 'pointer',
                      display: 'flex', alignItems: 'center', gap: 4,
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.background = '#333'
                      e.currentTarget.style.color = '#f5f5f5'
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.background = '#262626'
                      e.currentTarget.style.color = '#a3a3a3'
                    }}
                  >
                    <span style={{ opacity: 0.7 }}>{TYPE_ICONS[type]}</span>
                    {TYPE_LABELS[type]}
                  </button>
                ))}
              </div>
            </div>

            {/* Add comment — enters compose mode; next canvas click drops the pin */}
            <div style={{ borderTop: '1px solid #262626', padding: '8px 12px' }}>
              <div style={{ fontSize: 10, color: '#737373', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                Add comment
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                {COMMENT_TYPES.map((c) => (
                  <button
                    key={c.value}
                    onClick={() => handleStartCommentCompose(c.value)}
                    style={{
                      fontSize: 11, padding: '3px 8px', borderRadius: 4,
                      background: '#262626', border: '1px solid #333',
                      color: '#a3a3a3', cursor: 'pointer',
                      display: 'flex', alignItems: 'center', gap: 4,
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.background = '#333'
                      e.currentTarget.style.color = '#f5f5f5'
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.background = '#262626'
                      e.currentTarget.style.color = '#a3a3a3'
                    }}
                    title={`Drop a ${c.label.toLowerCase()} on the canvas`}
                  >
                    <span>{c.icon}</span>
                    {c.label}
                  </button>
                ))}
              </div>
              <div style={{ fontSize: 10, color: '#525252', marginTop: 4 }}>
                Then click on the canvas to place the pin.
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
