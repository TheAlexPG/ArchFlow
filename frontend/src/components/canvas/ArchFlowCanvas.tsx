import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  addEdge,
  type Connection as RFConnection,
  type Node,
  type Edge,
  type NodeTypes,
  type EdgeTypes,
  MarkerType,
  type OnSelectionChangeParams,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { useCallback, useEffect, useMemo } from 'react'

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

export function ArchFlowCanvas() {
  const { data: objects = [] } = useObjects()
  const { data: connections = [] } = useConnections()
  const createConnection = useCreateConnection()
  const { selectNode, selectEdge } = useCanvasStore()

  const initialNodes = useMemo(() => objects.map(objectToNode), [objects])
  const initialEdges = useMemo(() => connections.map(connectionToEdge), [connections])

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges)

  // Sync when data changes
  useEffect(() => {
    setNodes(objects.map((obj, i) => {
      const existing = nodes.find((n) => n.id === obj.id)
      if (existing) {
        return { ...existing, data: { object: obj } satisfies C4NodeData }
      }
      return objectToNode(obj, i)
    }))
  }, [objects]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    setEdges(connections.map(connectionToEdge))
  }, [connections]) // eslint-disable-line react-hooks/exhaustive-deps

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
    ({ nodes: selectedNodes, edges: selectedEdges }: OnSelectionChangeParams) => {
      if (selectedNodes.length > 0) {
        selectNode(selectedNodes[0].id)
      } else if (selectedEdges.length > 0) {
        selectEdge(selectedEdges[0].id)
      } else {
        selectNode(null)
      }
    },
    [selectNode, selectEdge],
  )

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
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
      className="bg-neutral-950"
    >
      <Background color="#333" gap={20} size={1} />
      <Controls className="!bg-neutral-800 !border-neutral-700 !shadow-lg [&>button]:!bg-neutral-800 [&>button]:!border-neutral-700 [&>button]:!text-neutral-300 [&>button:hover]:!bg-neutral-700" />
      <MiniMap
        nodeColor="#3b82f6"
        maskColor="rgba(0, 0, 0, 0.7)"
        className="!bg-neutral-900 !border-neutral-700"
      />
    </ReactFlow>
  )
}
