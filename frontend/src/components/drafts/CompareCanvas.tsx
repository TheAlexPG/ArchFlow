import {
  Background,
  ConnectionMode,
  MarkerType,
  MiniMap,
  ReactFlow,
  useEdgesState,
  useNodesState,
  useOnViewportChange,
  useReactFlow,
  type Edge,
  type EdgeTypes,
  type Node,
  type NodeTypes,
  type Viewport,
} from '@xyflow/react'
import { useEffect, useMemo } from 'react'

import {
  useConnections,
  useDiagramObjects,
  useObjects,
} from '../../hooks/use-api'
import { useDiagram } from '../../hooks/use-diagrams'
import type {
  Connection,
  DraftDiffStatusFork,
  DraftDiffStatusSource,
  PerDiagramDiffEntry,
} from '../../types/model'
import { ActorNode } from '../canvas/ActorNode'
import { C4Edge } from '../canvas/C4Edge'
import { C4Node, type C4NodeData } from '../canvas/C4Node'
import { ExternalSystemNode } from '../canvas/ExternalSystemNode'
import { GroupNode } from '../canvas/GroupNode'

const nodeTypes: NodeTypes = {
  c4: C4Node as unknown as NodeTypes['c4'],
  group: GroupNode as unknown as NodeTypes['group'],
  actor: ActorNode as unknown as NodeTypes['actor'],
  external: ExternalSystemNode as unknown as NodeTypes['external'],
}

const edgeTypes: EdgeTypes = { c4: C4Edge as unknown as EdgeTypes['c4'] }

// Diff-driven outline colors applied to each node/edge.
const STATUS_OUTLINE: Record<string, string> = {
  new: '#22c55e',
  modified: '#f59e0b',
  deleted: '#ef4444',
  unchanged: '',
}

function connectionToEdge(conn: Connection): Edge {
  const bidirectional = conn.direction === 'bidirectional'
  return {
    id: conn.id,
    source: conn.source_id,
    target: conn.target_id,
    sourceHandle: conn.source_handle,
    targetHandle: conn.target_handle,
    type: 'c4',
    markerEnd: { type: MarkerType.ArrowClosed, color: '#525252' },
    markerStart: bidirectional
      ? { type: MarkerType.ArrowClosed, color: '#525252' }
      : undefined,
    data: {
      label: conn.label,
      protocol: conn.protocol,
      shape: conn.shape,
      labelSize: conn.label_size,
    },
  }
}

interface CompareCanvasProps {
  diagramId: string
  side: 'source' | 'fork'
  diff: PerDiagramDiffEntry | undefined
  /** Which forked diagram's draft is this — used to fetch fork-scoped rows. */
  draftId: string | null
  /** True when the mouse is over this side — only then it emits viewport changes. */
  isActive: boolean
  /** `null` means nobody has driven the viewport yet — each side fits
   *  independently until the first user pan/zoom on either canvas. */
  viewport: Viewport | null
  onViewportChange: (vp: Viewport) => void
  movedOnFork: Set<string>
  resizedOnFork: Set<string>
}

/**
 * Read-only ReactFlow that renders the same scene as the live canvas, but
 * with nodes/edges outlined by their diff status and with pan/zoom synced
 * to its sibling compare canvas through the parent.
 *
 * Source side: passes no draftId, so we see the live model.
 * Fork side:   passes draftId so we include the fork's clones.
 */
export function CompareCanvas({
  diagramId,
  side,
  diff,
  draftId,
  isActive,
  viewport,
  onViewportChange,
  movedOnFork,
  resizedOnFork,
}: CompareCanvasProps) {
  const { data: diagram } = useDiagram(diagramId)
  const fetchDraftId = side === 'fork' ? draftId : null
  const { data: allObjects = [] } = useObjects(fetchDraftId)
  const { data: connections = [] } = useConnections(fetchDraftId)
  const { data: diagramObjects = [] } = useDiagramObjects(diagramId)
  const rf = useReactFlow()

  // Propagate viewport edits from this canvas to its sibling via the
  // parent. Only emit while the mouse is over us, otherwise we'd create
  // a feedback loop with setViewport below.
  useOnViewportChange({
    onChange: (vp) => {
      if (isActive) onViewportChange(vp)
    },
  })

  // When the other side is driving, sync ours to the shared viewport.
  // Skip when no viewport has been set yet so we don't stomp fitView.
  useEffect(() => {
    if (!isActive && viewport) {
      rf.setViewport(viewport, { duration: 0 })
    }
  }, [viewport, isActive, rf])

  const statusFor = (id: string): string => {
    if (!diff) return 'unchanged'
    const map =
      side === 'source'
        ? (diff.source_objects as Record<string, DraftDiffStatusSource>)
        : (diff.fork_objects as Record<string, DraftDiffStatusFork>)
    return map[id] ?? 'unchanged'
  }

  const connStatusFor = (id: string): string => {
    if (!diff) return 'unchanged'
    const map =
      side === 'source' ? diff.source_connections : diff.fork_connections
    return map[id] ?? 'unchanged'
  }

  const computedNodes: Node[] = useMemo(() => {
    const objectMap = new Map(allObjects.map((o) => [o.id, o]))
    return diagramObjects
      .map((dObj) => {
        const obj = objectMap.get(dObj.object_id)
        if (!obj) return null
        const status = statusFor(obj.id)
        const outline = STATUS_OUTLINE[status]
        const isLayoutChanged =
          side === 'fork' &&
          (movedOnFork.has(obj.id) || resizedOnFork.has(obj.id))
        // Layout-only changes get a dashed amber outline so the user can
        // tell "I moved/resized this" from "I edited fields".
        const style: React.CSSProperties = outline
          ? {
              outline: `2px solid ${outline}`,
              outlineOffset: 4,
              borderRadius: 10,
            }
          : isLayoutChanged
            ? {
                outline: '2px dashed #f59e0b',
                outlineOffset: 4,
                borderRadius: 10,
              }
            : {}
        const node: Node = {
          id: obj.id,
          type:
            obj.type === 'group'
              ? 'group'
              : obj.type === 'actor'
                ? 'actor'
                : obj.type === 'external_system'
                  ? 'external'
                  : 'c4',
          position: { x: dObj.position_x, y: dObj.position_y },
          data: { object: obj } satisfies C4NodeData,
          draggable: false,
          selectable: false,
          connectable: false,
          style,
          zIndex: obj.type === 'group' ? 0 : 1,
        }
        if (dObj.width != null && dObj.height != null) {
          node.width = dObj.width
          node.height = dObj.height
        }
        return node
      })
      .filter(Boolean) as Node[]
  }, [allObjects, diagramObjects, diff, movedOnFork, resizedOnFork, side])

  const computedEdges: Edge[] = useMemo(() => {
    const objectIds = new Set(diagramObjects.map((d) => d.object_id))
    return connections
      .filter((c) => objectIds.has(c.source_id) && objectIds.has(c.target_id))
      .map(connectionToEdge)
      .map((e) => {
        const status = connStatusFor(e.id)
        const outline = STATUS_OUTLINE[status]
        if (!outline) return e
        return {
          ...e,
          style: {
            ...e.style,
            stroke: outline,
            strokeWidth: 2.5,
          },
        }
      })
  }, [connections, diagramObjects, diff])

  // ReactFlow works best when the nodes/edges it owns are mutated through
  // its change handlers — otherwise edges can fail to attach to handles
  // during the initial paint. Mirror the computed arrays into its state.
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([])
  useEffect(() => {
    setNodes(computedNodes)
  }, [computedNodes, setNodes])
  useEffect(() => {
    setEdges(computedEdges)
  }, [computedEdges, setEdges])

  if (!diagram) {
    return (
      <div className="flex items-center justify-center h-full text-sm text-neutral-600">
        Loading diagram…
      </div>
    )
  }

  // When there are no nodes, skip ReactFlow entirely — fitView with 0 nodes
  // produces an invalid transform that leaves a solid black canvas.
  const isEmpty = computedNodes.length === 0
  if (isEmpty) {
    return (
      <div
        style={{
          position: 'absolute',
          inset: 0,
          background: '#0a0a0a',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: '#525252',
          fontSize: 12,
        }}
      >
        No objects on this diagram
      </div>
    )
  }

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      nodeTypes={nodeTypes}
      edgeTypes={edgeTypes}
      nodesDraggable={false}
      nodesConnectable={false}
      elementsSelectable={false}
      connectionMode={ConnectionMode.Loose}
      panOnDrag
      zoomOnScroll
      zoomOnPinch
      panOnScroll={false}
      fitView
      fitViewOptions={{ padding: 0.25 }}
      proOptions={{ hideAttribution: true }}
      style={{ background: '#0a0a0a' }}
    >
      <Background color="#262626" gap={10} size={1} />
      <MiniMap
        nodeColor="#3b82f6"
        maskColor="rgba(0,0,0,0.75)"
        style={{ background: '#171717', border: '1px solid #262626' }}
        pannable
        zoomable
      />
    </ReactFlow>
  )
}
