import { Link } from 'react-router-dom'

const GITHUB_URL = 'https://github.com/TheAlexPG/ArchFlow'

export function LandingPage() {
  return (
    <div className="min-h-screen bg-white text-slate-900 antialiased">
      <Nav />
      <Hero />
      <Features />
      <HowItWorks />
      <OpenSource />
      <FinalCTA />
      <Footer />
    </div>
  )
}

function Nav() {
  return (
    <header className="sticky top-0 z-20 bg-white/80 backdrop-blur border-b border-slate-200">
      <div className="max-w-6xl mx-auto flex items-center justify-between px-6 py-3">
        <Link to="/" className="flex items-center gap-2">
          <img src="/logo.png" alt="" className="w-8 h-8 rounded-lg" />
          <span className="font-semibold text-slate-900">ArchFlow</span>
          <span className="text-[10px] font-medium text-orange-600 bg-orange-50 border border-orange-100 rounded px-1.5 py-0.5">
            beta
          </span>
        </Link>
        <div className="flex items-center gap-5 text-sm">
          <a
            href={GITHUB_URL}
            target="_blank"
            rel="noreferrer"
            className="text-slate-600 hover:text-slate-900"
          >
            GitHub
          </a>
          <Link to="/login" className="text-slate-600 hover:text-slate-900">
            Sign in
          </Link>
          <Link
            to="/login"
            className="bg-slate-900 hover:bg-slate-800 text-white rounded-lg px-3 py-1.5 font-medium"
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
    <section className="relative overflow-hidden">
      <div className="max-w-4xl mx-auto px-6 py-24 md:py-32 text-center">
        <img
          src="/logo.png"
          alt="ArchFlow"
          className="w-20 h-20 mx-auto mb-8 rounded-2xl shadow-sm"
        />
        <div className="inline-flex items-center gap-2 bg-orange-50 text-orange-700 text-xs font-medium px-3 py-1 rounded-full border border-orange-100 mb-5">
          <span className="w-1.5 h-1.5 rounded-full bg-orange-500" />
          Self-hosted · AGPL-3.0
        </div>
        <h1 className="text-4xl md:text-6xl font-bold tracking-tight text-slate-900 leading-[1.1]">
          Draw your architecture
          <br />
          <span className="text-orange-600">the way you think about it.</span>
        </h1>
        <p className="mt-6 text-lg text-slate-600 max-w-2xl mx-auto leading-relaxed">
          ArchFlow is a visual-first C4 architecture platform. Model your
          systems, containers, and components — then collaborate, review, and
          ship with a typed model under the hood.
        </p>
        <div className="mt-8 flex flex-wrap gap-3 justify-center">
          <Link
            to="/login"
            className="bg-orange-600 hover:bg-orange-500 text-white rounded-lg px-6 py-3 text-sm font-semibold shadow-sm"
          >
            Sign in to get started
          </Link>
          <a
            href={GITHUB_URL}
            target="_blank"
            rel="noreferrer"
            className="bg-white border border-slate-300 hover:border-slate-400 text-slate-900 rounded-lg px-6 py-3 text-sm font-semibold"
          >
            Star on GitHub ★
          </a>
        </div>
        <p className="mt-5 text-xs text-slate-500">
          Free forever · Self-host with one <code className="text-orange-600">docker compose</code> command.
        </p>
      </div>
      {/* Subtle grid backdrop */}
      <div
        className="absolute inset-0 pointer-events-none opacity-[0.03]"
        style={{
          backgroundImage:
            'linear-gradient(#000 1px, transparent 1px), linear-gradient(90deg, #000 1px, transparent 1px)',
          backgroundSize: '40px 40px',
          zIndex: -1,
        }}
      />
    </section>
  )
}

function Features() {
  const items = [
    {
      title: 'C4-native data model',
      body:
        'Objects carry types, status, technology, tags, and owner teams. Drill L1 → L2 → L3 and the model stays consistent at every zoom.',
      icon: '▦',
    },
    {
      title: 'Real-time collaboration',
      body:
        'Live cursors, presence, selection sync, and optimistic drag & resize. Teammates see each other edit in one tick.',
      icon: '⚡',
    },
    {
      title: 'Drafts & reviews',
      body:
        'Fork any diagram. Edit in isolation. Diff against live. Resolve conflicts. Merge — zero surprises in production.',
      icon: '⤴',
    },
    {
      title: 'Team-level ACL',
      body:
        'Workspaces, teams, roles. Grant read / edit / manage on individual diagrams. Pending-approval invites.',
      icon: '👥',
    },
    {
      title: 'REST + WebSocket API',
      body:
        'OpenAPI with a generated TypeScript client. API keys and webhooks are first-class citizens next to JWT.',
      icon: '⟷',
    },
    {
      title: 'AGPL, self-hostable',
      body:
        'No vendor lock-in. Your data stays on your hardware. One Docker Compose file; Helm chart included.',
      icon: '⌂',
    },
  ]
  return (
    <section className="bg-slate-50 border-y border-slate-200">
      <div className="max-w-6xl mx-auto px-6 py-20">
        <SectionHead
          eyebrow="Features"
          title="Everything you need to model software"
          body="Built to replace PowerPoint-for-architecture with something that stays in sync with how the system actually works."
        />
        <div className="mt-12 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {items.map((f) => (
            <div
              key={f.title}
              className="bg-white border border-slate-200 rounded-xl p-6 hover:border-orange-300 hover:shadow-sm transition"
            >
              <div className="w-10 h-10 rounded-lg bg-orange-50 border border-orange-100 text-orange-600 flex items-center justify-center text-lg mb-4">
                {f.icon}
              </div>
              <div className="font-semibold text-slate-900 mb-1">{f.title}</div>
              <div className="text-sm text-slate-600 leading-relaxed">{f.body}</div>
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
        'Open a system, fork its Container diagram. Model apps, stores, and queues that live inside. The model tracks hierarchy automatically.',
    },
    {
      n: '03',
      title: 'Zoom into Components',
      body:
        'Pick any container and expand its internals. Objects reused across levels keep their identity — edit once, it lands everywhere.',
    },
  ]
  return (
    <section>
      <div className="max-w-6xl mx-auto px-6 py-24">
        <SectionHead
          eyebrow="How it works"
          title="The C4 model, but collaborative"
          body="Three zoom levels, one typed model, zero duplication."
        />
        <div className="mt-14 grid grid-cols-1 md:grid-cols-3 gap-6">
          {steps.map((s) => (
            <div key={s.n} className="relative">
              <div className="text-5xl font-bold text-orange-600/20 mb-2">{s.n}</div>
              <div className="font-semibold text-slate-900 mb-2 text-lg">{s.title}</div>
              <div className="text-sm text-slate-600 leading-relaxed">{s.body}</div>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

function OpenSource() {
  return (
    <section className="bg-slate-900 text-white">
      <div className="max-w-6xl mx-auto px-6 py-20 grid grid-cols-1 md:grid-cols-2 gap-10 items-center">
        <div>
          <div className="text-xs uppercase tracking-widest text-orange-400 mb-3">
            Open source
          </div>
          <h2 className="text-3xl md:text-4xl font-bold mb-4">
            Your architecture. Your hardware. Your rules.
          </h2>
          <p className="text-slate-300 leading-relaxed">
            ArchFlow is released under AGPL-3.0. Clone the repo, run{' '}
            <code className="text-orange-400">make setup</code>, and you have
            the full platform on your laptop in under a minute. Ship to your
            own Hetzner / AWS / bare-metal box with one Docker Compose file.
          </p>
          <div className="mt-6 flex gap-3 flex-wrap">
            <a
              href={GITHUB_URL}
              target="_blank"
              rel="noreferrer"
              className="bg-white text-slate-900 hover:bg-slate-100 rounded-lg px-5 py-2.5 text-sm font-semibold"
            >
              View on GitHub
            </a>
            <a
              href={`${GITHUB_URL}#quick-start`}
              target="_blank"
              rel="noreferrer"
              className="border border-slate-700 hover:border-slate-500 text-white rounded-lg px-5 py-2.5 text-sm font-semibold"
            >
              Read the docs
            </a>
          </div>
        </div>
        <div className="bg-slate-950 border border-slate-800 rounded-xl p-5 font-mono text-[13px] leading-relaxed">
          <div className="text-slate-500"># clone &amp; run</div>
          <div className="text-slate-300">
            <span className="text-orange-400">$</span> git clone{' '}
            <span className="text-emerald-300">github.com/TheAlexPG/ArchFlow</span>
          </div>
          <div className="text-slate-300">
            <span className="text-orange-400">$</span> cd ArchFlow
          </div>
          <div className="text-slate-300">
            <span className="text-orange-400">$</span> make setup &amp;&amp; make dev
          </div>
          <div className="mt-3 text-slate-500"># you're running ArchFlow on :5173</div>
        </div>
      </div>
    </section>
  )
}

function FinalCTA() {
  return (
    <section>
      <div className="max-w-3xl mx-auto px-6 py-24 text-center">
        <h2 className="text-3xl md:text-4xl font-bold text-slate-900 mb-4">
          Ready to model something real?
        </h2>
        <p className="text-slate-600 mb-8">
          Sign in with Google or email — your first workspace is waiting.
        </p>
        <Link
          to="/login"
          className="inline-block bg-orange-600 hover:bg-orange-500 text-white rounded-lg px-8 py-3 text-sm font-semibold shadow-sm"
        >
          Get started — free
        </Link>
      </div>
    </section>
  )
}

function Footer() {
  return (
    <footer className="border-t border-slate-200 bg-slate-50">
      <div className="max-w-6xl mx-auto px-6 py-10 grid grid-cols-2 md:grid-cols-4 gap-6 text-sm">
        <div className="col-span-2 md:col-span-1">
          <div className="flex items-center gap-2 mb-2">
            <img src="/logo.png" alt="" className="w-6 h-6 rounded" />
            <span className="font-semibold text-slate-900">ArchFlow</span>
          </div>
          <p className="text-xs text-slate-500 leading-relaxed">
            Self-hosted C4 architecture platform. AGPL-3.0.
          </p>
        </div>
        <FooterCol title="Product">
          <Link to="/login" className="hover:text-slate-900">Sign in</Link>
          <a href={GITHUB_URL} target="_blank" rel="noreferrer" className="hover:text-slate-900">GitHub</a>
          <a href={`${GITHUB_URL}/issues`} target="_blank" rel="noreferrer" className="hover:text-slate-900">Report an issue</a>
        </FooterCol>
        <FooterCol title="Legal">
          <Link to="/terms" className="hover:text-slate-900">Terms of service</Link>
          <Link to="/privacy" className="hover:text-slate-900">Privacy policy</Link>
          <a href={`${GITHUB_URL}/blob/main/LICENSE`} target="_blank" rel="noreferrer" className="hover:text-slate-900">License (AGPL-3.0)</a>
        </FooterCol>
        <FooterCol title="Resources">
          <a href={`${GITHUB_URL}#quick-start`} target="_blank" rel="noreferrer" className="hover:text-slate-900">Quick start</a>
          <a href={`${GITHUB_URL}/tree/main/docs`} target="_blank" rel="noreferrer" className="hover:text-slate-900">Docs</a>
          <a href="https://c4model.com" target="_blank" rel="noreferrer" className="hover:text-slate-900">C4 model</a>
        </FooterCol>
      </div>
      <div className="border-t border-slate-200 py-4 text-center text-xs text-slate-500">
        © ArchFlow · Built with care ·{' '}
        <a
          href={GITHUB_URL}
          target="_blank"
          rel="noreferrer"
          className="hover:text-slate-700"
        >
          Open source
        </a>
      </div>
    </footer>
  )
}

function FooterCol({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-xs font-semibold text-slate-900 uppercase tracking-wider mb-3">
        {title}
      </div>
      <div className="flex flex-col gap-1.5 text-slate-600">{children}</div>
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
      <div className="text-xs uppercase tracking-widest text-orange-600 font-semibold mb-3">
        {eyebrow}
      </div>
      <h2 className="text-3xl md:text-4xl font-bold text-slate-900 tracking-tight">
        {title}
      </h2>
      <p className="mt-4 text-slate-600 leading-relaxed">{body}</p>
    </div>
  )
}
