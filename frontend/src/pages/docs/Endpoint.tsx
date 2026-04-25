type Method = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE' | 'WS'

const METHOD_COLORS: Record<Method, string> = {
  GET: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
  POST: 'bg-blue-500/15 text-blue-300 border-blue-500/30',
  PUT: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
  PATCH: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
  DELETE: 'bg-rose-500/15 text-rose-300 border-rose-500/30',
  WS: 'bg-purple-500/15 text-purple-300 border-purple-500/30',
}

export function Endpoint({
  method,
  path,
  summary,
  auth,
  children,
}: {
  method: Method
  path: string
  summary?: string
  auth?: string
  children?: React.ReactNode
}) {
  return (
    <div className="my-4 rounded-lg border border-white/10 bg-white/[0.02] p-4">
      <div className="flex flex-wrap items-baseline gap-3">
        <span
          className={`inline-flex items-center justify-center px-2 py-0.5 rounded text-[11px] font-mono font-semibold border ${METHOD_COLORS[method]}`}
        >
          {method}
        </span>
        <code className="font-mono text-sm text-neutral-100 break-all">{path}</code>
        {auth ? (
          <span className="ml-auto text-[11px] uppercase tracking-wider text-neutral-500">
            auth: {auth}
          </span>
        ) : null}
      </div>
      {summary ? <p className="mt-2 text-sm text-neutral-400">{summary}</p> : null}
      {children ? <div className="mt-3">{children}</div> : null}
    </div>
  )
}
