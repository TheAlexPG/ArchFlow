import { memo, useEffect, useId, useRef, useState } from 'react'
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
// Internal padding so nodes don't kiss the frame edges. ~18px each side in
// viewBox coords keeps the content airy but still prominent.
const PAD = 18

// Default node size when a DiagramObjectData row doesn't carry width/height
// (older diagrams where resize was never persisted). ArchFlowCanvas applies
// 320×220 for groups and leaves others for ReactFlow's default — but for the
// preview we want a stable rectangle, so 180×60 is a reasonable mid-size.
const DEFAULT_W = 180
const DEFAULT_H = 60
const GROUP_DEFAULT_W = 320
const GROUP_DEFAULT_H = 220

// Cap rendered nodes so ultra-dense diagrams don't turn into illegible noise.
// Anything past this gets folded into a "+N more" overlay.
const MAX_NODES = 20

// Minimum rendered node footprint in viewBox units — keeps 2-3 nodes readable.
const MIN_NODE_W = 24
const MIN_NODE_H = 16
const MIN_ACTOR_R = 9

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

// Types we emit per-type linear gradients for. Actor gets a radialGradient
// instead, so it's not in this list.
const RECT_TYPES: ObjectType[] = [
  'system',
  'app',
  'store',
  'component',
  'group',
  'external_system',
]

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
  /** Projected (viewBox-space) rect. */
  x: number
  y: number
  w: number
  h: number
  /** Truthy for group nodes so we can draw them first (behind the others) and
   *  with a dashed stroke. */
  isGroup: boolean
  /** Projected centre — cached to avoid recomputing for each incident edge. */
  cx: number
  cy: number
}

interface Prepared {
  nodes: PreparedNode[]
  /** Number of nodes that had to be dropped because of MAX_NODES. 0 if none. */
  hiddenCount: number
  /** Average rendered footprint in viewBox units — used to derive stroke
   *  widths that scale with density without getting line-arty. */
  avgSize: number
}

/** Resolve {DiagramObjectData, ModelObject} pairs into normalized projected
 *  geometry inside the shared viewBox. Returns null if no usable nodes. */
function prepareNodes(
  diagramObjects: DiagramObjectData[],
  objectById: Map<string, ModelObject>,
): Prepared | null {
  interface RawNode {
    id: string
    type: ObjectType
    x: number
    y: number
    w: number
    h: number
    isGroup: boolean
  }
  const raws: RawNode[] = []
  for (const dObj of diagramObjects) {
    const obj = objectById.get(dObj.object_id)
    if (!obj) continue
    const isGroup = obj.type === 'group'
    const w = dObj.width ?? (isGroup ? GROUP_DEFAULT_W : DEFAULT_W)
    const h = dObj.height ?? (isGroup ? GROUP_DEFAULT_H : DEFAULT_H)
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

  // Cap at MAX_NODES. Preference: keep groups (structural context) then pick
  // the nodes closest to the overall centroid so the thumbnail represents the
  // "centre of mass" of the diagram rather than a random corner.
  let hiddenCount = 0
  let chosen = raws
  if (raws.length > MAX_NODES) {
    // Centroid of all node centres.
    let sx = 0
    let sy = 0
    for (const n of raws) {
      sx += n.x + n.w / 2
      sy += n.y + n.h / 2
    }
    const cx = sx / raws.length
    const cy = sy / raws.length
    const scored = raws.map((n) => {
      const dx = n.x + n.w / 2 - cx
      const dy = n.y + n.h / 2 - cy
      // Distance score; groups get a bonus so they survive the cut.
      const bonus = n.isGroup ? -1e6 : 0
      return { n, score: dx * dx + dy * dy + bonus }
    })
    scored.sort((a, b) => a.score - b.score)
    chosen = scored.slice(0, MAX_NODES).map((s) => s.n)
    hiddenCount = raws.length - chosen.length
  }

  // Bounding box of the chosen set
  let minX = Infinity
  let minY = Infinity
  let maxX = -Infinity
  let maxY = -Infinity
  for (const n of chosen) {
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

  // Singleton case: shrink so one-node diagrams don't fill the whole frame.
  const isSingleton = chosen.length === 1

  const nodes: PreparedNode[] = chosen.map((n) => {
    let rx = n.x
    let ry = n.y
    let rw = n.w
    let rh = n.h
    if (isSingleton) {
      const mcx = n.x + n.w / 2
      const mcy = n.y + n.h / 2
      rw = n.w * 0.55
      rh = n.h * 0.55
      rx = mcx - rw / 2
      ry = mcy - rh / 2
    }
    // Project into viewBox coords.
    let px = offsetX + (rx - minX) * scale
    let py = offsetY + (ry - minY) * scale
    let pw = rw * scale
    let ph = rh * scale

    // Enforce minimum footprint so leaf nodes always read — expand about the
    // node's centre so the projected layout stays balanced. Groups are framing
    // containers and naturally larger; skip the bump for them.
    if (!n.isGroup) {
      if (n.type === 'actor') {
        const r = Math.max(pw, ph) / 2
        if (r < MIN_ACTOR_R) {
          const cx2 = px + pw / 2
          const cy2 = py + ph / 2
          pw = MIN_ACTOR_R * 2
          ph = MIN_ACTOR_R * 2
          px = cx2 - pw / 2
          py = cy2 - ph / 2
        }
      } else {
        if (pw < MIN_NODE_W) {
          const cx2 = px + pw / 2
          px = cx2 - MIN_NODE_W / 2
          pw = MIN_NODE_W
        }
        if (ph < MIN_NODE_H) {
          const cy2 = py + ph / 2
          py = cy2 - MIN_NODE_H / 2
          ph = MIN_NODE_H
        }
      }
    }

    return {
      id: n.id,
      type: n.type,
      x: px,
      y: py,
      w: pw,
      h: ph,
      isGroup: n.isGroup,
      cx: px + pw / 2,
      cy: py + ph / 2,
    }
  })

  // Average projected node size — used to scale stroke widths.
  let sizeSum = 0
  for (const n of nodes) sizeSum += (n.w + n.h) / 2
  const avgSize = sizeSum / nodes.length

  return { nodes, hiddenCount, avgSize }
}

/** Smoothstep-ish bezier between two projected points. dx = half the x-span,
 *  which gives a soft S-curve when nodes are left/right-aligned and a flatter
 *  curve when they're stacked. */
function edgePath(ax: number, ay: number, bx: number, by: number): string {
  const dx = (bx - ax) / 2
  return `M ${ax.toFixed(2)} ${ay.toFixed(2)} C ${(ax + dx).toFixed(2)} ${ay.toFixed(2)}, ${(bx - dx).toFixed(2)} ${by.toFixed(2)}, ${bx.toFixed(2)} ${by.toFixed(2)}`
}

// ─── Real SVG ─────────────────────────────────────────────────────────────────

interface RealSvgProps {
  diagramObjects: DiagramObjectData[]
  objectById: Map<string, ModelObject>
  connections: Connection[]
}

function RealSvg({ diagramObjects, objectById, connections }: RealSvgProps) {
  // Stable unique prefix for per-card <defs> IDs — prevents gradient/filter
  // collisions when multiple previews are mounted on the same page. useId
  // returns a deterministic string per React tree slot, stable across renders.
  const uid = useId().replace(/:/g, '')

  const prepared = prepareNodes(diagramObjects, objectById)
  if (!prepared) return null
  const { nodes, hiddenCount, avgSize } = prepared

  // Edges: filter to connections whose source AND target are in the rendered
  // set (drops edges to nodes we trimmed for MAX_NODES).
  const rendered = new Set(nodes.map((n) => n.id))
  const edges = connections.filter(
    (c) => rendered.has(c.source_id) && rendered.has(c.target_id),
  )
  const centreById = new Map<string, [number, number]>()
  for (const n of nodes) centreById.set(n.id, [n.cx, n.cy])

  // Draw order: groups first (behind), then leaf nodes. Within each bucket
  // data order is preserved.
  const groupNodes = nodes.filter((n) => n.isGroup)
  const leafNodes = nodes.filter((n) => !n.isGroup)

  // Stroke scales gently with average node footprint — thicker for sparse
  // layouts (so they feel present) and slightly thinner for dense ones (so
  // rectangles don't bleed into one another).
  const strokeW = Math.max(1.1, Math.min(2, 1.0 + avgSize / 80))

  // IDs used for per-type gradients and the shared drop-shadow filter.
  const rectGradId = (t: ObjectType) => `pv-${uid}-rect-${t}`
  const actorGradId = `pv-${uid}-actor`
  const shadowId = `pv-${uid}-shadow`
  const vignetteId = `pv-${uid}-vignette`

  return (
    <svg
      width="100%"
      height="100%"
      viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
      preserveAspectRatio="xMidYMid meet"
    >
      <defs>
        {/* Per-type linear gradients: bright-ish at the top, fading toward a
            translucent base. Gives rects a "plate" feel instead of a hollow
            outline. Opacities kept low so dense layouts don't oversaturate. */}
        {RECT_TYPES.map((t) => {
          const c = colorFor(t)
          return (
            <linearGradient
              key={t}
              id={rectGradId(t)}
              x1="0"
              y1="0"
              x2="0"
              y2="1"
            >
              <stop offset="0%" stopColor={c} stopOpacity={0.22} />
              <stop offset="100%" stopColor={c} stopOpacity={0.05} />
            </linearGradient>
          )
        })}
        {/* Radial gradient for actors — light highlight in the upper-left so
            circles read as spheres rather than flat discs. */}
        <radialGradient id={actorGradId} cx="30%" cy="30%" r="75%">
          <stop offset="0%" stopColor="#c084fc" stopOpacity={0.38} />
          <stop offset="100%" stopColor="#c084fc" stopOpacity={0.04} />
        </radialGradient>
        {/* Shared drop-shadow filter, applied once to the node group so the
            GPU only does a single filter pass for the whole layer. */}
        <filter
          id={shadowId}
          x="-10%"
          y="-10%"
          width="120%"
          height="120%"
        >
          <feDropShadow
            dx="0"
            dy="1"
            stdDeviation="1.2"
            floodColor="#000"
            floodOpacity={0.35}
          />
        </filter>
        {/* Subtle central-ellipse vignette to push the content forward. */}
        <radialGradient id={vignetteId} cx="50%" cy="45%" r="70%">
          <stop offset="0%" stopColor="#000" stopOpacity={0} />
          <stop offset="100%" stopColor="#000" stopOpacity={0.28} />
        </radialGradient>
      </defs>

      {/* Vignette — draw behind everything else. */}
      <rect
        x={0}
        y={0}
        width={VIEW_W}
        height={VIEW_H}
        fill={`url(#${vignetteId})`}
      />

      {/* Groups (dashed frame + faint fill) — behind everything */}
      {groupNodes.map((n) => {
        const color = colorFor(n.type)
        return (
          <rect
            key={n.id}
            x={n.x}
            y={n.y}
            width={n.w}
            height={n.h}
            rx={4}
            fill={`url(#${rectGradId('group')})`}
            stroke={color}
            strokeWidth={Math.max(1, strokeW * 0.9)}
            strokeDasharray="4 2.5"
            strokeOpacity={0.85}
          />
        )
      })}

      {/* Edges — smoothstep-ish beziers between node centres. Drawn under the
          leaf nodes so their endpoints get absorbed by the rects, giving a
          clean map-view feel without an arrowhead marker. */}
      <g stroke="#52525b" strokeOpacity={0.7} strokeWidth={0.8} fill="none" strokeLinecap="round">
        {edges.map((e) => {
          const s = centreById.get(e.source_id)
          const t = centreById.get(e.target_id)
          if (!s || !t) return null
          return <path key={e.id} d={edgePath(s[0], s[1], t[0], t[1])} />
        })}
      </g>

      {/* Leaf nodes — wrapped in a group so the drop-shadow filter runs once. */}
      <g filter={`url(#${shadowId})`}>
        {leafNodes.map((n) => {
          const color = colorFor(n.type)
          if (n.type === 'actor') {
            const r = Math.max(2, Math.min(n.w, n.h) / 2)
            return (
              <circle
                key={n.id}
                cx={n.cx}
                cy={n.cy}
                r={r}
                fill={`url(#${actorGradId})`}
                stroke={color}
                strokeWidth={strokeW}
              />
            )
          }
          return (
            <rect
              key={n.id}
              x={n.x}
              y={n.y}
              width={n.w}
              height={n.h}
              rx={3.5}
              fill={`url(#${rectGradId(n.type)})`}
              stroke={color}
              strokeWidth={strokeW}
            />
          )
        })}
      </g>

      {/* "+N more" overlay when we trimmed nodes for density. */}
      {hiddenCount > 0 && (
        <g>
          <rect
            x={VIEW_W - 46}
            y={VIEW_H - 18}
            width={38}
            height={12}
            rx={2.5}
            fill="#0b0b0d"
            fillOpacity={0.72}
            stroke="#3f3f46"
            strokeWidth={0.6}
          />
          <text
            x={VIEW_W - 27}
            y={VIEW_H - 9}
            fontFamily="ui-monospace, SFMono-Regular, Menlo, monospace"
            fontSize={7}
            fill="#a1a1aa"
            textAnchor="middle"
          >
            +{hiddenCount} more
          </text>
        </g>
      )}
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
