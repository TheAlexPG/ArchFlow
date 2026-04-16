import { useState } from 'react'
import {
  useComments,
  useCreateComment,
  useDeleteComment,
  useUpdateComment,
} from '../../hooks/use-api'
import type { Comment, CommentTargetType, CommentType } from '../../types/model'

// IcePanel-style typed comments — matching the backend enum.
const TYPES: { value: CommentType; icon: string; label: string; color: string }[] = [
  { value: 'question', icon: '❓', label: 'Question', color: '#3b82f6' },
  { value: 'inaccuracy', icon: '🚩', label: 'Inaccuracy', color: '#ef4444' },
  { value: 'idea', icon: '💡', label: 'Idea', color: '#eab308' },
  { value: 'note', icon: '📝', label: 'Note', color: '#a3a3a3' },
]

const TYPE_META = Object.fromEntries(TYPES.map((t) => [t.value, t])) as Record<
  CommentType,
  (typeof TYPES)[number]
>

interface CommentsSectionProps {
  targetType: CommentTargetType
  targetId: string
}

export function CommentsSection({ targetType, targetId }: CommentsSectionProps) {
  const { data: comments = [] } = useComments(targetType, targetId)
  const createComment = useCreateComment()

  const [draftType, setDraftType] = useState<CommentType>('note')
  const [draft, setDraft] = useState('')

  const handlePost = () => {
    const body = draft.trim()
    if (!body) return
    createComment.mutate(
      { target_type: targetType, target_id: targetId, comment_type: draftType, body },
      { onSuccess: () => setDraft('') },
    )
  }

  const open = comments.filter((c) => !c.resolved)
  const resolved = comments.filter((c) => c.resolved)

  return (
    <div>
      <div className="text-xs text-neutral-500 mb-1.5">
        Comments {comments.length > 0 && `(${comments.length})`}
      </div>

      {/* Composer */}
      <div className="bg-neutral-800 border border-neutral-700 rounded p-2 space-y-1.5">
        <div className="flex gap-1">
          {TYPES.map((t) => (
            <button
              key={t.value}
              onClick={() => setDraftType(t.value)}
              title={t.label}
              className={`flex items-center gap-1 px-1.5 py-0.5 rounded text-[11px] transition-colors ${
                draftType === t.value
                  ? 'bg-neutral-700 text-neutral-100'
                  : 'text-neutral-500 hover:text-neutral-300'
              }`}
            >
              <span>{t.icon}</span>
              {t.label}
            </button>
          ))}
        </div>
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') handlePost()
          }}
          rows={2}
          placeholder={`Add a ${TYPE_META[draftType].label.toLowerCase()}…`}
          className="w-full bg-neutral-900 text-neutral-200 text-xs rounded border border-neutral-700 px-2 py-1.5 resize-none outline-none focus:border-neutral-600"
        />
        <div className="flex items-center justify-between">
          <span className="text-[10px] text-neutral-600">⌘ / Ctrl + Enter to post</span>
          <button
            onClick={handlePost}
            disabled={!draft.trim() || createComment.isPending}
            className="text-[11px] px-2 py-0.5 rounded bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-40 disabled:cursor-not-allowed"
          >
            Post
          </button>
        </div>
      </div>

      {/* Active comments */}
      <div className="mt-3 space-y-2">
        {open.map((c) => (
          <CommentItem key={c.id} comment={c} />
        ))}
        {open.length === 0 && (
          <div className="text-xs text-neutral-600 italic py-2">No comments yet.</div>
        )}
      </div>

      {/* Resolved (collapsed by default) */}
      {resolved.length > 0 && <ResolvedBlock comments={resolved} />}
    </div>
  )
}

function ResolvedBlock({ comments }: { comments: Comment[] }) {
  const [expanded, setExpanded] = useState(false)
  return (
    <div className="mt-3 border-t border-neutral-800 pt-2">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="text-[11px] text-neutral-500 hover:text-neutral-300"
      >
        {expanded ? '▾' : '▸'} Resolved ({comments.length})
      </button>
      {expanded && (
        <div className="mt-2 space-y-2 opacity-70">
          {comments.map((c) => (
            <CommentItem key={c.id} comment={c} />
          ))}
        </div>
      )}
    </div>
  )
}

function CommentItem({ comment }: { comment: Comment }) {
  const updateComment = useUpdateComment()
  const deleteComment = useDeleteComment()
  const meta = TYPE_META[comment.comment_type]
  const [editing, setEditing] = useState(false)
  const [body, setBody] = useState(comment.body)

  const when = timeAgo(new Date(comment.created_at))

  const handleSaveEdit = () => {
    const next = body.trim()
    if (!next || next === comment.body) {
      setEditing(false)
      setBody(comment.body)
      return
    }
    updateComment.mutate(
      { id: comment.id, body: next },
      { onSuccess: () => setEditing(false) },
    )
  }

  const handleDelete = () => {
    if (!confirm('Delete this comment?')) return
    deleteComment.mutate(comment.id)
  }

  const toggleResolved = () => {
    updateComment.mutate({ id: comment.id, resolved: !comment.resolved })
  }

  return (
    <div
      className="rounded border-l-2 pl-2 py-1"
      style={{ borderColor: meta.color }}
    >
      <div className="flex items-center gap-1.5 mb-0.5">
        <span>{meta.icon}</span>
        <span className="text-[11px] text-neutral-400">
          {comment.author?.email || 'Anonymous'}
        </span>
        <span className="text-[10px] text-neutral-600">·</span>
        <span className="text-[10px] text-neutral-600">{when}</span>
        {comment.resolved && (
          <span className="text-[10px] text-green-500 ml-auto">✓ Resolved</span>
        )}
      </div>
      {editing ? (
        <div className="space-y-1">
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            rows={2}
            autoFocus
            className="w-full bg-neutral-900 text-neutral-200 text-xs rounded border border-neutral-700 px-2 py-1 resize-none outline-none focus:border-neutral-600"
          />
          <div className="flex gap-1">
            <button
              onClick={handleSaveEdit}
              className="text-[10px] px-2 py-0.5 rounded bg-blue-600 hover:bg-blue-500 text-white"
            >
              Save
            </button>
            <button
              onClick={() => {
                setEditing(false)
                setBody(comment.body)
              }}
              className="text-[10px] px-2 py-0.5 rounded text-neutral-400 hover:text-neutral-200"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <>
          <div className="text-xs text-neutral-200 whitespace-pre-wrap break-words">
            {comment.body}
          </div>
          <div className="flex gap-2 mt-0.5 opacity-0 group-hover:opacity-100 transition-opacity"
               style={{ opacity: 1 }}>
            <button
              onClick={toggleResolved}
              className="text-[10px] text-neutral-500 hover:text-green-400"
            >
              {comment.resolved ? 'Reopen' : 'Resolve'}
            </button>
            <button
              onClick={() => setEditing(true)}
              className="text-[10px] text-neutral-500 hover:text-neutral-300"
            >
              Edit
            </button>
            <button
              onClick={handleDelete}
              className="text-[10px] text-neutral-500 hover:text-red-400"
            >
              Delete
            </button>
          </div>
        </>
      )}
    </div>
  )
}

function timeAgo(date: Date): string {
  const seconds = Math.floor((Date.now() - date.getTime()) / 1000)
  if (seconds < 60) return 'just now'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days}d ago`
  return date.toLocaleDateString()
}
