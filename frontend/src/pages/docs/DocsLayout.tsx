import { Link } from 'react-router-dom'

export interface TocEntry {
  id: string
  label: string
}

export function DocsLayout({
  toc,
  children,
}: {
  toc: TocEntry[]
  children: React.ReactNode
}) {
  return (
    <div className="min-h-screen bg-[#0a0a0f] text-neutral-200 relative overflow-hidden">
      <div
        className="pointer-events-none absolute -top-40 -left-40 w-[500px] h-[500px] rounded-full blur-[140px] opacity-20"
        style={{ background: 'radial-gradient(circle, #f97316 0%, transparent 70%)' }}
      />
      <header className="relative z-10 border-b border-white/5 bg-[#0a0a0f]/80 backdrop-blur">
        <div className="max-w-6xl mx-auto flex items-center justify-between px-6 py-3">
          <Link to="/" className="flex items-center gap-2">
            <img src="/logo.png" alt="" className="w-7 h-7 rounded-lg" />
            <span className="font-semibold text-neutral-100">ArchFlow</span>
          </Link>
          <div className="flex items-center gap-4 text-sm">
            <a
              href="https://github.com/TheAlexPG/ArchFlow"
              target="_blank"
              rel="noreferrer"
              className="text-neutral-400 hover:text-neutral-100 transition"
            >
              GitHub
            </a>
            <Link to="/" className="text-neutral-400 hover:text-neutral-100 transition">
              ← Back home
            </Link>
          </div>
        </div>
      </header>

      <main className="relative z-10 max-w-6xl mx-auto px-6 py-12 lg:grid lg:grid-cols-[220px_1fr] lg:gap-10">
        <aside className="hidden lg:block">
          <nav className="sticky top-8 text-sm">
            <div className="text-[11px] font-semibold uppercase tracking-wider text-neutral-500 mb-3">
              On this page
            </div>
            <ul className="space-y-1.5">
              {toc.map((entry) => (
                <li key={entry.id}>
                  <a
                    href={`#${entry.id}`}
                    className="block py-1 text-neutral-400 hover:text-orange-400 transition"
                  >
                    {entry.label}
                  </a>
                </li>
              ))}
            </ul>
          </nav>
        </aside>
        <article
          className="
            min-w-0 space-y-16 text-neutral-300 leading-relaxed
            [&_h1]:text-3xl [&_h1]:md:text-4xl [&_h1]:font-bold [&_h1]:text-neutral-100 [&_h1]:tracking-tight [&_h1]:mb-3
            [&_h2]:text-2xl [&_h2]:font-semibold [&_h2]:text-neutral-100 [&_h2]:tracking-tight [&_h2]:mt-2 [&_h2]:mb-3 [&_h2]:scroll-mt-24
            [&_h3]:text-lg [&_h3]:font-semibold [&_h3]:text-neutral-100 [&_h3]:mt-6 [&_h3]:mb-2
            [&_p]:my-3
            [&_ul]:list-disc [&_ul]:pl-6 [&_ul]:my-3 [&_ul]:space-y-1
            [&_code]:bg-white/5 [&_code]:border [&_code]:border-white/10 [&_code]:px-1.5 [&_code]:py-0.5 [&_code]:rounded [&_code]:text-[0.85em] [&_code]:text-orange-300 [&_code]:font-mono
            [&_a]:text-orange-400 [&_a:hover]:text-orange-300 [&_a]:transition
            [&_strong]:text-neutral-100
            [&_table]:w-full [&_table]:text-sm [&_table]:my-4
            [&_th]:text-left [&_th]:py-2 [&_th]:px-3 [&_th]:font-semibold [&_th]:text-neutral-200 [&_th]:border-b [&_th]:border-white/10
            [&_td]:py-2 [&_td]:px-3 [&_td]:border-b [&_td]:border-white/5 [&_td]:align-top
          "
        >
          {children}
        </article>
      </main>

      <footer className="relative z-10 border-t border-white/5 bg-black/40 py-6 text-center text-xs text-neutral-500 mt-16">
        <div className="flex justify-center gap-4">
          <Link to="/" className="hover:text-neutral-300 transition">Home</Link>
          <Link to="/terms" className="hover:text-neutral-300 transition">Terms</Link>
          <Link to="/privacy" className="hover:text-neutral-300 transition">Privacy</Link>
          <a
            href="https://github.com/TheAlexPG/ArchFlow"
            target="_blank"
            rel="noreferrer"
            className="hover:text-neutral-300 transition"
          >
            GitHub
          </a>
        </div>
      </footer>
    </div>
  )
}
