import { ViewportPortal } from '@xyflow/react'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import {
  useComments,
  useDeleteComment,
  useUpdateComment,
} from '../../hooks/use-api'
import { useCanvasStore } from '../../stores/canvas-store'
import type { Comment, CommentType } from '../../types/model'

// Shared meta for pin styling. Kept inline (not imported from the sidebar)
// so the canvas version stays independent of the deprecated sidebar module.
export const PIN_META: Record<CommentType, { icon: string; color: string; label: string }> = {
  question: { icon: '❓', color: '#3b82f6', label: 'Question' },
  inaccuracy: { icon: '🚩', color: '#ef4444', label: 'Inaccuracy' },
  idea: { icon: '💡', color: '#eab308', label: 'Idea' },
  note: { icon: '📝', color: '#a3a3a3', label: 'Note' },
}

interface CanvasCommentsProps {
  diagramId: string
}

/**
 * Floating comment pins rendered directly on the canvas at their own flow
 * coordinates (not inside a node). Uses ViewportPortal so the pins pan/zoom
 * with the diagram. Only comments whose target is this diagram AND have
 * position coordinates set are shown here; object-anchored comments don't
 * render as pins.
 */
export function CanvasComments({ diagramId }: CanvasCommentsProps) {
  const { data: comments = [] } = useComments('diagram', diagramId)
  const [openId, setOpenId] = useState<string | null>(null)

  const pins = comments.filter(
    (c) => c.position_x != null && c.position_y != null,
  )

  return (
    <ViewportPortal>
      {pins.map((c) => (
        <CommentPin
          key={c.id}
          comment={c}
          open={openId === c.id}
          onOpen={() => setOpenId(c.id)}
          onClose={() => setOpenId(null)}
        />
      ))}
    </ViewportPortal>
  )
}

function CommentPin({
  comment,
  open,
  onOpen,
  onClose,
}: {
  comment: Comment
  open: boolean
  onOpen: () => void
  onClose: () => void
}) {
  const meta = PIN_META[comment.comment_type]
  const updateComment = useUpdateComment()
  const deleteComment = useDeleteComment()
  const [body, setBody] = useState(comment.body)
  const popoverRef = useRef<HTMLDivElement>(null)

  // Keep the textarea synced if the comment is updated elsewhere.
  useEffect(() => {
    setBody(comment.body)
  }, [comment.body])

  // Auto-open a fresh pin that was just created (body === "") so the user
  // immediately lands in an editor.
  const autoOpenedRef = useRef(false)
  useLayoutEffect(() => {
    if (!autoOpenedRef.current && comment.body === '') {
      autoOpenedRef.current = true
      onOpen()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const handleSave = () => {
    const trimmed = body.trim()
    if (trimmed === comment.body) return
    updateComment.mutate({ id: comment.id, body: trimmed })
  }

  const handleDelete = () => {
    if (!confirm('Delete this comment?')) return
    deleteComment.mutate(comment.id)
    onClose()
  }

  const toggleResolved = () => {
    updateComment.mutate({ id: comment.id, resolved: !comment.resolved })
  }

  return (
    <div
      style={{
        position: 'absolute',
        left: comment.position_x!,
        top: comment.position_y!,
        transform: 'translate(-50%, -100%)',
        pointerEvents: 'auto',
      }}
      className="nodrag nopan"
      onMouseDown={(e) => e.stopPropagation()}
    >
      {/* The pin itself */}
      <button
        onClick={(e) => {
          e.stopPropagation()
          if (open) {
            handleSave()
            onClose()
          } else {
            onOpen()
          }
        }}
        style={{
          width: 30,
          height: 30,
          borderRadius: '50% 50% 50% 0',
          transform: 'rotate(-45deg)',
          background: meta.color,
          border: '2px solid #0a0a0a',
          boxShadow: '0 2px 6px rgba(0,0,0,0.5)',
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          opacity: comment.resolved ? 0.5 : 1,
        }}
        title={`${meta.label}${comment.resolved ? ' (resolved)' : ''}`}
      >
        <span style={{ transform: 'rotate(45deg)', fontSize: 14 }}>{meta.icon}</span>
      </button>

      {/* Body popover */}
      {open && (
        <div
          ref={popoverRef}
          style={{
            position: 'absolute',
            left: '50%',
            top: 'calc(100% + 8px)',
            transform: 'translateX(-50%)',
            width: 260,
            background: '#171717',
            border: `1px solid ${meta.color}`,
            borderRadius: 6,
            boxShadow: '0 8px 24px rgba(0,0,0,0.5)',
            padding: 10,
            zIndex: 50,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
            <span style={{ fontSize: 11, color: meta.color, fontWeight: 600 }}>
              {meta.icon} {meta.label}
            </span>
            <span style={{ flex: 1 }} />
            {comment.resolved && (
              <span style={{ fontSize: 10, color: '#22c55e' }}>✓ Resolved</span>
            )}
            <button
              onClick={onClose}
              style={{ background: 'transparent', border: 'none', color: '#737373', cursor: 'pointer' }}
              title="Close"
            >
              ×
            </button>
          </div>
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            onBlur={handleSave}
            onKeyDown={(e) => {
              if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
                handleSave()
                onClose()
              }
            }}
            autoFocus
            rows={3}
            placeholder="Type your comment…"
            style={{
              width: '100%',
              background: '#262626',
              border: '1px solid #333',
              borderRadius: 4,
              color: '#e5e5e5',
              fontSize: 12,
              padding: '6px 8px',
              resize: 'vertical',
              boxSizing: 'border-box',
              outline: 'none',
            }}
          />
          <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
            <button
              onClick={toggleResolved}
              style={{
                fontSize: 11,
                padding: '2px 8px',
                borderRadius: 4,
                background: 'transparent',
                color: comment.resolved ? '#a3a3a3' : '#22c55e',
                border: '1px solid #333',
                cursor: 'pointer',
              }}
            >
              {comment.resolved ? 'Reopen' : 'Resolve'}
            </button>
            <span style={{ flex: 1 }} />
            <button
              onClick={handleDelete}
              style={{
                fontSize: 11,
                padding: '2px 8px',
                borderRadius: 4,
                background: 'transparent',
                color: '#f87171',
                border: '1px solid #7f1d1d',
                cursor: 'pointer',
              }}
            >
              Delete
            </button>
          </div>
          <div style={{ fontSize: 10, color: '#525252', marginTop: 4 }}>
            {comment.author?.email || 'Anonymous'} ·{' '}
            {new Date(comment.created_at).toLocaleString()}
          </div>
        </div>
      )}
    </div>
  )
}
