import { useMemo, useState } from 'react'
import {
  useAddObjectToDiagram,
  useCreateObject,
  useDiagramObjects,
  useObjects,
  useTechnologies,
} from '../../hooks/use-api'
import { useCanvasStore } from '../../stores/canvas-store'
import { useWorkspaceStore } from '../../stores/workspace-store'
import type { ModelObject, ObjectType } from '../../types/model'
import { TYPE_ICONS, TYPE_LABELS } from '../canvas/node-utils'
import { ObjectContextMenu } from '../common/ObjectContextMenu'

interface TreeNode {
  object: ModelObject
  children: TreeNode[]
}

function buildTree(objects: ModelObject[]): TreeNode[] {
  const map = new Map<string, TreeNode>()
  const roots: TreeNode[] = []

  for (const obj of objects) {
    map.set(obj.id, { object: obj, children: [] })
  }

  for (const obj of objects) {
    const node = map.get(obj.id)!
    if (obj.parent_id && map.has(obj.parent_id)) {
      map.get(obj.parent_id)!.children.push(node)
    } else {
      roots.push(node)
    }
  }

  return roots
}

function matchesSearch(
  obj: ModelObject,
  query: string,
  techText: Map<string, string>,
): boolean {
  const q = query.toLowerCase()
  return (
    obj.name.toLowerCase().includes(q) ||
    (obj.description?.toLowerCase().includes(q) ?? false) ||
    (techText.get(obj.id)?.includes(q) ?? false)
  )
}

interface ObjectTreeProps {
  diagramId?: string
}

export function ObjectTree({ diagramId }: ObjectTreeProps) {
  const { data: objects = [] } = useObjects()
  const { data: diagramObjects = [] } = useDiagramObjects(diagramId)
  const workspaceId = useWorkspaceStore((s) => s.currentWorkspaceId)
  const { data: catalog = [] } = useTechnologies(workspaceId)
  const [search, setSearch] = useState('')
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const { selectNode } = useCanvasStore()
  const createObject = useCreateObject()
  const addToDiagram = useAddObjectToDiagram()

  const inDiagramIds = useMemo(
    () => new Set(diagramObjects.map((d) => d.object_id)),
    [diagramObjects],
  )

  // Prebuild a per-object haystack with resolved technology names / slugs /
  // aliases so the search bar matches human terms like "postgres" instead
  // of UUIDs.
  const techText = useMemo(() => {
    const byId = new Map(catalog.map((t) => [t.id, t]))
    const map = new Map<string, string>()
    for (const o of objects) {
      const parts: string[] = []
      for (const id of o.technology_ids ?? []) {
        const t = byId.get(id)
        if (t) {
          parts.push(t.name.toLowerCase(), t.slug.toLowerCase())
          for (const alias of t.aliases ?? []) parts.push(alias.toLowerCase())
        }
      }
      map.set(o.id, parts.join(' '))
    }
    return map
  }, [objects, catalog])

  const tree = useMemo(() => buildTree(objects), [objects])

  const filteredObjects = search
    ? objects.filter((obj) => matchesSearch(obj, search, techText))
    : null

  const toggleExpand = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const handleAddToDiagram = (objectId: string) => {
    if (!diagramId) return
    addToDiagram.mutate({
      diagramId,
      objectId,
      x: 100 + Math.random() * 400,
      y: 100 + Math.random() * 300,
    })
  }

  const handleQuickCreate = (type: ObjectType) => {
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
  }

  return (
    <div className="w-64 bg-neutral-900 border-r border-neutral-800 flex flex-col h-full">
      <div className="px-3 py-2 border-b border-neutral-800">
        <div className="text-xs font-medium text-neutral-400 mb-2">Model objects</div>
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search objects..."
          className="w-full bg-neutral-800 text-neutral-200 text-xs rounded px-2 py-1.5 border border-neutral-700 outline-none focus:border-neutral-600"
        />
      </div>

      <div className="flex-1 overflow-y-auto py-1">
        {filteredObjects
          ? filteredObjects.map((obj) => (
              <TreeItem
                key={obj.id}
                obj={obj}
                depth={0}
                onSelect={selectNode}
                inDiagram={inDiagramIds.has(obj.id)}
                diagramId={diagramId}
                onAdd={handleAddToDiagram}
              />
            ))
          : tree.map((node) => (
              <TreeNodeItem
                key={node.object.id}
                node={node}
                depth={0}
                expanded={expanded}
                toggleExpand={toggleExpand}
                onSelect={selectNode}
                inDiagramIds={inDiagramIds}
                diagramId={diagramId}
                onAdd={handleAddToDiagram}
              />
            ))}
        {objects.length === 0 && (
          <div className="px-3 py-4 text-xs text-neutral-600 text-center">
            No objects yet. Use + button to create.
          </div>
        )}
      </div>

      {/* Quick create */}
      <div className="border-t border-neutral-800 px-3 py-2">
        <div className="text-[10px] text-neutral-600 mb-1.5">Or create new</div>
        <div className="flex flex-wrap gap-1">
          {(['system', 'actor', 'app', 'store', 'group'] as ObjectType[]).map((type) => (
            <button
              key={type}
              onClick={() => handleQuickCreate(type)}
              className="text-[10px] px-1.5 py-0.5 rounded bg-neutral-800 text-neutral-400 hover:bg-neutral-700 hover:text-neutral-200 transition-colors flex items-center gap-1"
            >
              <span className="opacity-60">{TYPE_ICONS[type]}</span>
              {TYPE_LABELS[type]}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}

function TreeNodeItem({
  node,
  depth,
  expanded,
  toggleExpand,
  onSelect,
  inDiagramIds,
  diagramId,
  onAdd,
}: {
  node: TreeNode
  depth: number
  expanded: Set<string>
  toggleExpand: (id: string) => void
  onSelect: (id: string) => void
  inDiagramIds: Set<string>
  diagramId?: string
  onAdd: (id: string) => void
}) {
  const hasChildren = node.children.length > 0
  const isExpanded = expanded.has(node.object.id)
  const inDiagram = inDiagramIds.has(node.object.id)

  return (
    <>
      <div
        className="flex items-center gap-1 px-2 py-1 hover:bg-neutral-800 cursor-pointer group"
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
        onClick={() => onSelect(node.object.id)}
      >
        {hasChildren ? (
          <button
            onClick={(e) => {
              e.stopPropagation()
              toggleExpand(node.object.id)
            }}
            className="text-neutral-600 hover:text-neutral-400 text-[10px] w-4 shrink-0"
          >
            {isExpanded ? '▾' : '▸'}
          </button>
        ) : (
          <span className="w-4 shrink-0" />
        )}
        <span className="text-xs opacity-50">{TYPE_ICONS[node.object.type]}</span>
        <span
          className="text-xs truncate flex-1"
          style={{ color: inDiagram ? '#d4d4d4' : '#737373' }}
        >
          {node.object.name}
        </span>
        {diagramId && !inDiagram && (
          <button
            onClick={(e) => {
              e.stopPropagation()
              onAdd(node.object.id)
            }}
            className="opacity-0 group-hover:opacity-100 text-[10px] text-blue-400 hover:text-blue-300 px-1 transition-opacity"
            title="Add to diagram"
          >
            +
          </button>
        )}
        {diagramId && inDiagram && (
          <span className="text-[9px] text-neutral-600" title="In this diagram">●</span>
        )}
        <div className="opacity-0 group-hover:opacity-100 transition-opacity">
          <ObjectContextMenu object={node.object} diagramId={diagramId} />
        </div>
      </div>
      {isExpanded &&
        node.children.map((child) => (
          <TreeNodeItem
            key={child.object.id}
            node={child}
            depth={depth + 1}
            expanded={expanded}
            toggleExpand={toggleExpand}
            onSelect={onSelect}
            inDiagramIds={inDiagramIds}
            diagramId={diagramId}
            onAdd={onAdd}
          />
        ))}
    </>
  )
}

function TreeItem({
  obj,
  depth,
  onSelect,
  inDiagram,
  diagramId,
  onAdd,
}: {
  obj: ModelObject
  depth: number
  onSelect: (id: string) => void
  inDiagram: boolean
  diagramId?: string
  onAdd: (id: string) => void
}) {
  return (
    <div
      className="flex items-center gap-1 px-2 py-1 hover:bg-neutral-800 cursor-pointer group"
      style={{ paddingLeft: `${depth * 16 + 8}px` }}
      onClick={() => onSelect(obj.id)}
    >
      <span className="text-xs opacity-50">{TYPE_ICONS[obj.type]}</span>
      <span
        className="text-xs truncate flex-1"
        style={{ color: inDiagram ? '#d4d4d4' : '#737373' }}
      >
        {obj.name}
      </span>
      {diagramId && !inDiagram && (
        <button
          onClick={(e) => {
            e.stopPropagation()
            onAdd(obj.id)
          }}
          className="opacity-0 group-hover:opacity-100 text-[10px] text-blue-400 hover:text-blue-300 px-1 transition-opacity"
          title="Add to diagram"
        >
          +
        </button>
      )}
      {diagramId && inDiagram && (
        <span className="text-[9px] text-neutral-600">●</span>
      )}
      <div className="opacity-0 group-hover:opacity-100 transition-opacity">
        <ObjectContextMenu object={obj} diagramId={diagramId} />
      </div>
    </div>
  )
}
