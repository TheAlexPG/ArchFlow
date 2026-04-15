import { useEditor, EditorContent } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import Placeholder from '@tiptap/extension-placeholder'
import { useEffect } from 'react'

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
        style:
          'min-height: 60px; outline: none; font-size: 13px; color: #e5e5e5; line-height: 1.5;',
      },
    },
  })

  // Sync external content changes
  useEffect(() => {
    if (editor && content !== editor.getHTML()) {
      editor.commands.setContent(content, false)
    }
  }, [content]) // eslint-disable-line react-hooks/exhaustive-deps

  if (!editor) return null

  return (
    <div style={{ border: '1px solid #333', borderRadius: 6, background: '#171717' }}>
      {/* Toolbar */}
      <div style={{
        display: 'flex', gap: 2, padding: '4px 6px', borderBottom: '1px solid #262626',
      }}>
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
      <div style={{ padding: '8px 10px' }}>
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
      style={{
        background: active ? '#333' : 'transparent',
        border: 'none',
        borderRadius: 4,
        color: active ? '#f5f5f5' : '#737373',
        cursor: 'pointer',
        fontSize: 12,
        padding: '2px 6px',
        minWidth: 24,
        ...style,
      }}
    >
      {label}
    </button>
  )
}
