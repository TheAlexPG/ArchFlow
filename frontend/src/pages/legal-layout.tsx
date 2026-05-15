import { Link } from 'react-router-dom'

/**
 * Shared chrome for the legal pages (Terms / Privacy). Uses app theme tokens
 * so persisted light mode doesn't render a dark legal shell.
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
    <div className="min-h-screen bg-bg text-text-base relative overflow-hidden">
      {/* Soft ambient glow to match the landing's look-and-feel */}
      <div
        className="pointer-events-none absolute -top-40 -left-40 w-[500px] h-[500px] rounded-full blur-[140px] opacity-20"
        style={{ background: 'radial-gradient(circle, #f97316 0%, transparent 70%)' }}
      />

      <header className="relative z-10 border-b border-border-base bg-panel/80 backdrop-blur">
        <div className="max-w-3xl mx-auto flex items-center justify-between px-6 py-3">
          <Link to="/" className="flex items-center gap-2">
            <img src="/logo.png" alt="" className="w-7 h-7 rounded-lg" />
            <span className="font-semibold text-text-base">ArchFlow</span>
          </Link>
          <Link to="/" className="text-sm text-text-2 hover:text-text-base transition">
            ← Back home
          </Link>
        </div>
      </header>

      <main className="relative z-10 max-w-3xl mx-auto px-6 py-16">
        <h1 className="text-3xl md:text-4xl font-bold tracking-tight text-text-base mb-2">
          {title}
        </h1>
        <div className="text-xs text-text-3 mb-10">
          Last updated: {lastUpdated}
        </div>
        <article
          className="
            space-y-4 text-text-2 leading-relaxed
            [&_h2]:text-xl [&_h2]:font-semibold [&_h2]:text-text-base [&_h2]:mt-10 [&_h2]:mb-3 [&_h2]:tracking-tight
            [&_ul]:list-disc [&_ul]:pl-6 [&_ul]:space-y-1
            [&_code]:bg-white/5 [&_code]:border [&_code]:border-white/10 [&_code]:px-1.5 [&_code]:py-0.5 [&_code]:rounded [&_code]:text-sm [&_code]:text-orange-300
            [&_a]:text-orange-400 [&_a:hover]:text-orange-300 [&_a]:transition
            [&_strong]:text-text-base
          "
        >
          {children}
        </article>
      </main>

      <footer className="relative z-10 border-t border-border-base bg-panel/80 py-6 text-center text-xs text-text-3">
        <div className="flex justify-center gap-4">
          <Link to="/" className="hover:text-text-base transition">Home</Link>
          <Link to="/terms" className="hover:text-text-base transition">Terms</Link>
          <Link to="/privacy" className="hover:text-text-base transition">Privacy</Link>
          <a
            href="https://github.com/TheAlexPG/ArchFlow"
            target="_blank"
            rel="noreferrer"
            className="hover:text-text-base transition"
          >
            GitHub
          </a>
        </div>
      </footer>
    </div>
  )
}
