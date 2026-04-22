import { Link } from 'react-router-dom'

const GITHUB_URL = 'https://github.com/TheAlexPG/ArchFlow'

export function LandingPage() {
  return (
    <div className="min-h-screen bg-[#0a0a0f] text-neutral-200 antialiased relative overflow-hidden">
      <AmbientBackdrop />
      <Nav />
      <Hero />
      <WhyArchFlow />
      <Features />
      <Comparison />
      <HowItWorks />
      <OpenSource />
      <FinalCTA />
      <Footer />
    </div>
  )
}

function AmbientBackdrop() {
  // Two soft blurred blobs + a subtle grid — gives the page a premium depth
  // without going heavy on images or animation.
  return (
    <div className="pointer-events-none absolute inset-0 z-0 overflow-hidden">
      <div
        className="absolute -top-40 -left-40 w-[500px] h-[500px] rounded-full blur-[120px] opacity-30"
        style={{ background: 'radial-gradient(circle, #f97316 0%, transparent 70%)' }}
      />
      <div
        className="absolute top-[40%] -right-40 w-[520px] h-[520px] rounded-full blur-[140px] opacity-25"
        style={{ background: 'radial-gradient(circle, #a855f7 0%, transparent 70%)' }}
      />
      <div
        className="absolute inset-0 opacity-[0.035]"
        style={{
          backgroundImage:
            'linear-gradient(#fff 1px, transparent 1px), linear-gradient(90deg, #fff 1px, transparent 1px)',
          backgroundSize: '48px 48px',
        }}
      />
    </div>
  )
}

function Nav() {
  return (
    <header className="sticky top-0 z-30 border-b border-white/5 bg-[#0a0a0f]/80 backdrop-blur">
      <div className="max-w-6xl mx-auto flex items-center justify-between px-6 py-3">
        <Link to="/" className="flex items-center gap-2">
          <img src="/logo.png" alt="" className="w-8 h-8 rounded-lg" />
          <span className="font-semibold text-neutral-100">ArchFlow</span>
          <span className="text-[10px] font-medium text-orange-400 bg-orange-500/10 border border-orange-500/20 rounded px-1.5 py-0.5">
            beta
          </span>
        </Link>
        <div className="flex items-center gap-5 text-sm">
          <a
            href={GITHUB_URL}
            target="_blank"
            rel="noreferrer"
            className="text-neutral-400 hover:text-neutral-100 transition"
          >
            GitHub
          </a>
          <Link to="/login" className="text-neutral-400 hover:text-neutral-100 transition">
            Sign in
          </Link>
          <Link
            to="/login"
            className="bg-white text-neutral-900 hover:bg-neutral-200 rounded-lg px-3 py-1.5 font-medium transition"
          >
            Get started
          </Link>
        </div>
      </div>
    </header>
  )
}

function Hero() {
  return (
    <section className="relative z-10">
      <div className="max-w-4xl mx-auto px-6 py-24 md:py-32 text-center">
        <img
          src="/logo.png"
          alt="ArchFlow"
          className="w-20 h-20 mx-auto mb-8 rounded-2xl shadow-[0_20px_60px_-10px_rgba(249,115,22,0.4)]"
        />
        <div className="inline-flex items-center gap-2 bg-white/5 border border-white/10 text-neutral-300 text-xs font-medium px-3 py-1.5 rounded-full mb-6">
          <span className="w-1.5 h-1.5 rounded-full bg-orange-500 animate-pulse" />
          Self-hosted · AGPL-3.0 open source
        </div>
        <h1 className="text-4xl md:text-6xl font-bold tracking-tight leading-[1.1]">
          <span className="text-neutral-100">Architecture diagrams</span>
          <br />
          <span className="bg-gradient-to-r from-orange-400 via-orange-300 to-fuchsia-400 bg-clip-text text-transparent">
            that stay in sync with reality.
          </span>
        </h1>
        <p className="mt-6 text-lg text-neutral-400 max-w-2xl mx-auto leading-relaxed">
          Most architecture tools give you pretty pictures that rot the moment
          someone renames a service. ArchFlow treats your architecture as a
          <span className="text-neutral-200"> typed, versioned, collaborative model</span> —
          drill from landscape to component, branch like git, review like code.
        </p>
        <div className="mt-9 flex flex-wrap gap-3 justify-center">
          <Link
            to="/login"
            className="group relative bg-gradient-to-r from-orange-500 to-orange-600 hover:from-orange-400 hover:to-orange-500 text-white rounded-lg px-6 py-3 text-sm font-semibold shadow-[0_10px_30px_-10px_rgba(249,115,22,0.6)] transition"
          >
            Sign in to get started
          </Link>
          <a
            href={GITHUB_URL}
            target="_blank"
            rel="noreferrer"
            className="bg-white/5 border border-white/10 hover:bg-white/10 hover:border-white/20 text-neutral-100 rounded-lg px-6 py-3 text-sm font-semibold transition backdrop-blur"
          >
            Star on GitHub ★
          </a>
        </div>
        <p className="mt-5 text-xs text-neutral-500">
          Free forever · Self-host with one{' '}
          <code className="text-orange-400 bg-orange-500/10 px-1.5 py-0.5 rounded">
            docker compose
          </code>{' '}
          command.
        </p>
      </div>
    </section>
  )
}

function WhyArchFlow() {
  const pillars = [
    {
      headline: 'Not just boxes. A typed model.',
      body:
        'Every object has a type, status, technology stack, owning team, and lifecycle. Rename a service once — every diagram updates. Your architecture becomes searchable, filterable, queryable.',
    },
    {
      headline: 'Not just drawings. A review workflow.',
      body:
        'Fork any diagram into a draft. Experiment without blowing up production docs. Diff your changes against live, resolve conflicts, merge when ready. Git-style, but for architecture.',
    },
    {
      headline: 'Not another SaaS. Your server, your data.',
      body:
        'AGPL-3.0, self-hostable in one Docker Compose command. No seat limits. No data-exfil. No "your team plan expired" — your architecture stays yours forever.',
    },
  ]
  return (
    <section className="relative z-10 border-t border-white/5">
      <div className="max-w-6xl mx-auto px-6 py-24">
        <SectionHead
          eyebrow="Why ArchFlow"
          title="Built for architecture that evolves"
          body="PowerPoint and Miro were never designed to stay accurate. ArchFlow was."
        />
        <div className="mt-14 grid grid-cols-1 md:grid-cols-3 gap-6">
          {pillars.map((p) => (
            <div
              key={p.headline}
              className="relative bg-white/[0.02] border border-white/10 rounded-xl p-6 hover:border-orange-500/30 transition"
            >
              <div className="text-lg font-semibold text-neutral-100 mb-3 leading-snug">
                {p.headline}
              </div>
              <p className="text-sm text-neutral-400 leading-relaxed">{p.body}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

function Comparison() {
  const rows = [
    {
      tool: 'Miro · FigJam',
      gap: 'Pretty sticky notes. No data model, no drill-through, no review flow.',
    },
    {
      tool: 'Lucidchart · draw.io',
      gap: 'Nicer shapes — still free-floating boxes. Rename a service in one diagram, forget it in six others.',
    },
    {
      tool: 'Structurizr',
      gap: 'C4-native, but code-only DSL. Non-engineers locked out of the model.',
    },
    {
      tool: 'IcePanel',
      gap: 'Closest peer. Paid SaaS, your data on their servers. ArchFlow is AGPL and runs on your hardware.',
    },
  ]
  return (
    <section className="relative z-10 border-t border-white/5">
      <div className="max-w-5xl mx-auto px-6 py-20">
        <SectionHead
          eyebrow="Vs the alternatives"
          title="You've tried the others."
          body="Here's where they stop and ArchFlow starts."
        />
        <div className="mt-12 divide-y divide-white/5 bg-white/[0.02] border border-white/10 rounded-xl overflow-hidden">
          {rows.map((r) => (
            <div
              key={r.tool}
              className="flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-6 px-5 py-4"
            >
              <div className="sm:w-48 shrink-0 font-semibold text-neutral-100 text-sm">
                {r.tool}
              </div>
              <div className="text-sm text-neutral-400 leading-relaxed">{r.gap}</div>
            </div>
          ))}
          <div className="flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-6 px-5 py-5 bg-gradient-to-r from-orange-500/10 to-fuchsia-500/10">
            <div className="sm:w-48 shrink-0 font-semibold text-orange-300 text-sm flex items-center gap-2">
              <img src="/logo.png" alt="" className="w-5 h-5 rounded" />
              ArchFlow
            </div>
            <div className="text-sm text-neutral-200 leading-relaxed">
              Typed model · C4 drill-through · drafts &amp; review · realtime
              collab · self-hostable · AGPL open source.
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}

function Features() {
  const items = [
    {
      title: 'C4 drill-through',
      body:
        'The same "Payments" system on L1 is the same entity as its Container diagram on L2 and its Components on L3. Rename it once — it updates everywhere, on every zoom.',
      icon: '▦',
    },
    {
      title: 'Real-time collaboration',
      body:
        'Live cursors, presence roster, selection sync, optimistic drag & resize. Your teammate drags a node; you see it move in ~one tick. No refresh, no "who moved what".',
      icon: '⚡',
    },
    {
      title: 'Drafts &amp; reviews',
      body:
        'Architecture deserves the same review workflow as code. Fork a diagram, change it, diff it, resolve conflicts, merge. Reviewers see exactly what moved.',
      icon: '⤴',
    },
    {
      title: 'Packs, pins &amp; search',
      body:
        'Group diagrams into Packs (folders, but reorderable). Pin the important ones to Overview. Cmd+K search across every object, diagram, and description in your workspace.',
      icon: '✦',
    },
    {
      title: 'Teams + per-diagram ACL',
      body:
        'Workspaces with roles (owner / admin / editor / viewer). Grant a specific team read or edit on a specific diagram. Pending-approval invites so admins stay in control.',
      icon: '⧉',
    },
    {
      title: 'API, webhooks, AI insights',
      body:
        'OpenAPI spec + generated TypeScript client. API keys next to JWT. Webhooks for every object/diagram event. Optional Claude-powered insights on any object.',
      icon: '⟷',
    },
    {
      title: 'Versions &amp; history',
      body:
        'Every change logged. Snapshot a diagram as a named version. Revert any diagram, object, or connection to any prior state with one click.',
      icon: '◷',
    },
    {
      title: 'Comments on canvas',
      body:
        'Drop a question pin, an inaccuracy flag, an idea note, or a plain comment directly on the diagram. Threaded replies. Resolved comments stay as history.',
      icon: '❝',
    },
    {
      title: 'AGPL, self-hostable',
      body:
        'One Docker Compose command and the full stack runs on your Hetzner / AWS / laptop. Helm chart included. Your data never leaves your hardware. No vendor lock-in, ever.',
      icon: '⌂',
    },
  ]
  return (
    <section className="relative z-10">
      <div className="max-w-6xl mx-auto px-6 py-24">
        <SectionHead
          eyebrow="Features"
          title="Everything you need to model software"
          body="Built to replace PowerPoint-for-architecture with something that stays in sync with how the system actually works."
        />
        <div className="mt-14 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {items.map((f) => (
            <div
              key={f.title}
              className="group relative bg-white/[0.02] border border-white/10 rounded-xl p-6 hover:border-orange-500/30 hover:bg-white/[0.04] transition"
            >
              <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-orange-500/20 to-fuchsia-500/10 border border-orange-500/20 text-orange-300 flex items-center justify-center text-lg mb-4">
                {f.icon}
              </div>
              <div className="font-semibold text-neutral-100 mb-1.5">{f.title}</div>
              <div className="text-sm text-neutral-400 leading-relaxed">{f.body}</div>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

function HowItWorks() {
  const steps = [
    {
      n: '01',
      title: 'Start with a System Landscape',
      body:
        'Drop systems, actors, and external systems. Connect them. This is the big picture stakeholders read first.',
    },
    {
      n: '02',
      title: 'Drill into Containers',
      body:
        'Open a system, fork its Container diagram. Model apps, stores, and queues that live inside. Hierarchy tracked automatically.',
    },
    {
      n: '03',
      title: 'Zoom into Components',
      body:
        'Pick any container and expand its internals. Objects reused across levels keep their identity — edit once, it lands everywhere.',
    },
  ]
  return (
    <section className="relative z-10 border-t border-white/5">
      <div className="max-w-6xl mx-auto px-6 py-24">
        <SectionHead
          eyebrow="How it works"
          title="The C4 model, but collaborative"
          body="Three zoom levels, one typed model, zero duplication."
        />
        <div className="mt-16 grid grid-cols-1 md:grid-cols-3 gap-8">
          {steps.map((s) => (
            <div key={s.n}>
              <div className="text-6xl font-bold bg-gradient-to-br from-orange-400/60 to-fuchsia-400/20 bg-clip-text text-transparent mb-3">
                {s.n}
              </div>
              <div className="font-semibold text-neutral-100 mb-2 text-lg">
                {s.title}
              </div>
              <div className="text-sm text-neutral-400 leading-relaxed">{s.body}</div>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

function OpenSource() {
  return (
    <section className="relative z-10 border-t border-white/5">
      <div className="max-w-6xl mx-auto px-6 py-24 grid grid-cols-1 md:grid-cols-2 gap-12 items-center">
        <div>
          <div className="text-xs uppercase tracking-widest text-orange-400 font-semibold mb-3">
            Open source
          </div>
          <h2 className="text-3xl md:text-4xl font-bold mb-5 text-neutral-100 tracking-tight">
            Your architecture. Your hardware. Your rules.
          </h2>
          <p className="text-neutral-400 leading-relaxed">
            ArchFlow is released under AGPL-3.0. Clone the repo, run{' '}
            <code className="text-orange-400 bg-orange-500/10 px-1.5 py-0.5 rounded text-sm">
              make setup
            </code>
            , and you have the full platform on your laptop in under a minute.
            Ship to your own Hetzner / AWS / bare-metal box with one Docker
            Compose file.
          </p>
          <div className="mt-7 flex gap-3 flex-wrap">
            <a
              href={GITHUB_URL}
              target="_blank"
              rel="noreferrer"
              className="bg-white text-neutral-900 hover:bg-neutral-200 rounded-lg px-5 py-2.5 text-sm font-semibold transition"
            >
              View on GitHub
            </a>
            <a
              href={`${GITHUB_URL}#quick-start`}
              target="_blank"
              rel="noreferrer"
              className="bg-white/5 border border-white/10 hover:bg-white/10 text-neutral-100 rounded-lg px-5 py-2.5 text-sm font-semibold transition"
            >
              Read the docs
            </a>
          </div>
        </div>
        <div className="relative">
          <div
            className="absolute -inset-4 rounded-2xl blur-2xl opacity-40"
            style={{
              background:
                'linear-gradient(135deg, rgba(249,115,22,0.3) 0%, rgba(168,85,247,0.2) 100%)',
            }}
          />
          <div className="relative bg-[#0d0d13] border border-white/10 rounded-xl p-5 font-mono text-[13px] leading-relaxed shadow-2xl">
            <div className="flex gap-1.5 mb-3">
              <span className="w-2.5 h-2.5 rounded-full bg-red-500/60" />
              <span className="w-2.5 h-2.5 rounded-full bg-yellow-500/60" />
              <span className="w-2.5 h-2.5 rounded-full bg-green-500/60" />
            </div>
            <div className="text-neutral-500"># clone &amp; run</div>
            <div className="text-neutral-300">
              <span className="text-orange-400">$</span> git clone{' '}
              <span className="text-emerald-300">
                github.com/TheAlexPG/ArchFlow
              </span>
            </div>
            <div className="text-neutral-300">
              <span className="text-orange-400">$</span> cd ArchFlow
            </div>
            <div className="text-neutral-300">
              <span className="text-orange-400">$</span> make setup &amp;&amp; make dev
            </div>
            <div className="mt-3 text-neutral-500"># running on :5173</div>
          </div>
        </div>
      </div>
    </section>
  )
}

function FinalCTA() {
  return (
    <section className="relative z-10 border-t border-white/5">
      <div className="max-w-3xl mx-auto px-6 py-24 text-center">
        <h2 className="text-3xl md:text-4xl font-bold text-neutral-100 mb-4 tracking-tight">
          Ready to model something real?
        </h2>
        <p className="text-neutral-400 mb-8">
          Sign in with Google or email — your first workspace is waiting.
        </p>
        <Link
          to="/login"
          className="inline-block bg-gradient-to-r from-orange-500 to-orange-600 hover:from-orange-400 hover:to-orange-500 text-white rounded-lg px-8 py-3.5 text-sm font-semibold shadow-[0_10px_30px_-10px_rgba(249,115,22,0.6)] transition"
        >
          Get started — free
        </Link>
      </div>
    </section>
  )
}

function Footer() {
  return (
    <footer className="relative z-10 border-t border-white/5 bg-black/40">
      <div className="max-w-6xl mx-auto px-6 py-12 grid grid-cols-2 md:grid-cols-4 gap-8 text-sm">
        <div className="col-span-2 md:col-span-1">
          <div className="flex items-center gap-2 mb-2">
            <img src="/logo.png" alt="" className="w-6 h-6 rounded" />
            <span className="font-semibold text-neutral-100">ArchFlow</span>
          </div>
          <p className="text-xs text-neutral-400 leading-relaxed">
            Self-hosted C4 architecture platform. AGPL-3.0.
          </p>
        </div>
        <FooterCol title="Product">
          <Link to="/login" className="hover:text-orange-400 transition">Sign in</Link>
          <a href={GITHUB_URL} target="_blank" rel="noreferrer" className="hover:text-orange-400 transition">GitHub</a>
          <a href={`${GITHUB_URL}/issues`} target="_blank" rel="noreferrer" className="hover:text-orange-400 transition">Report an issue</a>
        </FooterCol>
        <FooterCol title="Legal">
          <Link to="/terms" className="hover:text-orange-400 transition">Terms of service</Link>
          <Link to="/privacy" className="hover:text-orange-400 transition">Privacy policy</Link>
          <a href={`${GITHUB_URL}/blob/main/LICENSE`} target="_blank" rel="noreferrer" className="hover:text-orange-400 transition">License (AGPL-3.0)</a>
        </FooterCol>
        <FooterCol title="Resources">
          <a href={`${GITHUB_URL}#quick-start`} target="_blank" rel="noreferrer" className="hover:text-orange-400 transition">Quick start</a>
          <a href={`${GITHUB_URL}/tree/main/docs`} target="_blank" rel="noreferrer" className="hover:text-orange-400 transition">Docs</a>
          <a href="https://c4model.com" target="_blank" rel="noreferrer" className="hover:text-orange-400 transition">C4 model</a>
        </FooterCol>
      </div>
      {/* Always-visible inline bar — so even at a glance on mobile, Terms /
          Privacy are one tap away without hunting through the grid. */}
      <div className="border-t border-white/10 py-5">
        <div className="max-w-6xl mx-auto px-6 flex flex-col sm:flex-row items-center justify-between gap-3 text-xs">
          <div className="text-neutral-500">
            © ArchFlow · Built with care
          </div>
          <div className="flex flex-wrap items-center justify-center gap-x-5 gap-y-2 text-neutral-300">
            <Link to="/terms" className="hover:text-orange-400 transition">
              Terms
            </Link>
            <Link to="/privacy" className="hover:text-orange-400 transition">
              Privacy
            </Link>
            <a
              href={`${GITHUB_URL}/blob/main/LICENSE`}
              target="_blank"
              rel="noreferrer"
              className="hover:text-orange-400 transition"
            >
              License
            </a>
            <a
              href={GITHUB_URL}
              target="_blank"
              rel="noreferrer"
              className="hover:text-orange-400 transition"
            >
              GitHub
            </a>
          </div>
        </div>
      </div>
    </footer>
  )
}

function FooterCol({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-xs font-semibold text-neutral-100 uppercase tracking-wider mb-3">
        {title}
      </div>
      <div className="flex flex-col gap-2 text-neutral-300">{children}</div>
    </div>
  )
}

function SectionHead({
  eyebrow,
  title,
  body,
}: {
  eyebrow: string
  title: string
  body: string
}) {
  return (
    <div className="text-center max-w-2xl mx-auto">
      <div className="text-xs uppercase tracking-widest text-orange-400 font-semibold mb-3">
        {eyebrow}
      </div>
      <h2 className="text-3xl md:text-4xl font-bold text-neutral-100 tracking-tight">
        {title}
      </h2>
      <p className="mt-4 text-neutral-400 leading-relaxed">{body}</p>
    </div>
  )
}
