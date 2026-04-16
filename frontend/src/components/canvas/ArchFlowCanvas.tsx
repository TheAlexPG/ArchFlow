import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  ConnectionMode,
  useReactFlow,
  type Connection as RFConnection,
  type Node,
  type Edge,
  type NodeTypes,
  type EdgeTypes,
  type NodeDragEvent,
  MarkerType,
  type OnSelectionChangeParams,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { useCallback, useEffect, useRef } from 'react'

import {
  useConnections,
  useCreateConnection,
  useDeleteConnection,
  useDiagramObjects,
  useObjects,
  useSaveDiagramPosition,
} from '../../hooks/use-api'
import { useCanvasStore } from '../../stores/canvas-store'
import type { ModelObject, Connection } from '../../types/model'
import { C4Edge } from './C4Edge'
import { C4Node, type C4NodeData } from './C4Node'
import { GroupNode } from './GroupNode'

const nodeTypes: NodeTypes = {
  c4: C4Node as unknown as NodeTypes['c4'],
  group: GroupNode as unknown as NodeTypes['group'],
}

const edgeTypes: EdgeTypes = {
  c4: C4Edge as unknown as EdgeTypes['c4'],
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
    markerStart: bidirectional ? { type: MarkerType.ArrowClosed, color: '#525252' } : undefined,
    data: {
      label: conn.label,
      protocol: conn.protocol,
      shape: conn.shape,
      labelSize: conn.label_size,
    },
  }
}

interface ArchFlowCanvasProps {
  diagramId?: string
}

function CanvasInner({ diagramId }: ArchFlowCanvasProps) {
  const { data: allObjects = [] } = useObjects()
  const { data: connections = [] } = useConnections()
  const { data: diagramObjects = [] } = useDiagramObjects(diagramId)
  const createConnection = useCreateConnection()
  const deleteConnection = useDeleteConnection()
  const saveDiagramPosition = useSaveDiagramPosition()
  const { selectNode, selectEdge } = useCanvasStore()
  const { setNodes, setEdges, getNodes } = useReactFlow()
  const prevKeyRef = useRef<string>('')
  const prevConnsRef = useRef<string>('')

  // Build nodes from diagram objects (scoped to this diagram)
  useEffect(() => {
    if (!diagramId) return

    const objectMap = new Map(allObjects.map((o) => [o.id, o]))
    const nodes: Node[] = diagramObjects
      .map((dObj) => {
        const obj = objectMap.get(dObj.object_id)
        if (!obj) return null
        return {
          id: obj.id,
          type: obj.type === 'group' ? 'group' : 'c4',
          position: { x: dObj.position_x, y: dObj.position_y },
          data: { object: obj } satisfies C4NodeData,
        } as Node
      })
      .filter(Boolean) as Node[]

    const key = nodes.map((n) => `${n.id}:${n.position.x}:${n.position.y}`).join(',')
    if (key === prevKeyRef.current) return
    prevKeyRef.current = key

    // Preserve dragged positions
    const currentNodes = getNodes()
    const merged = nodes.map((n) => {
      const existing = currentNodes.find((cn) => cn.id === n.id)
      if (existing) return { ...n, position: existing.position }
      return n
    })
    setNodes(merged)
  }, [diagramId, allObjects, diagramObjects, setNodes, getNodes])

  // Filter connections to only those between objects in this diagram
  useEffect(() => {
    const objectIds = new Set(diagramObjects.map((d) => d.object_id))
    const filtered = connections.filter(
      (c) => objectIds.has(c.source_id) && objectIds.has(c.target_id),
    )
    const key = filtered.map((c) => c.id).join(',')
    if (key === prevConnsRef.current) return
    prevConnsRef.current = key
    setEdges(filtered.map(connectionToEdge))
  }, [connections, diagramObjects, setEdges])

  const onNodeDragStop = useCallback(
    (_event: NodeDragEvent, node: Node) => {
      if (diagramId) {
        saveDiagramPosition.mutate({
          diagramId,
          objectId: node.id,
          x: node.position.x,
          y: node.position.y,
        })
      }
    },
    [diagramId, saveDiagramPosition],
  )

  const onConnect = useCallback(
    (params: RFConnection) => {
      if (params.source && params.target) {
        createConnection.mutate({
          source_id: params.source,
          target_id: params.target,
          source_handle: params.sourceHandle || null,
          target_handle: params.targetHandle || null,
        })
      }
    },
    [createConnection],
  )

  const onSelectionChange = useCallback(
    ({ nodes: sel, edges: selEdges }: OnSelectionChangeParams) => {
      if (sel.length > 0) selectNode(sel[0].id)
      else if (selEdges.length > 0) selectEdge(selEdges[0].id)
      else selectNode(null)
    },
    [selectNode, selectEdge],
  )

  const onEdgesDelete = useCallback(
    (edges: Edge[]) => {
      for (const edge of edges) {
        deleteConnection.mutate(edge.id)
      }
    },
    [deleteConnection],
  )

  return (
    <ReactFlow
      defaultNodes={[]}
      defaultEdges={[]}
      connectionMode={ConnectionMode.Loose}
      onNodeDragStop={onNodeDragStop}
      onConnect={onConnect}
      onSelectionChange={onSelectionChange}
      onEdgesDelete={onEdgesDelete}
      deleteKeyCode={['Backspace', 'Delete']}
      nodeTypes={nodeTypes}
      edgeTypes={edgeTypes}
      fitView
      snapToGrid
      snapGrid={[20, 20]}
      defaultEdgeOptions={{
        type: 'c4',
        markerEnd: { type: MarkerType.ArrowClosed, color: '#525252' },
      }}
      style={{ background: '#0a0a0a' }}
    >
      <Background color="#333" gap={20} size={1} />
      <Controls />
      <MiniMap
        nodeColor="#3b82f6"
        maskColor="rgba(0, 0, 0, 0.7)"
        style={{ background: '#171717', border: '1px solid #333' }}
      />
    </ReactFlow>
  )
}

export function ArchFlowCanvas({ diagramId }: ArchFlowCanvasProps) {
  return <CanvasInner diagramId={diagramId} />
}
