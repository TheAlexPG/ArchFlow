import { Fragment, useDeferredValue, useMemo, type ReactNode } from 'react'
import { cn } from '../../../utils/cn'
import { parseArchflowLink, type ArchflowLinkTarget } from '../../../lib/archflow-link'
import { ArchflowLink } from './ArchflowLink'

// ─── AssistantText ──────────────────────────────────────────────────────────
//
// Left-aligned bubble rendering streaming assistant text. We hand-roll a
// minimal markdown subset — bold, italic, inline code, links, and the
// archflow:// link convention — to avoid pulling react-markdown into the
// bundle for Phase 1.
//
// Performance: text changes on every `token` SSE event. We wrap the visible
// string in `useDeferredValue` so React can yield to higher-priority
// renders (scroll, input) while the latest delta is parsed.

interface AssistantTextProps {
  text: string
}

export function AssistantText({ text }: AssistantTextProps) {
  const deferred = useDeferredValue(text)
  const blocks = useMemo(() => parseBlocks(deferred), [deferred])

  return (
    <div className="flex justify-start" data-testid="assistant-text">
      <div
        className={cn(
          'max-w-[85%] rounded-lg px-3 py-2',
          'bg-surface border border-border-base',
          'text-[13px] text-text-base leading-relaxed break-words',
        )}
      >
        {blocks.map((block, i) => (
          <Fragment key={i}>{block}</Fragment>
        ))}
      </div>
    </div>
  )
}

// ─── Block-level parser ────────────────────────────────────────────────────
//
// Split on blank lines (\n\n) — each chunk becomes a <p>. Single newlines
// within a chunk are preserved as <br/> for usable streamed output.

function parseBlocks(text: string): ReactNode[] {
  if (!text) return []
  const paragraphs = text.split(/\n{2,}/)
  return paragraphs.map((para, i) => (
    <p key={i} className={i > 0 ? 'mt-2' : undefined}>
      {parseInline(para)}
    </p>
  ))
}

// ─── Inline parser ─────────────────────────────────────────────────────────
//
// Tokenizes inline syntax into spans. Order matters: we match the longest
// constructs first (code, then links, then emphasis) so e.g. `*foo*` inside
// a code span does not get italicized.
//
// Patterns:
//   `code`              → <code>
//   [label](url)        → <a> or <ArchflowLink>
//   archflow://x/{id}   → <ArchflowLink> (bare URI form, valid UUID only)
//   **bold**            → <strong>
//   *italic*            → <em>
//   plain newlines      → <br/>

interface InlineToken {
  type: 'text' | 'code' | 'link' | 'archflow' | 'bold' | 'italic' | 'br'
  value: string
  href?: string
  archflow?: { target: ArchflowLinkTarget; id: string }
}

const INLINE_PATTERNS: Array<{
  type: InlineToken['type']
  re: RegExp
  build?: (m: RegExpExecArray) => InlineToken | null
}> = [
  // Inline code first — wins over everything inside the backticks.
  {
    type: 'code',
    re: /`([^`\n]+)`/,
    build: (m) => ({ type: 'code', value: m[1] }),
  },
  // Markdown link `[label](url)`. If the URL is archflow://, route to <ArchflowLink>.
  {
    type: 'link',
    re: /\[([^\]]+)\]\(([^)\s]+)\)/,
    build: (m) => {
      const archflow = parseArchflowLink(m[2])
      if (archflow) {
        return {
          type: 'archflow',
          value: m[1],
          archflow: { target: archflow.target, id: archflow.id },
        }
      }
      return { type: 'link', value: m[1], href: m[2] }
    },
  },
  // Bare archflow:// URI (must be a real UUID — see archflow-link.ts INLINE_RE).
  {
    type: 'archflow',
    re: /archflow:\/\/(object|diagram|connection)\/[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}/,
    build: (m) => {
      const parsed = parseArchflowLink(m[0])
      if (!parsed) return null
      return {
        type: 'archflow',
        value: m[0],
        archflow: { target: parsed.target, id: parsed.id },
      }
    },
  },
  // Bold (must precede italic — both use *).
  {
    type: 'bold',
    re: /\*\*([^*\n]+)\*\*/,
    build: (m) => ({ type: 'bold', value: m[1] }),
  },
  // Italic.
  {
    type: 'italic',
    re: /\*([^*\n]+)\*/,
    build: (m) => ({ type: 'italic', value: m[1] }),
  },
]

function tokenizeInline(text: string): InlineToken[] {
  const tokens: InlineToken[] = []
  let remaining = text
  while (remaining.length > 0) {
    // Find the earliest match across all patterns.
    let bestIdx = -1
    let bestLen = 0
    let bestToken: InlineToken | null = null

    for (const pattern of INLINE_PATTERNS) {
      const m = pattern.re.exec(remaining)
      if (!m) continue
      const built = pattern.build ? pattern.build(m) : { type: pattern.type, value: m[0] }
      if (!built) continue
      if (bestIdx === -1 || m.index < bestIdx) {
        bestIdx = m.index
        bestLen = m[0].length
        bestToken = built
      }
    }

    if (bestIdx === -1 || bestToken == null) {
      // No more inline patterns — flush the rest as text (with br for newlines).
      pushTextWithBreaks(tokens, remaining)
      break
    }

    if (bestIdx > 0) {
      pushTextWithBreaks(tokens, remaining.slice(0, bestIdx))
    }
    tokens.push(bestToken)
    remaining = remaining.slice(bestIdx + bestLen)
  }
  return tokens
}

function pushTextWithBreaks(out: InlineToken[], text: string): void {
  if (!text) return
  const lines = text.split('\n')
  lines.forEach((line, i) => {
    if (i > 0) out.push({ type: 'br', value: '' })
    if (line) out.push({ type: 'text', value: line })
  })
}

function parseInline(text: string): ReactNode[] {
  const tokens = tokenizeInline(text)
  return tokens.map((t, i) => renderToken(t, i))
}

function renderToken(t: InlineToken, key: number): ReactNode {
  switch (t.type) {
    case 'text':
      return <span key={key}>{t.value}</span>
    case 'br':
      return <br key={key} />
    case 'code':
      return (
        <code
          key={key}
          className="px-1 py-0.5 rounded bg-surface-hi border border-border-base text-[12px] font-mono text-coral-2"
        >
          {t.value}
        </code>
      )
    case 'bold':
      return (
        <strong key={key} className="font-semibold">
          {t.value}
        </strong>
      )
    case 'italic':
      return (
        <em key={key} className="italic">
          {t.value}
        </em>
      )
    case 'link':
      return (
        <a
          key={key}
          href={t.href}
          target="_blank"
          rel="noopener noreferrer"
          className="text-coral underline underline-offset-2 hover:text-coral-2"
        >
          {t.value}
        </a>
      )
    case 'archflow': {
      if (!t.archflow) return null
      // For bare URIs, keep the original URI as the visible label (so users
      // can copy it). For [label](archflow://...) syntax, use the label.
      const isBareUri = t.value.startsWith('archflow://')
      const label = isBareUri ? `${t.archflow.target}/${shortenId(t.archflow.id)}` : t.value
      return (
        <ArchflowLink key={key} target={t.archflow.target} id={t.archflow.id}>
          {label}
        </ArchflowLink>
      )
    }
  }
}

function shortenId(id: string): string {
  // Show first 8 chars of a UUID for readability — full id stays in the URL.
  return id.length > 8 ? id.slice(0, 8) : id
}
