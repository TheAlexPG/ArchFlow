import { memo, useEffect, useRef, useState } from 'react'
import {
  useDiagramObjects,
  useObjects,
  useConnections,
  type DiagramObjectData,
} from '../../hooks/use-api'
import type {
  Connection,
  ModelObject,
  ObjectType,
} from '../../types/model'

// ─── Types & constants ────────────────────────────────────────────────────────

export interface DiagramPreviewSvgProps {
  /** When omitted we always render the fallback motif (no fetch). */
  diagramId?: string
  /** Optional — the diagram type (a C4 DiagramType literal, or any string —
   *  unknown values fall through to the custom motif), used for the fallback
   *  motif when data hasn't loaded yet or the diagram has zero nodes. */
  fallbackType?: string
  /** Optional — draft id, passed to object / connection hooks so draft forks
   *  show their own pool. Default undefined → live pool. */
  draftId?: string | null
  className?: string
}

// ViewBox dimensions — tuned so either card geometry (h-[90px] or h-[140px])
// rescales cleanly via preserveAspectRatio=xMidYMid meet.
const VIEW_W = 300
const VIEW_H = 140
const PAD = 10

// Default node size when a DiagramObjectData row doesn't carry width/height
// (older diagrams where resize was never persisted). ArchFlowCanvas applies
// 320×220 for groups and leaves others for ReactFlow's default — but for the
// preview we want a stable rectangle, so 180×60 is a reasonable mid-size.
const DEFAULT_W = 180
const DEFAULT_H = 60
const GROUP_DEFAULT_W = 320
const GROUP_DEFAULT_H = 220

/** Type → stroke colour (matches minimap + canvas node restyle). */
function colorFor(type: ObjectType | undefined): string {
  switch (type) {
    case 'actor':
    case 'system':
      return '#c084fc' // purple
    case 'app':
    case 'store':
      return '#FF6B35' // coral
    case 'component':
      return '#60a5fa' // blue
    case 'group':
      return '#4ade80' // green
    case 'external_system':
      return '#fbbf24' // amber
    default:
      return '#52525b' // text-4 fallback
  }
}

// ─── IntersectionObserver-gated mount ─────────────────────────────────────────
//
// For large grids (hundreds of cards) we don't want every card firing
// `useDiagramObjects(id)` at mount. We gate the actual data hook behind a
// viewport observer: until the card scrolls close to the viewport, we render
// only the type fallback. This keeps initial paint cheap and only ever fetches
// for cards the user can plausibly see.

function useInViewport<T extends Element>(
  /** Root margin passed to IntersectionObserver — widening the root makes the
   *  fetch fire slightly before the card is visible so the real preview is
   *  ready by the time it scrolls in. */
  rootMargin = '200px',
) {
  const ref = useRef<T | null>(null)
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    if (visible) return // once visible, stay visible — no point re-observing
    const el = ref.current
    if (!el) return
    // Fallback for environments without IntersectionObserver — just reveal.
    // Use a microtask so we don't setState synchronously inside the effect
    // body (which the linter flags as cascading-render-prone).
    if (typeof IntersectionObserver === 'undefined') {
      const id = setTimeout(() => setVisible(true), 0)
      return () => clearTimeout(id)
    }
    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setVisible(true)
            io.disconnect()
            break
          }
        }
      },
      { rootMargin },
    )
    io.observe(el)
    return () => io.disconnect()
  }, [visible, rootMargin])

  return [ref, visible] as const
}

// ─── Fallback SVGs (pre-baked per-type motif) ─────────────────────────────────

function FallbackSvg({ type }: { type?: string }) {
  if (type === 'system_landscape' || type === 'system_context') {
    return (
      <svg
        width="100%"
        height="100%"
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        preserveAspectRatio="xMidYMid meet"
      >
        <circle cx="50" cy="70" r="12" fill="none" stroke="#c084fc" strokeWidth="1.5" />
        <rect x="100" y="55" width="50" height="30" rx="4" fill="#16161a" stroke="#FF6B35" strokeWidth="1.5" />
        <rect x="180" y="55" width="50" height="30" rx="4" fill="#16161a" stroke="#FF6B35" strokeWidth="1.5" />
        <rect x="260" y="55" width="30" height="30" rx="4" fill="#16161a" stroke="#FF6B35" strokeWidth="1.5" />
        <path d="M62 70 Q80 70 100 70" stroke="#52525b" strokeWidth="1" fill="none" />
        <path d="M150 70 L180 70" stroke="#52525b" strokeWidth="1" fill="none" />
        <path d="M230 70 L260 70" stroke="#52525b" strokeWidth="1" fill="none" />
      </svg>
    )
  }
  if (type === 'container') {
    return (
      <svg
        width="100%"
        height="100%"
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        preserveAspectRatio="xMidYMid meet"
      >
        <rect x="40" y="30" width="80" height="30" rx="4" fill="#16161a" stroke="#60a5fa" strokeWidth="1.5" />
        <rect x="40" y="80" width="80" height="30" rx="4" fill="#16161a" stroke="#60a5fa" strokeWidth="1.5" />
        <rect x="180" y="55" width="80" height="30" rx="4" fill="#16161a" stroke="#4ade80" strokeWidth="1.5" />
        <path d="M120 45 Q150 45 180 65" stroke="#52525b" strokeWidth="1" fill="none" />
        <path d="M120 95 Q150 95 180 75" stroke="#52525b" strokeWidth="1" fill="none" />
      </svg>
    )
  }
  if (type === 'component') {
    return (
      <svg
        width="100%"
        height="100%"
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        preserveAspectRatio="xMidYMid meet"
      >
        <rect x="30" y="40" width="60" height="20" rx="3" fill="#16161a" stroke="#FF6B35" strokeWidth="1.2" />
        <rect x="30" y="70" width="60" height="20" rx="3" fill="#16161a" stroke="#FF6B35" strokeWidth="1.2" />
        <rect x="120" y="25" width="60" height="20" rx="3" fill="#16161a" stroke="#FF6B35" strokeWidth="1.2" />
        <rect x="120" y="55" width="60" height="20" rx="3" fill="#16161a" stroke="#FF6B35" strokeWidth="1.2" />
        <rect x="120" y="85" width="60" height="20" rx="3" fill="#16161a" stroke="#FF6B35" strokeWidth="1.2" />
        <rect x="210" y="55" width="60" height="20" rx="3" fill="#16161a" stroke="#4ade80" strokeWidth="1.2" />
        <path d="M90 50 L120 35" stroke="#52525b" strokeWidth="0.8" fill="none" />
        <path d="M90 80 L120 65" stroke="#52525b" strokeWidth="0.8" fill="none" />
        <path d="M180 65 L210 65" stroke="#52525b" strokeWidth="0.8" fill="none" />
      </svg>
    )
  }
  // custom / undefined fallback
  return (
    <svg
      width="100%"
      height="100%"
      viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
      preserveAspectRatio="xMidYMid meet"
    >
      <rect x="60" y="45" width="70" height="50" rx="4" fill="#16161a" stroke="#FF6B35" strokeWidth="1.5" />
      <rect x="170" y="45" width="70" height="50" rx="4" fill="#16161a" stroke="#52525b" strokeWidth="1.5" />
      <path d="M130 70 L170 70" stroke="#52525b" strokeWidth="1" fill="none" />
    </svg>
  )
}

// ─── Geometry ─────────────────────────────────────────────────────────────────

interface PreparedNode {
  id: string
  type: ObjectType
  x: number
  y: number
  w: number
  h: number
  /** Truthy for group nodes so we can draw them first (behind the others) and
   *  with a dashed stroke. */
  isGroup: boolean
}

/** Resolve {DiagramObjectData, ModelObject} pairs into normalized geometry
 *  inside the shared viewBox. Returns null if no usable nodes. */
function prepareNodes(
  diagramObjects: DiagramObjectData[],
  objectById: Map<string, ModelObject>,
): { nodes: PreparedNode[]; transform: (x: number, y: number) => [number, number]; scale: number } | null {
  const raws: PreparedNode[] = []
  for (const dObj of diagramObjects) {
    const obj = objectById.get(dObj.object_id)
    if (!obj) continue
    const isGroup = obj.type === 'group'
    const w =
      dObj.width ?? (isGroup ? GROUP_DEFAULT_W : DEFAULT_W)
    const h =
      dObj.height ?? (isGroup ? GROUP_DEFAULT_H : DEFAULT_H)
    raws.push({
      id: obj.id,
      type: obj.type,
      x: dObj.position_x,
      y: dObj.position_y,
      w,
      h,
      isGroup,
    })
  }
  if (raws.length === 0) return null

  // Bounding box
  let minX = Infinity
  let minY = Infinity
  let maxX = -Infinity
  let maxY = -Infinity
  for (const n of raws) {
    if (n.x < minX) minX = n.x
    if (n.y < minY) minY = n.y
    if (n.x + n.w > maxX) maxX = n.x + n.w
    if (n.y + n.h > maxY) maxY = n.y + n.h
  }
  const bbW = Math.max(1, maxX - minX)
  const bbH = Math.max(1, maxY - minY)

  // Scale bbox into (VIEW_W-2*PAD) × (VIEW_H-2*PAD), preserve aspect.
  const innerW = VIEW_W - 2 * PAD
  const innerH = VIEW_H - 2 * PAD
  const scale = Math.min(innerW / bbW, innerH / bbH)
  // Centre inside the viewBox.
  const offsetX = PAD + (innerW - bbW * scale) / 2
  const offsetY = PAD + (innerH - bbH * scale) / 2

  const transform = (x: number, y: number): [number, number] => [
    offsetX + (x - minX) * scale,
    offsetY + (y - minY) * scale,
  ]

  return { nodes: raws, transform, scale }
}

// ─── Real SVG ─────────────────────────────────────────────────────────────────

interface RealSvgProps {
  diagramObjects: DiagramObjectData[]
  objectById: Map<string, ModelObject>
  connections: Connection[]
}

function RealSvg({ diagramObjects, objectById, connections }: RealSvgProps) {
  const prepared = prepareNodes(diagramObjects, objectById)
  if (!prepared) return null
  const { nodes, transform, scale } = prepared

  // Single-node case → centre at 50% scale so it doesn't fill the whole frame.
  // Build a lookup for edge centres (projected coords).
  const centreById = new Map<string, [number, number]>()
  for (const n of nodes) {
    const [tx, ty] = transform(n.x + n.w / 2, n.y + n.h / 2)
    centreById.set(n.id, [tx, ty])
  }

  // Edges: filter to connections whose source AND target are in this diagram.
  const inSet = new Set(nodes.map((n) => n.id))
  const edges = connections.filter(
    (c) => inSet.has(c.source_id) && inSet.has(c.target_id),
  )

  // Draw order: groups first (behind), then non-groups. Within each bucket we
  // keep the data order — groups tend to be authored before their children so
  // this happens to match real canvas Z-order.
  const groupNodes = nodes.filter((n) => n.isGroup)
  const leafNodes = nodes.filter((n) => !n.isGroup)

  // For single-node layouts, shrink a bit so it reads as "a node" rather than
  // "a full-width panel".
  const isSingleton = nodes.length === 1

  // Thin stroke that scales slightly with the fit scale — keeps thumbnails
  // from becoming line-art for dense diagrams.
  const strokeW = Math.max(1, Math.min(1.5, 1.5 * Math.sqrt(scale)))

  return (
    <svg
      width="100%"
      height="100%"
      viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
      preserveAspectRatio="xMidYMid meet"
    >
      {/* Groups (dashed) — behind everything */}
      {groupNodes.map((n) => {
        const [tx, ty] = transform(n.x, n.y)
        const tw = n.w * scale
        const th = n.h * scale
        const color = colorFor(n.type)
        return (
          <rect
            key={n.id}
            x={tx}
            y={ty}
            width={tw}
            height={th}
            rx={3}
            fill={color}
            fillOpacity={0.06}
            stroke={color}
            strokeWidth={strokeW}
            strokeDasharray="3 2"
          />
        )
      })}

      {/* Edges — drawn under leaf nodes so their endpoints get visually
          "absorbed" by the node rects; for a map-view feel this is nicer than
          visible arrow-heads poking out. */}
      {edges.map((e) => {
        const s = centreById.get(e.source_id)
        const t = centreById.get(e.target_id)
        if (!s || !t) return null
        return (
          <line
            key={e.id}
            x1={s[0]}
            y1={s[1]}
            x2={t[0]}
            y2={t[1]}
            stroke="#52525b"
            strokeWidth={0.8}
            strokeOpacity={0.9}
          />
        )
      })}

      {/* Leaf nodes */}
      {leafNodes.map((n) => {
        const color = colorFor(n.type)
        // Single-node: downscale to 50% around its centre.
        let x = n.x
        let y = n.y
        let w = n.w
        let h = n.h
        if (isSingleton) {
          const cx = n.x + n.w / 2
          const cy = n.y + n.h / 2
          w = n.w * 0.5
          h = n.h * 0.5
          x = cx - w / 2
          y = cy - h / 2
        }
        const [tx, ty] = transform(x, y)
        const tw = w * scale
        const th = h * scale

        if (n.type === 'actor') {
          // Actors render as circles in the canvas — keep that affordance.
          const cx = tx + tw / 2
          const cy = ty + th / 2
          const r = Math.max(2, Math.min(tw, th) / 2)
          return (
            <circle
              key={n.id}
              cx={cx}
              cy={cy}
              r={r}
              fill={color}
              fillOpacity={0.1}
              stroke={color}
              strokeWidth={strokeW}
            />
          )
        }

        return (
          <rect
            key={n.id}
            x={tx}
            y={ty}
            width={tw}
            height={th}
            rx={3}
            fill={color}
            fillOpacity={0.1}
            stroke={color}
            strokeWidth={strokeW}
          />
        )
      })}
    </svg>
  )
}

// ─── Main component ───────────────────────────────────────────────────────────

/** Renders a simplified preview of a diagram using its actual nodes and
 *  connections. Falls back to a type-specific pre-baked motif until the data
 *  loads or when the diagram has no nodes at all.
 *
 *  Wrapped in React.memo so parent re-renders (e.g. hover state on the card)
 *  don't cause the preview to recompute. Data fetches are gated by an
 *  IntersectionObserver so cards below the fold don't trigger network requests
 *  until the user scrolls near them. */
function DiagramPreviewSvgImpl({
  diagramId,
  fallbackType,
  draftId,
  className,
}: DiagramPreviewSvgProps) {
  const [wrapRef, inView] = useInViewport<HTMLDivElement>()

  // Gate the data hooks on in-view AND a real diagramId — skipping the
  // diagramId disables the react-query fetch entirely. Once visible the hook
  // stays enabled so we don't yo-yo the fetch on scroll.
  const shouldFetch = inView && !!diagramId
  const diagramObjectsQ = useDiagramObjects(shouldFetch ? diagramId : undefined)
  const objectsQ = useObjects(shouldFetch ? draftId ?? undefined : undefined)
  const connectionsQ = useConnections(shouldFetch ? draftId ?? undefined : undefined)

  const diagramObjects = diagramObjectsQ.data
  const objects = objectsQ.data
  const connections = connectionsQ.data

  const ready =
    shouldFetch &&
    Array.isArray(diagramObjects) &&
    Array.isArray(objects) &&
    Array.isArray(connections)

  // Build an object lookup once the three queries resolve. Also detect the
  // "empty diagram" case so we can flip back to the fallback motif — a blank
  // thumbnail is worse than the pre-baked placeholder.
  const objectById = ready ? new Map(objects.map((o) => [o.id, o])) : null
  const hasUsableNodes =
    ready &&
    objectById !== null &&
    diagramObjects.some((d) => objectById.has(d.object_id))

  return (
    <div
      ref={wrapRef}
      className={className}
      style={{ width: '100%', height: '100%' }}
    >
      {ready && hasUsableNodes && objectById ? (
        <RealSvg
          diagramObjects={diagramObjects}
          objectById={objectById}
          connections={connections}
        />
      ) : (
        <FallbackSvg type={fallbackType} />
      )}
    </div>
  )
}

export const DiagramPreviewSvg = memo(DiagramPreviewSvgImpl)
