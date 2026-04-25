export function CodeBlock({
  title,
  language,
  children,
}: {
  title?: string
  language?: string
  children: string
}) {
  return (
    <div className="my-3 rounded-lg border border-white/10 bg-black/60 overflow-hidden">
      {title ? (
        <div className="px-3 py-1.5 text-[11px] font-mono uppercase tracking-wider text-neutral-500 border-b border-white/5 flex items-center justify-between">
          <span>{title}</span>
          {language ? <span className="text-neutral-600">{language}</span> : null}
        </div>
      ) : null}
      <pre className="px-3 py-3 text-[12.5px] leading-relaxed font-mono text-neutral-200 overflow-x-auto whitespace-pre">
        {children}
      </pre>
    </div>
  )
}
