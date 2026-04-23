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
  MarkerType,
  type OnSelectionChangeParams,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { useCallback, useEffect, useMemo, useRef } from 'react'

import {
  useConnections,
  useCreateComment,
  useCreateConnection,
  useDeleteConnection,
  useDiagramObjects,
  useFlows,
  useObjects,
  useSaveDiagramPosition,
  useUpdateObject,
} from '../../hooks/use-api'
import { useDiagram } from '../../hooks/use-diagrams'
import { useCanvasStore } from '../../stores/canvas-store'
import type { ModelObject, Connection } from '../../types/model'
import { C4Edge } from './C4Edge'
import { ActorNode } from './ActorNode'
import { C4Node, type C4NodeData } from './C4Node'
import { CanvasComments } from './CanvasComments'
import { ExternalSystemNode } from './ExternalSystemNode'
import { GroupNode } from './GroupNode'
import { extractFilterValue, overlayStyleFor, type FilterDim } from './overlay-utils'
import { detectParentGroup, findSpatialGroupMembers, nodeToRect } from './group-utils'
import { useDiagramSocket } from '../../hooks/use-realtime'
import { CursorsOverlay, RemoteSelectionsOverlay } from './CursorsOverlay'
import { PresenceRoster } from './PresenceRoster'

const nodeTypes: NodeTypes = {
  c4: C4Node as unknown as NodeTypes['c4'],
  group: GroupNode as unknown as NodeTypes['group'],
  actor: ActorNode as unknown as NodeTypes['actor'],
  external: ExternalSystemNode as unknown as NodeTypes['external'],
}

const edgeTypes: EdgeTypes = {
  c4: C4Edge as unknown as EdgeTypes['c4'],
}

function connectionToEdge(conn: Connection): Edge {
  const arrow = { type: MarkerType.ArrowClosed, color: '#525252' }
  const markerEnd =
    conn.direction === 'undirected' ? undefined : arrow
  const markerStart =
    conn.direction === 'bidirectional' ? arrow : undefined
  // Embed direction + endpoints in the id so React Flow treats any change
  // as a new edge (unmount + remount). Without this, React Flow merges by
  // id: `markerStart: undefined` does NOT clear a previously-set markerStart,
  // and after a flip source/target may stay visually attached to the old
  // endpoints because React Flow doesn't re-route existing edges.
  return {
    id: `${conn.id}:${conn.direction}:${conn.source_id}:${conn.target_id}`,
    source: conn.source_id,
    target: conn.target_id,
    sourceHandle: conn.source_handle,
    targetHandle: conn.target_handle,
    type: 'c4',
    markerEnd,
    markerStart,
    data: {
      label: conn.label,
      protocol_id: conn.protocol_id,
      shape: conn.shape,
      labelSize: conn.label_size,
      direction: conn.direction,
      // Raw connection UUID (without the direction fingerprint suffix) so
      // other parts of the canvas can look up flow steps / dependency chains
      // by the original ID.
      connId: conn.id,
    },
  }
}

interface ArchFlowCanvasProps {
  diagramId?: string
}

function CanvasInner({ diagramId }: ArchFlowCanvasProps) {
  // If this diagram is a forked draft, we must ask for its draft-scoped
  // objects/connections — otherwise we'd only get the live model and miss
  // every forked clone the user has on this canvas.
  const { data: diagram } = useDiagram(diagramId)
  const draftId = diagram?.draft_id ?? null
  const { data: allObjects = [] } = useObjects(draftId)
  const { data: connections = [] } = useConnections(draftId)
  const { data: diagramObjects = [] } = useDiagramObjects(diagramId)
  const createConnection = useCreateConnection(draftId)
  const deleteConnection = useDeleteConnection()
  const saveDiagramPosition = useSaveDiagramPosition()
  const {
    selectNode,
    selectEdge,
    dependenciesFocusId,
    setDependenciesFocus,
    activeFilter,
    activeFilterValue,
    playingFlowId,
    playingStepIdx,
    activeBranch,
    commentComposeType,
    setCommentComposeType,
  } = useCanvasStore()
  const filterDim = activeFilter as FilterDim

  // For the tag/technology filter dims an object can carry multiple values;
  // a node matches the chip if any of its values equal the selected value.
  // status/teams dims reuse the single-value extractor.
  const matchesFilterValue = useCallback(
    (obj: ModelObject): boolean => {
      if (!activeFilterValue) return true
      if (filterDim === 'tags') return obj.tags?.includes(activeFilterValue) ?? false
      if (filterDim === 'technology')
        return obj.technology_ids?.includes(activeFilterValue) ?? false
      return extractFilterValue(obj, filterDim) === activeFilterValue
    },
    [activeFilterValue, filterDim],
  )
  const { data: flows = [] } = useFlows(diagramId)
  const updateObject = useUpdateObject()
  const createComment = useCreateComment()

  // Map edgeId → step number (1-based) for the currently active flow branch,
  // plus the id of the "current" step being played. Drives edge highlighting
  // during flow playback.
  const flowPlayback = useMemo(() => {
    if (!playingFlowId) return null
    const flow = flows.find((f) => f.id === playingFlowId)
    if (!flow) return null
    const branchSteps = flow.steps.filter((s) =>
      !activeBranch || activeBranch === 'main' ? !s.branch : s.branch === activeBranch,
    )
    const stepNumbers = new Map<string, number>()
    branchSteps.forEach((s, i) => stepNumbers.set(s.connection_id, i + 1))
    const currentConnId = branchSteps[playingStepIdx]?.connection_id ?? null
    return { stepNumbers, currentConnId }
  }, [playingFlowId, playingStepIdx, activeBranch, flows])
  const { setNodes, setEdges, getNodes, getEdges, screenToFlowPosition } = useReactFlow()

  // Realtime collaboration: cursor sharing with other users in the same diagram.
  const { cursors, selections, presence, sendCursor, sendSelection } = useDiagramSocket(
    diagramId ?? null,
  )

  const onMouseMove = useCallback(
    (event: React.MouseEvent) => {
      if (document.hidden) return
      // Chrome emits clientX/Y relative to the *visual* viewport when a
      // visual-viewport offset is active (pinch-zoom or OS-level display
      // zoom on some setups), while getBoundingClientRect() — which
      // screenToFlowPosition uses internally — returns layout-viewport
      // coordinates.  Safari always keeps both in the same space, so it is
      // unaffected.  Correcting clientX/Y by visualViewport.offsetLeft/Top
      // brings Chrome into the same layout-viewport frame before the
      // screenToFlowPosition call and eliminates the constant-per-session
      // cursor offset that Chrome senders otherwise produce for remote peers.
      const vvOffX = window.visualViewport?.offsetLeft ?? 0
      const vvOffY = window.visualViewport?.offsetTop ?? 0
      // Disable snap-to-grid for cursor broadcasts so the pin tracks the actual
      // pointer sub-pixel position rather than the nearest grid intersection.
      // Without this, at high zoom levels the grid-snapped error (up to
      // gridSize/2 flow units = gridSize/2 * zoom screen pixels) becomes
      // visually significant — e.g. at zoom=2 with snapGrid=[10,10], the pin
      // can drift up to 10 CSS pixels from the real cursor.
      const pos = screenToFlowPosition(
        { x: event.clientX + vvOffX, y: event.clientY + vvOffY },
        { snapToGrid: false },
      )
      sendCursor(pos.x, pos.y)
    },
    [screenToFlowPosition, sendCursor],
  )

  const prevKeyRef = useRef<string>('')
  const prevConnsRef = useRef<string>('')
  // Stores {groupId -> {nodeId -> startPosition}} while a group drag is in progress.
  const groupDragStartRef = useRef<Map<string, { x: number; y: number }> | null>(null)

  // Direct-neighbor dependency chain for the "View dependencies" overlay.
  // Focused node + every object with an incoming/outgoing edge to it within
  // this diagram. Nodes/edges outside the chain are dimmed on the canvas.
  // Declared before the node/edge build effects because they reference it
  // in their deps array (would hit TDZ otherwise).
  const dependencyChain = useMemo(() => {
    if (!dependenciesFocusId) return null
    const inDiagram = new Set(diagramObjects.map((d) => d.object_id))
    if (!inDiagram.has(dependenciesFocusId)) return null
    const chain = new Set<string>([dependenciesFocusId])
    const connectedEdgeIds = new Set<string>()
    for (const c of connections) {
      if (c.source_id === dependenciesFocusId && inDiagram.has(c.target_id)) {
        chain.add(c.target_id)
        connectedEdgeIds.add(c.id)
      } else if (c.target_id === dependenciesFocusId && inDiagram.has(c.source_id)) {
        chain.add(c.source_id)
        connectedEdgeIds.add(c.id)
      }
    }
    return { nodes: chain, edges: connectedEdgeIds }
  }, [dependenciesFocusId, connections, diagramObjects])

  // Build nodes from diagram objects (scoped to this diagram)
  useEffect(() => {
    if (!diagramId) return

    const objectMap = new Map(allObjects.map((o) => [o.id, o]))
    const nodes: Node[] = diagramObjects
      .map((dObj) => {
        const obj = objectMap.get(dObj.object_id)
        if (!obj) return null
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
          zIndex: obj.type === 'group' ? 0 : 1,
        }
        // Restore persisted node size from the diagram_objects row so the
        // resized dimensions survive page reloads. For groups that never
        // got resized, seed a sensible default so NodeResizer has something
        // to grow from — otherwise ReactFlow uses its 150px type default
        // which fights with our min-size constraints.
        if (dObj.width != null && dObj.height != null) {
          node.width = dObj.width
          node.height = dObj.height
        } else if (obj.type === 'group') {
          node.width = 320
          node.height = 220
        }
        return node
      })
      .filter(Boolean) as Node[]

    // Include updated_at + persisted size in key so nodes re-render when
    // any of these change.
    const key = nodes
      .map((n) => {
        const obj = (n.data as C4NodeData).object
        return `${n.id}:${n.position.x}:${n.position.y}:${n.width ?? ''}:${n.height ?? ''}:${obj.updated_at}:${n.type}`
      })
      .join(',')
    if (key === prevKeyRef.current) return
    prevKeyRef.current = key

    // The diagram-objects cache is authoritative for position + size.
    // Carry over selection / overlay styling from the previous nodes, and
    // ONLY preserve local state while a drag or resize is in progress (so
    // an incoming remote echo doesn't yank the node out from under the
    // user). Anything else — including another collaborator's drag — we
    // let through so two-browser edits actually propagate.
    const currentNodes = getNodes()
    const merged = nodes.map((n) => {
      const existing = currentNodes.find((cn) => cn.id === n.id)
      const obj = (n.data as C4NodeData).object
      const dimForChain =
        dependencyChain && !dependencyChain.nodes.has(n.id)
      const dimForChip = !matchesFilterValue(obj)
      const opacity = dimForChain || dimForChip ? 0.15 : 1
      const overlay = overlayStyleFor(obj, filterDim)
      const baseStyle = { ...(overlay ?? {}), opacity }
      if (existing) {
        const isDragging = (existing as Node & { dragging?: boolean }).dragging === true
        return {
          ...n,
          position: isDragging ? existing.position : n.position,
          selected: existing.selected,
          width: existing.width != null && isDragging ? existing.width : n.width,
          height: existing.height != null && isDragging ? existing.height : n.height,
          style: { ...existing.style, ...baseStyle },
        }
      }
      return { ...n, style: baseStyle }
    })
    setNodes(merged)
  }, [
    diagramId,
    allObjects,
    diagramObjects,
    setNodes,
    getNodes,
    dependencyChain,
    filterDim,
    matchesFilterValue,
  ])

  // Sync connections → React Flow edges AND apply overlay/flow-playback styling.
  //
  // Both concerns are merged into one effect intentionally: the overlay effect
  // (dependencyChain, filterDim, flowPlayback) and the connection-sync effect
  // previously called setEdges independently.  When both fired in the same React
  // render cycle (e.g. a flow is playing and a connection's direction changes),
  // the overlay effect ran AFTER the sync effect, called getEdges() which still
  // returned React Flow's committed pre-sync edges, and clobbered the freshly
  // built edge list — causing direction / marker changes to visually revert.
  // Merging into one effect guarantees a single setEdges call per render, so
  // the clobber is structurally impossible.
  useEffect(() => {
    const objectIds = new Set(diagramObjects.map((d) => d.object_id))
    const filtered = connections.filter(
      (c) => objectIds.has(c.source_id) && objectIds.has(c.target_id),
    )

    // ── Connection-structure key ──────────────────────────────────────────
    // Include all visual fields so the edge rebuild runs whenever any of them
    // change (not just direction or id).
    // source_id and target_id MUST be included: a flip operation swaps them
    // without changing direction/shape/handles.  For same-side handles
    // (e.g. top↔top) the handle names are symmetric under swap, so a flip
    // would otherwise produce an identical key and the early-return would
    // prevent setEdges from being called — leaving the canvas arrow stale.
    const connKey = filtered
      .map(
        (c) =>
          `${c.id}:${c.source_id}:${c.target_id}:${c.shape}:${c.label_size}:${c.direction}:${c.label ?? ''}:${c.protocol_id ?? ''}:${c.source_handle ?? ''}:${c.target_handle ?? ''}`,
      )
      .join(',')

    // ── Overlay/playback key ──────────────────────────────────────────────
    // Captures the visual-only inputs that affect opacity / flowStep but do
    // NOT change edge structure (id / markers / path shape).
    const overlayKey = `${dependencyChain ? JSON.stringify([...dependencyChain.edges]) : ''}|${filterDim}|${flowPlayback?.currentConnId ?? ''}|${flowPlayback ? [...flowPlayback.stepNumbers.entries()].map(([k,v]) => k+':'+v).join(',') : ''}`

    const combinedKey = connKey + '||' + overlayKey
    if (combinedKey === prevConnsRef.current) return
    prevConnsRef.current = combinedKey

    // Preserve selection state across re-renders + apply overlay opacity +
    // flow playback step number/highlight.
    const currentEdges = getEdges()
    setEdges(
      filtered.map(connectionToEdge).map((e) => {
        const connId = (e.data as { connId: string }).connId
        // Match by connId, not edge id — when direction changes the fingerprinted
        // id differs but we still want to preserve the `selected` state.
        const existing = currentEdges.find(
          (ce) => ((ce.data as { connId?: string })?.connId ?? ce.id) === connId,
        )
        const flowStep = flowPlayback?.stepNumbers.get(connId)
        const isCurrent = flowPlayback?.currentConnId === connId
        const flowOpacity = flowPlayback
          ? flowStep
            ? 1
            : 0.1
          : dependencyChain && !dependencyChain.edges.has(connId)
            ? 0.15
            : 1
        const withStyle = {
          ...e,
          style: { ...e.style, opacity: flowOpacity },
          data: {
            ...(e.data || {}),
            flowStep: flowStep ?? null,
            flowCurrent: isCurrent,
          },
        }
        return existing?.selected ? { ...withStyle, selected: true } : withStyle
      }),
    )
  }, [connections, diagramObjects, setEdges, getEdges, dependencyChain, flowPlayback, filterDim])

  // Apply dimming + color overlay to existing nodes whenever the dependency
  // focus or active filter changes. Edges are handled by the effect above
  // (merged to prevent a second setEdges call from clobbering direction changes).
  useEffect(() => {
    const currentNodes = getNodes()
    if (currentNodes.length > 0) {
      setNodes(
        currentNodes.map((n) => {
          const obj = (n.data as C4NodeData).object
          const overlay = overlayStyleFor(obj, filterDim)
          const dimForChain =
            dependencyChain && !dependencyChain.nodes.has(n.id)
          const dimForChip = !matchesFilterValue(obj)
          return {
            ...n,
            style: {
              ...n.style,
              // Overlay outline — clear it when no filter is active.
              outline: overlay?.outline ?? undefined,
              outlineOffset: overlay?.outlineOffset ?? undefined,
              opacity: dimForChain || dimForChip ? 0.15 : 1,
            },
          }
        }),
      )
    }
  }, [dependencyChain, filterDim, matchesFilterValue, getNodes, setNodes])

  // ESC clears the dependencies focus overlay.
  useEffect(() => {
    if (!dependenciesFocusId) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setDependenciesFocus(null)
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [dependenciesFocusId, setDependenciesFocus])

  const focusObject = dependenciesFocusId
    ? allObjects.find((o) => o.id === dependenciesFocusId)
    : null

  /**
   * Collect all node IDs that should travel with the given group on drag.
   * Union of:
   *   - nodes whose parent_id chain reaches this group (persisted membership)
   *   - nodes whose rect is currently inside the group's rect (spatial)
   * The spatial side is what lets a group "pick up" nodes that were never
   * formally dropped into it (e.g. the user resized a group over existing
   * nodes, or added a group on top of a cluster).
   */
  const getGroupMemberIds = useCallback(
    (groupId: string): string[] => {
      const objectMap = new Map(allObjects.map((o) => [o.id, o]))
      const members = new Set<string>()
      for (const dObj of diagramObjects) {
        if (dObj.object_id === groupId) continue
        let current = objectMap.get(dObj.object_id)
        while (current) {
          if (current.parent_id === groupId) {
            members.add(dObj.object_id)
            break
          }
          current = current.parent_id ? objectMap.get(current.parent_id) : undefined
        }
      }
      for (const id of findSpatialGroupMembers(groupId, diagramObjects, allObjects)) {
        members.add(id)
      }
      return [...members]
    },
    [allObjects, diagramObjects],
  )

  const onNodeDrag = useCallback(
    (_event: React.MouseEvent, node: Node) => {
      const obj = allObjects.find((o) => o.id === node.id)
      if (!obj || obj.type !== 'group') return

      const currentNodes = getNodes()
      const groupNode = currentNodes.find((n) => n.id === node.id)
      if (!groupNode) return

      // On the very first drag event, snapshot positions of all members.
      if (!groupDragStartRef.current) {
        const memberIds = getGroupMemberIds(node.id)
        const startPositions = new Map<string, { x: number; y: number }>()
        startPositions.set(node.id, { x: groupNode.position.x, y: groupNode.position.y })
        for (const memberId of memberIds) {
          const memberNode = currentNodes.find((n) => n.id === memberId)
          if (memberNode) {
            startPositions.set(memberId, { x: memberNode.position.x, y: memberNode.position.y })
          }
        }
        groupDragStartRef.current = startPositions
      }

      const startPos = groupDragStartRef.current.get(node.id)
      if (!startPos) return
      const dx = node.position.x - startPos.x
      const dy = node.position.y - startPos.y

      if (dx === 0 && dy === 0) return

      const memberIds = new Set(getGroupMemberIds(node.id))
      setNodes(
        currentNodes.map((n) => {
          if (!memberIds.has(n.id)) return n
          const memberStart = groupDragStartRef.current?.get(n.id)
          if (!memberStart) return n
          return { ...n, position: { x: memberStart.x + dx, y: memberStart.y + dy } }
        }),
      )
    },
    [allObjects, getGroupMemberIds, getNodes, setNodes],
  )

  const onNodeDragStop = useCallback(
    (_event: React.MouseEvent, node: Node) => {
      if (!diagramId) return

      const obj = allObjects.find((o) => o.id === node.id)

      // Persist position for the dragged node.
      saveDiagramPosition.mutate({
        diagramId,
        objectId: node.id,
        x: node.position.x,
        y: node.position.y,
      })

      if (obj && obj.type === 'group') {
        // Persist positions for all children that were dragged with the group.
        const startPositions = groupDragStartRef.current
        groupDragStartRef.current = null

        if (startPositions) {
          const startPos = startPositions.get(node.id)
          if (startPos) {
            const dx = node.position.x - startPos.x
            const dy = node.position.y - startPos.y
            const currentNodes = getNodes()
            const memberIds = getGroupMemberIds(node.id)
            for (const memberId of memberIds) {
              const memberStart = startPositions.get(memberId)
              const memberNode = currentNodes.find((n) => n.id === memberId)
              if (memberStart && memberNode) {
                saveDiagramPosition.mutate({
                  diagramId,
                  objectId: memberId,
                  x: memberStart.x + dx,
                  y: memberStart.y + dy,
                })
              }
            }
          }
        }
      } else {
        // Non-group node: clear stale drag ref if any, then check spatial containment.
        groupDragStartRef.current = null

        if (obj) {
          const nodeRect = nodeToRect(
            node.id,
            node.position,
            node.width,
            node.height,
            allObjects,
          )
          const newParentId = detectParentGroup(node.id, nodeRect, diagramObjects, allObjects)
          if (newParentId !== (obj.parent_id ?? null)) {
            updateObject.mutate({ id: node.id, parent_id: newParentId })
          }
        }
      }
    },
    [diagramId, saveDiagramPosition, allObjects, diagramObjects, updateObject, getGroupMemberIds, getNodes],
  )


  const onConnect = useCallback(
    (params: RFConnection) => {
      if (params.source && params.target) {
        createConnection.mutate({
          source_id: params.source,
          target_id: params.target,
          source_handle: params.sourceHandle || null,
          target_handle: params.targetHandle || null,
          shape: 'smoothstep',
        })
      }
    },
    [createConnection],
  )

  const onSelectionChange = useCallback(
    ({ nodes: sel, edges: selEdges }: OnSelectionChangeParams) => {
      if (sel.length > 0) selectNode(sel[0].id)
      else if (selEdges.length > 0) {
        // Edge IDs are fingerprinted as `${connId}:${direction}` — pass the
        // raw connection UUID to the store so EdgeSidebar can fetch it.
        const selEdge = selEdges[0]
        const connId = ((selEdge.data as { connId?: string })?.connId) ?? selEdge.id
        selectEdge(connId)
      }
      else selectNode(null)
      // Broadcast to other users so they see who's looking at what.
      sendSelection(sel.map((n) => n.id))
    },
    [selectNode, selectEdge, sendSelection],
  )

  // Drop a canvas comment pin where the user just clicked, when a compose
   // mode is active. Plays well with pan/zoom because we translate screen
   // coords to the viewport's flow-space coords.
  const onPaneClick = useCallback(
    (event: React.MouseEvent) => {
      if (!commentComposeType || !diagramId) return
      const pos = screenToFlowPosition({ x: event.clientX, y: event.clientY })
      createComment.mutate({
        target_type: 'diagram',
        target_id: diagramId,
        comment_type: commentComposeType,
        body: '',
        position_x: pos.x,
        position_y: pos.y,
      })
      setCommentComposeType(null)
    },
    [commentComposeType, diagramId, createComment, screenToFlowPosition, setCommentComposeType],
  )

  // ESC cancels a pending comment compose.
  useEffect(() => {
    if (!commentComposeType) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setCommentComposeType(null)
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [commentComposeType, setCommentComposeType])

  const onEdgesDelete = useCallback(
    (edges: Edge[]) => {
      for (const edge of edges) {
        // Edge IDs are fingerprinted as `${connId}:${direction}` — extract
        // the raw connection UUID for the delete API call.
        const connId = ((edge.data as { connId?: string })?.connId) ?? edge.id
        deleteConnection.mutate(connId)
      }
    },
    [deleteConnection],
  )

  return (
    <>
      {commentComposeType && (
        <div
          style={{
            position: 'absolute',
            top: 12,
            left: '50%',
            transform: 'translateX(-50%)',
            zIndex: 25,
            padding: '6px 12px',
            background: '#171717',
            border: '1px solid #3b82f6',
            borderRadius: 8,
            fontSize: 12,
            color: '#e5e5e5',
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            boxShadow: '0 4px 12px rgba(0,0,0,0.4)',
          }}
        >
          <span>Click on the canvas to place a {commentComposeType} pin</span>
          <button
            onClick={() => setCommentComposeType(null)}
            style={{
              background: 'transparent',
              border: '1px solid #404040',
              color: '#a3a3a3',
              borderRadius: 4,
              padding: '2px 8px',
              cursor: 'pointer',
              fontSize: 11,
            }}
            title="Cancel (Esc)"
          >
            Cancel
          </button>
        </div>
      )}
      {focusObject && (
        <div
          style={{
            position: 'absolute',
            top: 12,
            left: '50%',
            transform: 'translateX(-50%)',
            zIndex: 20,
            display: 'flex',
            alignItems: 'center',
            gap: 12,
            padding: '8px 14px',
            background: '#171717',
            border: '1px solid #3b82f6',
            borderRadius: 8,
            color: '#e5e5e5',
            fontSize: 12,
            boxShadow: '0 4px 12px rgba(0,0,0,0.4)',
          }}
        >
          <span style={{ color: '#60a5fa' }}>🔗</span>
          <span>
            Dependencies of{' '}
            <span style={{ fontWeight: 600, color: '#f5f5f5' }}>{focusObject.name}</span>
          </span>
          <button
            onClick={() => setDependenciesFocus(null)}
            style={{
              background: 'transparent',
              border: '1px solid #404040',
              color: '#a3a3a3',
              borderRadius: 4,
              padding: '2px 8px',
              cursor: 'pointer',
              fontSize: 11,
            }}
            title="Clear (Esc)"
          >
            Clear
          </button>
        </div>
      )}
      <ReactFlow
      defaultNodes={[]}
      defaultEdges={[]}
      connectionMode={ConnectionMode.Loose}
      onNodeDrag={onNodeDrag}
      onNodeDragStop={onNodeDragStop}
      onConnect={onConnect}
      onSelectionChange={onSelectionChange}
      onEdgesDelete={onEdgesDelete}
      onPaneClick={onPaneClick}
      onMouseMove={onMouseMove}
      deleteKeyCode={['Backspace', 'Delete']}
      nodeTypes={nodeTypes}
      edgeTypes={edgeTypes}
      /*
       * Do not bump z-index of selected nodes. React Flow's default is to
       * elevate the selected node via inline `zIndex`, which re-evaluates
       * the stacking context and promotes the node to a fresh GPU
       * composition layer. Under the viewport's fractional-pixel transform,
       * this leaves the entire canvas rasterized blurry until the next pan.
       */
      elevateNodesOnSelect={false}
      /*
       * Performance: skip painting off-screen nodes/edges. Biggest win on
       * dense diagrams (100+ nodes) where most of them sit outside the
       * current viewport while the user is zoomed in on a subsection.
       */
      onlyRenderVisibleElements
      fitView
      snapToGrid
      snapGrid={[10, 10]}
      defaultEdgeOptions={{
        type: 'c4',
        markerEnd: { type: MarkerType.ArrowClosed, color: '#525252' },
      }}
      style={{
        background: '#0a0a0a',
        cursor: commentComposeType ? 'crosshair' : undefined,
      }}
    >
      <Background color="#333" gap={10} size={1} />
      <Controls />
      <MiniMap
        nodeColor="#3b82f6"
        maskColor="rgba(0, 0, 0, 0.7)"
        style={{ background: '#171717', border: '1px solid #333' }}
      />
      {diagramId && <CanvasComments diagramId={diagramId} />}
      <CursorsOverlay cursors={cursors} />
      <RemoteSelectionsOverlay selections={selections} />
      <PresenceRoster users={presence} />
    </ReactFlow>
    </>
  )
}

export function ArchFlowCanvas({ diagramId }: ArchFlowCanvasProps) {
  return <CanvasInner diagramId={diagramId} />
}
