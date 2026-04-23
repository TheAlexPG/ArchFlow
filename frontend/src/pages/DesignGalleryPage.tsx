import {
  Avatar,
  AvatarStack,
  Button,
  Kbd,
  LevelBar,
  Pill,
  PillDot,
  Pulse,
  SectionLabel,
  StatusPill,
} from '../components/ui'
import type { PillVariant } from '../components/ui'

// ─── Section wrapper ───────────────────────────────────────────────────────

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-4">
      <SectionLabel>{title}</SectionLabel>
      <div className="flex flex-wrap gap-3 items-center">{children}</div>
    </div>
  )
}

// ─── Page ──────────────────────────────────────────────────────────────────

export function DesignGalleryPage() {
  const statusVariants: Array<Exclude<PillVariant, 'neutral'>> = [
    'done',
    'review',
    'processing',
    'input',
    'draft',
    'ai',
  ]

  return (
    <div className="min-h-screen page-bg p-8 font-sans">
      <div className="max-w-4xl mx-auto flex flex-col gap-10">

        {/* Header */}
        <div className="flex flex-col gap-1">
          <h1 className="text-[22px] font-semibold text-text-base tracking-tight">
            Design Gallery
          </h1>
          <p className="font-mono text-[11px] text-text-3">
            /design · DEV-only visual token review
          </p>
        </div>

        {/* ── Pills ─────────────────────────────────────────────────── */}
        <div
          className="bg-panel border border-border-base rounded-xl p-6 flex flex-col gap-6 shadow-window"
        >
          <Section title="Pill — neutral">
            <Pill>NEUTRAL</Pill>
            <Pill dotColor="#FF6B35">WITH DOT</Pill>
            <Pill>
              <PillDot color="#60a5fa" />
              CUSTOM DOT
            </Pill>
          </Section>

          <Section title="Pill — status variants">
            {statusVariants.map((v) => (
              <StatusPill key={v} status={v}>
                {v.toUpperCase()}
              </StatusPill>
            ))}
          </Section>

          <Section title="Pill — all variant prop">
            <Pill variant="neutral">NEUTRAL</Pill>
            <Pill variant="done">DONE</Pill>
            <Pill variant="review">REVIEW</Pill>
            <Pill variant="processing">PROCESSING</Pill>
            <Pill variant="input">INPUT</Pill>
            <Pill variant="draft">DRAFT</Pill>
            <Pill variant="ai">AI</Pill>
          </Section>
        </div>

        {/* ── Buttons ───────────────────────────────────────────────── */}
        <div className="bg-panel border border-border-base rounded-xl p-6 flex flex-col gap-6 shadow-window">
          <Section title="Button — variants">
            <Button variant="default">Default</Button>
            <Button variant="primary">Primary</Button>
            <Button variant="ghost">Ghost</Button>
          </Section>

          <Section title="Button — sizes">
            <Button size="default">Default size</Button>
            <Button size="sm">Small</Button>
            <Button size="icon" aria-label="icon button">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <line x1="12" y1="5" x2="12" y2="19"/>
                <line x1="5" y1="12" x2="19" y2="12"/>
              </svg>
            </Button>
          </Section>

          <Section title="Button — icons">
            <Button
              variant="primary"
              leftIcon={
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                  <line x1="12" y1="5" x2="12" y2="19"/>
                  <line x1="5" y1="12" x2="19" y2="12"/>
                </svg>
              }
            >
              New diagram
            </Button>
            <Button
              variant="default"
              rightIcon={<Kbd>⌘K</Kbd>}
            >
              Search
            </Button>
          </Section>

          <Section title="Button — disabled state">
            <Button disabled>Disabled default</Button>
            <Button variant="primary" disabled>Disabled primary</Button>
          </Section>
        </div>

        {/* ── Kbd ───────────────────────────────────────────────────── */}
        <div className="bg-panel border border-border-base rounded-xl p-6 flex flex-col gap-6 shadow-window">
          <Section title="Kbd — keycap chips">
            <Kbd>⌘K</Kbd>
            <Kbd>⌘S</Kbd>
            <Kbd>Esc</Kbd>
            <Kbd>⌃⇧P</Kbd>
            <Kbd>Enter</Kbd>
          </Section>
        </div>

        {/* ── SectionLabel ──────────────────────────────────────────── */}
        <div className="bg-panel border border-border-base rounded-xl p-6 flex flex-col gap-6 shadow-window">
          <Section title="SectionLabel">
            <div className="w-full flex flex-col gap-3">
              <SectionLabel>DIAGRAMS</SectionLabel>
              <SectionLabel counter={12}>WITH COUNTER</SectionLabel>
              <SectionLabel counter="∞">CONNECTIONS</SectionLabel>
            </div>
          </Section>
        </div>

        {/* ── Pulse ─────────────────────────────────────────────────── */}
        <div className="bg-panel border border-border-base rounded-xl p-6 flex flex-col gap-6 shadow-window">
          <Section title="Pulse — presence dots">
            <div className="flex items-center gap-2">
              <Pulse color="green" />
              <span className="font-mono text-[11px] text-text-3">green (online)</span>
            </div>
            <div className="flex items-center gap-2">
              <Pulse color="coral" />
              <span className="font-mono text-[11px] text-text-3">coral (active)</span>
            </div>
            <div className="flex items-center gap-2">
              <Pulse color="blue" />
              <span className="font-mono text-[11px] text-text-3">blue (sync)</span>
            </div>
          </Section>
        </div>

        {/* ── LevelBar ──────────────────────────────────────────────── */}
        <div className="bg-panel border border-border-base rounded-xl p-6 flex flex-col gap-6 shadow-window">
          <Section title="LevelBar — C4 levels">
            {([1, 2, 3, 4] as const).map((lvl) => (
              <div key={lvl} className="flex items-center gap-2">
                <LevelBar level={lvl} />
                <span className="font-mono text-[11px] text-text-3">L{lvl}</span>
              </div>
            ))}
          </Section>
        </div>

        {/* ── Avatar ────────────────────────────────────────────────── */}
        <div className="bg-panel border border-border-base rounded-xl p-6 flex flex-col gap-6 shadow-window">
          <Section title="Avatar — gradients">
            <Avatar initials="AB" gradient="coral-amber" />
            <Avatar initials="CP" gradient="coral-purple" />
            <Avatar initials="BP" gradient="blue-purple" />
            <Avatar initials="GB" gradient="green-blue" />
          </Section>

          <Section title="Avatar — sizes">
            <Avatar initials="XS" size="xs" />
            <Avatar initials="SM" size="sm" />
            <Avatar initials="MD" size="md" />
          </Section>

          <Section title="AvatarStack — presence">
            <AvatarStack>
              <Avatar initials="AB" gradient="coral-amber" size="sm" />
              <Avatar initials="CP" gradient="coral-purple" size="sm" />
              <Avatar initials="BP" gradient="blue-purple" size="sm" />
              <Avatar initials="GB" gradient="green-blue" size="sm" />
            </AvatarStack>
          </Section>
        </div>

        {/* ── Composition demo ──────────────────────────────────────── */}
        <div className="bg-panel border border-border-base rounded-xl p-6 flex flex-col gap-6 shadow-window">
          <SectionLabel counter={3}>RECENT DIAGRAMS</SectionLabel>
          <div className="flex flex-col gap-2">
            {['System Context', 'Container Map', 'Component Detail'].map((name, i) => (
              <div
                key={name}
                className="flex items-center justify-between px-3 py-2.5 rounded-lg border border-border-base bg-surface hover:bg-surface-hi hover:border-border-hi transition-all duration-[120ms]"
              >
                <div className="flex items-center gap-3">
                  <LevelBar level={((i + 1) as 1 | 2 | 3 | 4)} />
                  <span className="text-[13px] text-text-base">{name}</span>
                </div>
                <div className="flex items-center gap-2">
                  <StatusPill status={(['done', 'draft', 'review'] as const)[i]}>
                    {(['DONE', 'DRAFT', 'REVIEW'] as const)[i]}
                  </StatusPill>
                  <AvatarStack>
                    <Avatar initials="AB" gradient="coral-amber" size="xs" />
                    <Avatar initials="CP" gradient="blue-purple" size="xs" />
                  </AvatarStack>
                </div>
              </div>
            ))}
          </div>
          <div className="flex items-center justify-between pt-2">
            <div className="flex items-center gap-2">
              <Pulse color="green" />
              <span className="font-mono text-[10.5px] text-text-3">3 ONLINE</span>
            </div>
            <div className="flex items-center gap-2">
              <Button variant="ghost" size="sm">Filter</Button>
              <Button variant="primary" size="sm"
                leftIcon={
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                    <line x1="12" y1="5" x2="12" y2="19"/>
                    <line x1="5" y1="12" x2="19" y2="12"/>
                  </svg>
                }
              >
                New
              </Button>
              <Kbd>⌘N</Kbd>
            </div>
          </div>
        </div>

      </div>
    </div>
  )
}
