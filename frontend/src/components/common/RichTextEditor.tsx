import { useEditor, EditorContent } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import Placeholder from '@tiptap/extension-placeholder'
import { useEffect } from 'react'
import { cn } from '../../utils/cn'

interface RichTextEditorProps {
  content: string
  onChange: (html: string) => void
  placeholder?: string
}

export function RichTextEditor({ content, onChange, placeholder }: RichTextEditorProps) {
  const editor = useEditor({
    extensions: [
      StarterKit,
      Placeholder.configure({ placeholder: placeholder || 'Add description...' }),
    ],
    content,
    onUpdate: ({ editor }) => {
      onChange(editor.getHTML())
    },
    editorProps: {
      attributes: {
        class: 'rich-text-editor__content',
      },
    },
  })

  // Sync external content changes
  useEffect(() => {
    if (editor && content !== editor.getHTML()) {
      editor.commands.setContent(content, { emitUpdate: false })
    }
  }, [content]) // eslint-disable-line react-hooks/exhaustive-deps

  if (!editor) return null

  return (
    <div className="rich-text-editor">
      {/* Toolbar */}
      <div className="rich-text-editor__toolbar">
        <ToolBtn
          active={editor.isActive('bold')}
          onClick={() => editor.chain().focus().toggleBold().run()}
          label="B"
          style={{ fontWeight: 700 }}
        />
        <ToolBtn
          active={editor.isActive('italic')}
          onClick={() => editor.chain().focus().toggleItalic().run()}
          label="I"
          style={{ fontStyle: 'italic' }}
        />
        <ToolBtn
          active={editor.isActive('bulletList')}
          onClick={() => editor.chain().focus().toggleBulletList().run()}
          label="•"
        />
        <ToolBtn
          active={editor.isActive('codeBlock')}
          onClick={() => editor.chain().focus().toggleCodeBlock().run()}
          label="<>"
        />
      </div>

      {/* Editor */}
      <div className="rich-text-editor__body">
        <EditorContent editor={editor} />
      </div>
    </div>
  )
}

function ToolBtn({
  active,
  onClick,
  label,
  style,
}: {
  active: boolean
  onClick: () => void
  label: string
  style?: React.CSSProperties
}) {
  return (
    <button
      onClick={onClick}
      className={cn('rich-text-editor__tool-button', active && 'rich-text-editor__tool-button--active')}
      style={style}
      type="button"
    >
      {label}
    </button>
  )
}
