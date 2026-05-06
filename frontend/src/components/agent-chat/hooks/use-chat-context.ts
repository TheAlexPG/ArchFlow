import { useLocation, useSearchParams } from 'react-router-dom'
import { useMemo } from 'react'
import type { ChatContext } from '../types'
import { useCanvasStore } from '../../../stores/canvas-store'
import { useWorkspaceStore } from '../../../stores/workspace-store'

// ─── URL parsing ────────────────────────────────────────────────────────────
//
// We read the route from `useLocation().pathname` directly (not `useParams`)
// because the chat bubble lives OUTSIDE `<Routes>` (so a single instance can
// use useNavigate from anywhere). useParams returns {} when called outside the
// matched route element — the previous implementation always reported
// kind='workspace' even when the user was on /diagram/:id.

const DIAGRAM_RE = /^\/diagram\/([^/?#]+)/
const OBJECT_RE = /^\/(?:ws\/[^/]+\/)?objects\/([^/?#]+)/

function parseRoute(pathname: string): {
  diagramId?: string
  objectId?: string
} {
  const dm = DIAGRAM_RE.exec(pathname)
  if (dm) return { diagramId: dm[1] }
  const om = OBJECT_RE.exec(pathname)
  if (om) return { objectId: om[1] }
  return {}
}

// ─── Canvas selection (safe outside diagram page) ───────────────────────────
//
// useCanvasStore is a Zustand store — always safe to call regardless of whether
// a canvas is mounted.  When no diagram is open, selectedNodeId is null.

function useCanvasSelectionMaybe(): { objectId: string } | null {
  const selectedNodeId = useCanvasStore((s) => s.selectedNodeId)
  return selectedNodeId ? { objectId: selectedNodeId } : null
}

// ─── useChatContext ──────────────────────────────────────────────────────────
//
// Derives chat context from the current route + canvas selection.
//
// Supported routes (current + forward-compatible with future /ws/:slug paths):
//
//   /diagram/:diagramId?draft=<id>
//     → kind='diagram', id=diagramId, draft_id?
//     → + canvas selection → kind='object', id=selectedNodeId, parent_diagram_id
//
//   /ws/:workspaceSlug/diagrams/:diagramId?draft=<id>   (future)
//     → same as above
//
//   /ws/:workspaceSlug/objects/:objectId               (future)
//     → kind='object', id=objectId
//
//   /ws/:workspaceSlug                                 (future)
//     → kind='workspace', id from workspaceSlug param (falls back to store)
//
//   / (authenticated overview) or any other page
//     → kind='workspace', id from workspace store
//
//   No workspace in store and no matching params
//     → kind='none'

export function useChatContext(): ChatContext {
  const location = useLocation()
  const [searchParams] = useSearchParams()
  const selection = useCanvasSelectionMaybe()
  const workspaceId = useWorkspaceStore((s) => s.currentWorkspaceId)

  return useMemo<ChatContext>(() => {
    const draftId = searchParams.get('draft') ?? undefined
    const route = parseRoute(location.pathname)

    if (route.diagramId) {
      if (selection?.objectId) {
        return {
          kind: 'object',
          id: selection.objectId,
          parent_diagram_id: route.diagramId,
          draft_id: draftId,
        }
      }
      return { kind: 'diagram', id: route.diagramId, draft_id: draftId }
    }

    if (route.objectId) {
      return { kind: 'object', id: route.objectId }
    }

    const wsId = workspaceId ?? undefined
    if (wsId) {
      return { kind: 'workspace', id: wsId }
    }

    return { kind: 'none' }
  }, [location.pathname, searchParams, selection, workspaceId])
}
