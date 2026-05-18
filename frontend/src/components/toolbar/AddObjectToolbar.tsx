import { useMemo, useState } from 'react'
import {
  useAddObjectToDiagram,
  useCreateObject,
  useDiagramObjects,
  useObjects,
  useUpdateObject,
} from '../../hooks/use-api'
import { useDiagram } from '../../hooks/use-diagrams'
import { useCanvasStore } from '../../stores/canvas-store'
import { C4_DIAGRAM_LEVEL_LABELS, type CommentType, type DiagramType, type ObjectType } from '../../types/model'
import { detectParentGroup, nodeToRect } from '../canvas/group-utils'
import { getObjectTypeLabel, TYPE_ICONS } from '../canvas/node-utils'
import { ObjectContextMenu } from '../common/ObjectContextMenu'

const ALL_QUICK_TYPES: ObjectType[] = ['system', 'actor', 'external_system', 'app', 'store', 'group']

function getQuickTypesForDiagram(diagramType: DiagramType | undefined): ObjectType[] {
  if (!diagramType) return ALL_QUICK_TYPES
  switch (diagramType) {
    case 'system_landscape':
    case 'system_context':
      return ['system', 'actor', 'external_system', 'group']
    case 'container':
      // A container can reference an external system (e.g. a payment gateway
      // it talks to). Allow placing systems on L2/L3 even though C4 purists
      // would typically render those on L1 — IcePanel does the same.
      return ['app', 'store', 'component', 'system', 'external_system', 'actor', 'group']
    case 'component':
      return ['component', 'system', 'external_system', 'actor', 'group']
    case 'custom':
      // C4 L4 is the Code diagram. The backend reuses the `component` object
      // type for code-level elements, so label it as Code in this context.
      return ['component', 'group']
    default:
      return ALL_QUICK_TYPES
  }
}

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
  // When we're on a forked draft diagram, creations stay scoped to the
  // draft so they don't leak into the live model.
  const { data: diagram } = useDiagram(diagramId)
  const draftId = diagram?.draft_id ?? null
  const diagramType = diagram?.type as DiagramType | undefined
  const quickTypes = getQuickTypesForDiagram(diagramType)
  const levelLabel = diagramType ? C4_DIAGRAM_LEVEL_LABELS[diagramType] : null
  const { data: objects = [] } = useObjects(draftId)
  const { data: diagramObjects = [] } = useDiagramObjects(diagramId)
  const createObject = useCreateObject(draftId)
  const addToDiagram = useAddObjectToDiagram()
  const updateObject = useUpdateObject()
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
        // TODO(tech-catalog): match by resolved catalog name/aliases (M7).
        o.technology_ids?.some((t) => t.toLowerCase().includes(q)),
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
    const name = prompt(`New ${getObjectTypeLabel(type, diagramType)} name:`)
    if (!name?.trim()) return
    const placementX = 200 + Math.random() * 300
    const placementY = 150 + Math.random() * 250
    createObject.mutate(
      { name: name.trim(), type, from_diagram_id: diagramId, from_draft_id: draftId },
      {
        onSuccess: (obj) => {
          if (!diagramId) return
          addToDiagram.mutate(
            { diagramId, objectId: obj.id, x: placementX, y: placementY },
            {
              onSuccess: () => {
                // After placement, check spatial containment against current
                // diagram objects (the new object is now in the diagram).
                if (type === 'group') return
                const nodeRect = nodeToRect(obj.id, { x: placementX, y: placementY }, undefined, undefined, [obj])
                const newParentId = detectParentGroup(obj.id, nodeRect, diagramObjects, [...objects, obj])
                if (newParentId) {
                  updateObject.mutate({ id: obj.id, parent_id: newParentId, from_diagram_id: diagramId, from_draft_id: draftId })
                }
              },
            },
          )
        },
      },
    )
    setIsOpen(false)
  }

  return (
    <div className="add-object-toolbar">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="add-object-toolbar__trigger"
        aria-expanded={isOpen}
        title="Add object"
      >
        +
      </button>

      {isOpen && (
        <>
          <div
            className="add-object-toolbar__scrim"
            onClick={() => setIsOpen(false)}
          />
          <div className="add-object-toolbar__popover">
            {/* Header */}
            <div className="add-object-toolbar__header">
              <div className="add-object-toolbar__eyebrow">
                Model objects
              </div>
              {levelLabel && (
                <div className="add-object-toolbar__level">
                  {levelLabel}
                </div>
              )}
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search objects..."
                autoFocus
                className="add-object-toolbar__search"
              />
            </div>

            {/* List */}
            <div className="add-object-toolbar__list">
              {filtered.length === 0 ? (
                <div className="add-object-toolbar__empty">
                  {search ? 'No matches' : 'No objects yet'}
                </div>
              ) : (
                filtered.map((obj) => {
                  const inDiagram = inDiagramIds.has(obj.id)
                  return (
                    <div
                      key={obj.id}
                      className="add-object-toolbar__row group"
                    >
                      <button
                        onClick={() => handleAddExisting(obj.id)}
                        disabled={inDiagram}
                        className="add-object-toolbar__object-button"
                        title={
                          inDiagram
                            ? 'Already in this diagram'
                            : `${getObjectTypeLabel(obj.type, diagramType)}${obj.technology_ids ? ` — ${obj.technology_ids.join(', ')}` : ''}`
                        }
                      >
                        <span style={{ opacity: 0.5 }}>{TYPE_ICONS[obj.type]}</span>
                        <span className="add-object-toolbar__object-name">
                          {obj.name}
                        </span>
                        {inDiagram ? (
                          <span
                            title="In this diagram"
                            className="add-object-toolbar__in-diagram"
                          >
                            ●
                          </span>
                        ) : (
                          <span className="add-object-toolbar__type-label">
                            {getObjectTypeLabel(obj.type, diagramType)}
                          </span>
                        )}
                      </button>
                      <ObjectContextMenu object={obj} diagramId={diagramId} draftId={draftId} />
                    </div>
                  )
                })
              )}
            </div>

            {/* Quick create */}
            <div className="add-object-toolbar__section">
              <div className="add-object-toolbar__eyebrow add-object-toolbar__section-title">
                Or create new
              </div>
              <div className="add-object-toolbar__button-grid">
                {quickTypes.map((type) => (
                  <button
                    key={type}
                    onClick={() => handleCreateNew(type)}
                    className="add-object-toolbar__pill"
                  >
                    <span style={{ opacity: 0.7 }}>{TYPE_ICONS[type]}</span>
                    {getObjectTypeLabel(type, diagramType)}
                  </button>
                ))}
              </div>
            </div>

            {/* Add comment — enters compose mode; next canvas click drops the pin */}
            <div className="add-object-toolbar__section add-object-toolbar__comment-section">
              <div className="add-object-toolbar__eyebrow add-object-toolbar__section-title">
                Add comment
              </div>
              <div className="add-object-toolbar__button-grid">
                {COMMENT_TYPES.map((c) => (
                  <button
                    key={c.value}
                    onClick={() => handleStartCommentCompose(c.value)}
                    className="add-object-toolbar__pill"
                    title={`Drop a ${c.label.toLowerCase()} on the canvas`}
                  >
                    <span>{c.icon}</span>
                    {c.label}
                  </button>
                ))}
              </div>
              <div className="add-object-toolbar__hint">
                Then click on the canvas to place the pin.
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
