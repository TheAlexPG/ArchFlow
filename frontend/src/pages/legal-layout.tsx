import { Link } from 'react-router-dom'

/**
 * Shared chrome for the legal pages (Terms / Privacy). Keeps them visually
 * aligned with the landing page without pulling in the app's dark-themed
 * AppSidebar.
 */
export function LegalLayout({
  title,
  lastUpdated,
  children,
}: {
  title: string
  lastUpdated: string
  children: React.ReactNode
}) {
  return (
    <div className="min-h-screen bg-white text-slate-900">
      <header className="border-b border-slate-200 bg-white">
        <div className="max-w-3xl mx-auto flex items-center justify-between px-6 py-3">
          <Link to="/" className="flex items-center gap-2">
            <img src="/logo.png" alt="" className="w-7 h-7 rounded-lg" />
            <span className="font-semibold text-slate-900">ArchFlow</span>
          </Link>
          <Link to="/" className="text-sm text-slate-600 hover:text-slate-900">
            ← Back home
          </Link>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-6 py-14">
        <h1 className="text-3xl md:text-4xl font-bold tracking-tight mb-2">
          {title}
        </h1>
        <div className="text-xs text-slate-500 mb-10">
          Last updated: {lastUpdated}
        </div>
        <article className="prose-slate prose-a:text-orange-600 prose-a:no-underline hover:prose-a:underline space-y-4 text-slate-700 leading-relaxed [&_h2]:text-xl [&_h2]:font-semibold [&_h2]:text-slate-900 [&_h2]:mt-10 [&_h2]:mb-3 [&_ul]:list-disc [&_ul]:pl-6 [&_ul]:space-y-1 [&_code]:bg-slate-100 [&_code]:px-1.5 [&_code]:py-0.5 [&_code]:rounded [&_code]:text-sm [&_a]:text-orange-600 [&_a:hover]:underline">
          {children}
        </article>
      </main>

      <footer className="border-t border-slate-200 bg-slate-50 py-6 text-center text-xs text-slate-500">
        <div className="flex justify-center gap-4">
          <Link to="/" className="hover:text-slate-700">Home</Link>
          <Link to="/terms" className="hover:text-slate-700">Terms</Link>
          <Link to="/privacy" className="hover:text-slate-700">Privacy</Link>
          <a
            href="https://github.com/TheAlexPG/ArchFlow"
            target="_blank"
            rel="noreferrer"
            className="hover:text-slate-700"
          >
            GitHub
          </a>
        </div>
      </footer>
    </div>
  )
}
