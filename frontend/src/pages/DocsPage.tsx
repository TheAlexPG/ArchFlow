import { DocsLayout, type TocEntry } from './docs/DocsLayout'
import { IntroSection } from './docs/sections/IntroSection'
import { AuthSection } from './docs/sections/AuthSection'
import { ApiKeysSection } from './docs/sections/ApiKeysSection'
import { WorkspacesSection } from './docs/sections/WorkspacesSection'
import { ObjectsSection } from './docs/sections/ObjectsSection'
import { ConnectionsSection } from './docs/sections/ConnectionsSection'
import { DiagramsSection } from './docs/sections/DiagramsSection'
import { TechnologiesSection } from './docs/sections/TechnologiesSection'
import { WebhooksSection } from './docs/sections/WebhooksSection'
import { RealtimeSection } from './docs/sections/RealtimeSection'
import { MiscSection } from './docs/sections/MiscSection'

const TOC: TocEntry[] = [
  { id: 'intro', label: 'Overview' },
  { id: 'auth', label: 'Authentication' },
  { id: 'api-keys', label: 'API Keys' },
  { id: 'workspaces', label: 'Workspaces' },
  { id: 'objects', label: 'Objects' },
  { id: 'connections', label: 'Connections' },
  { id: 'diagrams', label: 'Diagrams' },
  { id: 'technologies', label: 'Technologies' },
  { id: 'webhooks', label: 'Webhooks' },
  { id: 'realtime', label: 'Realtime (WS)' },
  { id: 'misc', label: 'Other endpoints' },
]

export function DocsPage() {
  return (
    <DocsLayout toc={TOC}>
      <IntroSection />
      <AuthSection />
      <ApiKeysSection />
      <WorkspacesSection />
      <ObjectsSection />
      <ConnectionsSection />
      <DiagramsSection />
      <TechnologiesSection />
      <WebhooksSection />
      <RealtimeSection />
      <MiscSection />
    </DocsLayout>
  )
}
