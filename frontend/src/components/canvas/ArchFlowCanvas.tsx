import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useReactFlow,
  type Connection as RFConnection,
  type Node,
  type Edge,
  type NodeTypes,
  type EdgeTypes,
  MarkerType,
  type OnSelectionChangeParams,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { useCallback, useEffect, useRef } from 'react'

import { useConnections, useCreateConnection, useObjects } from '../../hooks/use-api'
import { useCanvasStore } from '../../stores/canvas-store'
import type { ModelObject, Connection } from '../../types/model'
import { C4Edge } from './C4Edge'
import { C4Node, type C4NodeData } from './C4Node'

const nodeTypes: NodeTypes = {
  c4: C4Node as unknown as NodeTypes['c4'],
}

const edgeTypes: EdgeTypes = {
  c4: C4Edge as unknown as EdgeTypes['c4'],
}

function objectToNode(obj: ModelObject, index: number): Node {
  return {
    id: obj.id,
    type: 'c4',
    position: { x: (index % 5) * 280 + 50, y: Math.floor(index / 5) * 200 + 50 },
    data: { object: obj } satisfies C4NodeData,
  }
}

function connectionToEdge(conn: Connection): Edge {
  return {
    id: conn.id,
    source: conn.source_id,
    target: conn.target_id,
    type: 'c4',
    markerEnd: { type: MarkerType.ArrowClosed, color: '#525252' },
    data: { label: conn.label, protocol: conn.protocol },
  }
}

function CanvasInner() {
  const { data: objects = [] } = useObjects()
  const { data: connections = [] } = useConnections()
  const createConnection = useCreateConnection()
  const { selectNode, selectEdge } = useCanvasStore()
  const { setNodes, setEdges, getNodes } = useReactFlow()
  const prevObjectsRef = useRef<string>('')
  const prevConnsRef = useRef<string>('')

  // Sync API data → React Flow (only when data actually changes)
  useEffect(() => {
    const key = objects.map((o) => `${o.id}:${o.updated_at}`).join(',')
    if (key === prevObjectsRef.current) return
    prevObjectsRef.current = key

    const currentNodes = getNodes()
    const newNodes = objects.map((obj, i) => {
      const existing = currentNodes.find((n) => n.id === obj.id)
      if (existing) {
        return { ...existing, data: { object: obj } satisfies C4NodeData }
      }
      return objectToNode(obj, i)
    })
    setNodes(newNodes)
  }, [objects, setNodes, getNodes])

  useEffect(() => {
    const key = connections.map((c) => c.id).join(',')
    if (key === prevConnsRef.current) return
    prevConnsRef.current = key
    setEdges(connections.map(connectionToEdge))
  }, [connections, setEdges])

  const onConnect = useCallback(
    (params: RFConnection) => {
      if (params.source && params.target) {
        createConnection.mutate({
          source_id: params.source,
          target_id: params.target,
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

  return (
    <ReactFlow
      defaultNodes={[]}
      defaultEdges={[]}
      onConnect={onConnect}
      onSelectionChange={onSelectionChange}
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

export function ArchFlowCanvas() {
  return <CanvasInner />
}
