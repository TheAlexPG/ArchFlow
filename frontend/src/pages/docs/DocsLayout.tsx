import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'

export interface TocEntry {
  id: string
  label: string
}

// Topmost section currently in the upper-middle band of the viewport.
// Drives the highlighted state in the mobile pill nav and desktop sidebar.
function useActiveSection(toc: TocEntry[]) {
  const [activeId, setActiveId] = useState<string | null>(toc[0]?.id ?? null)
  useEffect(() => {
    const elements = toc
      .map((e) => document.getElementById(e.id))
      .filter((el): el is HTMLElement => el !== null)
    if (elements.length === 0) return

    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)
        if (visible[0]) setActiveId(visible[0].target.id)
      },
      { rootMargin: '-30% 0px -60% 0px', threshold: 0 },
    )
    elements.forEach((el) => observer.observe(el))
    return () => observer.disconnect()
  }, [toc])
  return activeId
}

export function DocsLayout({
  toc,
  children,
}: {
  toc: TocEntry[]
  children: React.ReactNode
}) {
  const activeId = useActiveSection(toc)
  const pillRefs = useRef<Record<string, HTMLAnchorElement | null>>({})

  // Keep the active pill visible inside the horizontally-scrolling mobile nav.
  useEffect(() => {
    if (!activeId) return
    const el = pillRefs.current[activeId]
    if (el) el.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' })
  }, [activeId])

  return (
    <div className="min-h-screen bg-[#0a0a0f] text-neutral-200 relative">
      {/* Decorative gradient blob — clipped by its own container so the page
          wrapper doesn't need overflow:hidden, which can interfere with
          anchor-jump scroll on some mobile browsers. */}
      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        <div
          className="absolute -top-40 -left-40 w-[500px] h-[500px] rounded-full blur-[140px] opacity-20"
          style={{ background: 'radial-gradient(circle, #f97316 0%, transparent 70%)' }}
        />
      </div>

      <header className="sticky top-0 z-30 border-b border-white/5 bg-[#0a0a0f]/85 backdrop-blur">
        <div className="max-w-6xl mx-auto flex items-center justify-between px-4 lg:px-6 py-3">
          <Link to="/" className="flex items-center gap-2">
            <img src="/logo.png" alt="" className="w-7 h-7 rounded-lg" />
            <span className="font-semibold text-neutral-100">ArchFlow</span>
          </Link>
          <div className="flex items-center gap-3 sm:gap-4 text-sm">
            <a
              href="https://github.com/TheAlexPG/ArchFlow"
              target="_blank"
              rel="noreferrer"
              className="text-neutral-400 hover:text-neutral-100 transition"
            >
              GitHub
            </a>
            <Link
              to="/"
              className="text-neutral-400 hover:text-neutral-100 transition"
              aria-label="Back home"
            >
              <span className="hidden sm:inline">← Back home</span>
              <span className="sm:hidden text-base leading-none">←</span>
            </Link>
          </div>
        </div>

        {/* Mobile section nav — horizontal pill bar inside the sticky header
            so users can jump between sections at any scroll depth. Hidden on
            lg+ where the sidebar takes over. */}
        <nav
          aria-label="Sections"
          className="lg:hidden border-t border-white/5 bg-[#0a0a0f]/85"
        >
          <ul className="max-w-6xl mx-auto flex gap-2 overflow-x-auto px-4 py-2 text-xs [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
            {toc.map((entry) => {
              const active = entry.id === activeId
              return (
                <li key={entry.id} className="shrink-0">
                  <a
                    ref={(el) => {
                      pillRefs.current[entry.id] = el
                    }}
                    href={`#${entry.id}`}
                    aria-current={active ? 'location' : undefined}
                    className={
                      'inline-block px-3 py-1.5 rounded-full border transition whitespace-nowrap ' +
                      (active
                        ? 'border-orange-400/60 bg-orange-400/10 text-orange-200'
                        : 'border-white/10 bg-white/[0.03] text-neutral-300 hover:text-orange-300 hover:border-orange-400/40')
                    }
                  >
                    {entry.label}
                  </a>
                </li>
              )
            })}
          </ul>
        </nav>
      </header>

      <main className="relative z-10 max-w-6xl mx-auto px-4 lg:px-6 py-8 lg:py-12 lg:grid lg:grid-cols-[220px_1fr] lg:gap-10">
        <aside className="hidden lg:block">
          <nav className="sticky top-20 text-sm" aria-label="On this page">
            <div className="text-[11px] font-semibold uppercase tracking-wider text-neutral-500 mb-3">
              On this page
            </div>
            <ul className="space-y-1.5">
              {toc.map((entry) => {
                const active = entry.id === activeId
                return (
                  <li key={entry.id}>
                    <a
                      href={`#${entry.id}`}
                      aria-current={active ? 'location' : undefined}
                      className={
                        'block py-1 pl-3 -ml-[2px] border-l-2 transition ' +
                        (active
                          ? 'border-orange-400 text-orange-300'
                          : 'border-transparent text-neutral-400 hover:text-orange-400 hover:border-white/20')
                      }
                    >
                      {entry.label}
                    </a>
                  </li>
                )
              })}
            </ul>
          </nav>
        </aside>
        <article
          className="
            min-w-0 space-y-16 text-neutral-300 leading-relaxed
            [&_h1]:text-3xl [&_h1]:md:text-4xl [&_h1]:font-bold [&_h1]:text-neutral-100 [&_h1]:tracking-tight [&_h1]:mb-3
            [&_h2]:text-2xl [&_h2]:font-semibold [&_h2]:text-neutral-100 [&_h2]:tracking-tight [&_h2]:mt-2 [&_h2]:mb-3 [&_h2]:scroll-mt-32 [&_h2]:lg:scroll-mt-24
            [&_h3]:text-lg [&_h3]:font-semibold [&_h3]:text-neutral-100 [&_h3]:mt-6 [&_h3]:mb-2
            [&_section]:scroll-mt-32 [&_section]:lg:scroll-mt-24
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

      <footer className="relative z-10 border-t border-white/5 bg-black/40 py-6 text-xs text-neutral-500 mt-16">
        <div className="flex flex-wrap justify-center gap-x-4 gap-y-2 px-4">
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
