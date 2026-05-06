import { useDeferredValue, type ReactNode } from 'react'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { cn } from '../../../utils/cn'
import { parseArchflowLink } from '../../../lib/archflow-link'
import { ArchflowLink } from './ArchflowLink'

// ─── AssistantText ──────────────────────────────────────────────────────────
//
// Left-aligned bubble that renders streaming assistant text as full markdown
// (GitHub-flavoured: tables, task lists, fenced code, etc.) using
// react-markdown. Custom renderers route ``archflow://`` links into the
// in-app navigator and apply project styling tokens to headings, lists,
// code, tables and blockquotes.
//
// Performance: text changes on every ``token`` SSE event. We wrap the
// visible string in ``useDeferredValue`` so React can yield to higher-
// priority renders (scroll, input) while the latest delta is parsed.

interface AssistantTextProps {
  text: string
}

export function AssistantText({ text }: AssistantTextProps) {
  const deferred = useDeferredValue(text)

  return (
    <div className="flex justify-start" data-testid="assistant-text">
      <div
        className={cn(
          'max-w-[85%] rounded-lg px-3 py-2',
          'bg-surface border border-border-base',
          'text-[13px] text-text-base leading-relaxed break-words',
          'archflow-md',
        )}
      >
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={MARKDOWN_COMPONENTS}>
          {deferred}
        </ReactMarkdown>
      </div>
    </div>
  )
}

// ─── Custom renderers ──────────────────────────────────────────────────────
//
// Style each markdown element with project tokens. The ``archflow-md``
// container class (in index.css) supplies vertical rhythm so we don't
// hand-tune ``mt-`` on every component.

const MARKDOWN_COMPONENTS: Components = {
  a({ href, children, ...props }) {
    if (typeof href === 'string') {
      const archflow = parseArchflowLink(href)
      if (archflow) {
        return (
          <ArchflowLink target={archflow.target} id={archflow.id}>
            {children as ReactNode}
          </ArchflowLink>
        )
      }
    }
    return (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className="text-coral underline underline-offset-2 hover:text-coral-2"
        {...props}
      >
        {children}
      </a>
    )
  },
  // react-markdown's `Components` typing for `code` doesn't expose `inline`
  // directly; cast through `any` so we can pull it off props without fighting
  // the lib's intersected type.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  code({ inline, className, children, ...props }: any) {
    if (inline) {
      return (
        <code
          className="px-1 py-0.5 rounded bg-surface-hi border border-border-base text-[12px] font-mono text-coral-2"
          {...props}
        >
          {children}
        </code>
      )
    }
    return (
      <code className={cn('font-mono text-[12px]', className)} {...props}>
        {children}
      </code>
    )
  },
  pre({ children, ...props }) {
    return (
      <pre
        className="rounded-md bg-surface-hi border border-border-base p-2 overflow-x-auto text-[12px] my-2"
        {...props}
      >
        {children}
      </pre>
    )
  },
  h1({ children, ...props }) {
    return (
      <h1 className="text-[15px] font-semibold mt-3 mb-1" {...props}>
        {children}
      </h1>
    )
  },
  h2({ children, ...props }) {
    return (
      <h2 className="text-[14px] font-semibold mt-3 mb-1" {...props}>
        {children}
      </h2>
    )
  },
  h3({ children, ...props }) {
    return (
      <h3 className="text-[13px] font-semibold mt-2 mb-1" {...props}>
        {children}
      </h3>
    )
  },
  ul({ children, ...props }) {
    return (
      <ul className="list-disc pl-5 my-1 space-y-0.5" {...props}>
        {children}
      </ul>
    )
  },
  ol({ children, ...props }) {
    return (
      <ol className="list-decimal pl-5 my-1 space-y-0.5" {...props}>
        {children}
      </ol>
    )
  },
  li({ children, ...props }) {
    return (
      <li className="leading-snug" {...props}>
        {children}
      </li>
    )
  },
  blockquote({ children, ...props }) {
    return (
      <blockquote
        className="border-l-2 border-coral/40 pl-3 my-2 text-text-2 italic"
        {...props}
      >
        {children}
      </blockquote>
    )
  },
  table({ children, ...props }) {
    return (
      <div className="overflow-x-auto my-2">
        <table className="text-[12px] border-collapse" {...props}>
          {children}
        </table>
      </div>
    )
  },
  th({ children, ...props }) {
    return (
      <th
        className="border border-border-base bg-surface-hi px-2 py-1 text-left font-semibold"
        {...props}
      >
        {children}
      </th>
    )
  },
  td({ children, ...props }) {
    return (
      <td className="border border-border-base px-2 py-1 align-top" {...props}>
        {children}
      </td>
    )
  },
  hr() {
    return <hr className="border-border-base my-3" />
  },
  p({ children, ...props }) {
    return (
      <p className="my-1 first:mt-0 last:mb-0" {...props}>
        {children}
      </p>
    )
  },
  strong({ children, ...props }) {
    return (
      <strong className="font-semibold" {...props}>
        {children}
      </strong>
    )
  },
  em({ children, ...props }) {
    return (
      <em className="italic" {...props}>
        {children}
      </em>
    )
  },
}

