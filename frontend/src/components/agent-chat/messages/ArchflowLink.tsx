import { useNavigate, useParams } from 'react-router-dom'
import { cn } from '../../../utils/cn'
import { emitFocusObject, emitFocusConnection } from '../../../lib/canvas-events'
import { useCanvasStore } from '../../../stores/canvas-store'
import type { ArchflowLinkTarget } from '../../../lib/archflow-link'

// ─── ArchflowLink ─────────────────────────────────────────────────────────────
//
// Renders an `archflow://` deep-link as a clickable inline pill. Three target
// types are supported:
//
//   object     → select the node on the active canvas (and navigate to its
//                diagram first if we're not already on a diagram page).
//   diagram    → navigate to /diagram/{id}
//   connection → select the edge on the active canvas
//
// Canvas selection uses the pub/sub emitters from `canvas-events.ts` so this
// component works without being inside a ReactFlowProvider.

/** @deprecated Use ArchflowLinkTarget from lib/archflow-link instead. */
export type ArchflowKind = ArchflowLinkTarget

interface ArchflowLinkProps {
  /** Resolved target type from the parsed `archflow://` URL. */
  target?: ArchflowLinkTarget
  /**
   * @deprecated Use `target` instead. Kept for backward compatibility with
   * components written before task-048.
   */
  kind?: ArchflowKind
  /** UUID of the target resource. */
  id: string
  /** Display label — legacy prop for callers that don't pass children. */
  label?: string
  /** Display content. Takes priority over `label`. */
  children?: React.ReactNode
}

export function ArchflowLink({ target, kind, id, label, children }: ArchflowLinkProps) {
  // Resolve target: new callers use `target`, legacy callers use `kind`.
  const resolvedTarget: ArchflowLinkTarget = (target ?? kind) as ArchflowLinkTarget
  const navigate = useNavigate()
  // Grab the current diagram param so we can decide whether a navigation is
  // needed before dispatching the canvas event.
  const { diagramId } = useParams<{ diagramId?: string }>()
  const selectNode = useCanvasStore((s) => s.selectNode)
  const selectEdge = useCanvasStore((s) => s.selectEdge)

  const handleClick = (e: React.MouseEvent) => {
    e.preventDefault()

    if (resolvedTarget === 'diagram') {
      navigate(`/diagram/${id}`)
      return
    }

    if (resolvedTarget === 'object') {
      if (!diagramId) {
        // Not on a diagram page — we can't centre on a node without one.
        // The canvas event is still emitted in case navigation lands on a
        // diagram that mounts the listener before the event fires.
        navigate('/')
      }
      // Select in the canvas store (opens the sidebar) and emit the focus
      // event so CanvasInner can call fitView on that node.
      selectNode(id)
      emitFocusObject(id)
      return
    }

    if (resolvedTarget === 'connection') {
      // Select the edge in the sidebar and emit focus.
      selectEdge(id)
      emitFocusConnection(id)
    }
  }

  const iconMap: Record<ArchflowLinkTarget, string> = {
    object: '◈',
    diagram: '⊞',
    connection: '⇢',
  }

  const displayContent = children ?? label ?? `${resolvedTarget}/${id}`

  return (
    <a
      href={`archflow://${resolvedTarget}/${id}`}
      onClick={handleClick}
      data-testid="archflow-link"
      data-archflow-kind={resolvedTarget}
      data-archflow-id={id}
      className={cn(
        'inline-flex items-center gap-1 px-1.5 py-0.5 mx-0.5 rounded',
        'text-[11px] font-mono',
        'bg-coral/10 text-coral border border-coral/30',
        'hover:bg-coral/20 hover:border-coral/50',
        'transition-colors duration-100 cursor-pointer',
      )}
    >
      <span aria-hidden="true">{iconMap[resolvedTarget]}</span>
      {displayContent}
    </a>
  )
}
