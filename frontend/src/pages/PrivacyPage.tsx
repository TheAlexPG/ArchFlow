import { LegalLayout } from './legal-layout'

export function PrivacyPage() {
  return (
    <LegalLayout title="Privacy Policy" lastUpdated="2026-04-23">
      <p>
        This Privacy Policy explains what data{' '}
        <a href="https://archflow.tools">archflow.tools</a> collects, how it's
        used, and your rights around it. The hosted Service is run on a small
        personal server — we collect as little as we can get away with.
      </p>

      <h2>1. What we collect</h2>
      <ul>
        <li>
          <strong>Account data.</strong> Email address and display name. If
          you sign in with Google OAuth, we also receive your basic Google
          profile (email, name) — nothing more. We never receive your Google
          password.
        </li>
        <li>
          <strong>Your Content.</strong> Everything you explicitly create:
          diagrams, objects, connections, comments, drafts, versions,
          workspaces, teams, invites.
        </li>
        <li>
          <strong>Activity metadata.</strong> Timestamps of creates/updates/
          deletes on your own Content, so you can see your own history.
        </li>
        <li>
          <strong>Operational logs.</strong> Standard web server logs (IP
          address, user agent, request path, response code, timestamp) kept
          for up to 30 days for security and debugging. No request bodies are
          logged.
        </li>
      </ul>

      <h2>2. What we don't collect</h2>
      <ul>
        <li>No analytics trackers (no Google Analytics, no Facebook pixel, no Mixpanel).</li>
        <li>No advertising cookies.</li>
        <li>No fingerprinting.</li>
        <li>No selling or sharing of your data with third-party marketers.</li>
        <li>No training third-party ML models on Your Content.</li>
      </ul>

      <h2>3. Cookies & storage</h2>
      <p>
        We use <code>localStorage</code> to remember your sign-in session and
        which workspace you're currently looking at. That's it. No tracking
        cookies.
      </p>

      <h2>4. Where data lives</h2>
      <p>
        All data is stored on a dedicated server hosted with Hetzner
        (Germany/Finland). Backups, if any, are stored in the same
        jurisdiction. Data is transmitted over TLS (HTTPS/WSS).
      </p>

      <h2>5. Who can see your data</h2>
      <ul>
        <li>
          <strong>You.</strong> Always. Everything you created.
        </li>
        <li>
          <strong>Collaborators you invite.</strong> Only to the workspaces /
          teams / diagrams you've explicitly granted them access to.
        </li>
        <li>
          <strong>The maintainers.</strong> Operational access to the
          database for support and debugging. We don't routinely read your
          Content.
        </li>
      </ul>

      <h2>6. Optional AI features</h2>
      <p>
        If the maintainers enable AI Insights, and if you trigger them, the
        relevant object / diagram data for that request is sent to Anthropic
        (Claude) for processing. This is per-click — nothing is sent
        automatically or in the background. You can see which endpoints
        trigger this in the open-source code. AI is disabled unless the
        operator configures an API key.
      </p>

      <h2>7. Your rights</h2>
      <p>
        You can request export or deletion of all data associated with your
        account at any time via{' '}
        <a
          href="https://github.com/TheAlexPG/ArchFlow/issues"
          target="_blank"
          rel="noreferrer"
        >
          a GitHub issue
        </a>
        . Deletion requests are honored within 30 days.
      </p>

      <h2>8. Security</h2>
      <p>
        We use standard practices: TLS, password hashing (bcrypt), JWT for
        sessions, isolated database networks. No system is 100% secure — if
        you discover a vulnerability please report it privately via GitHub
        security advisories at{' '}
        <a
          href="https://github.com/TheAlexPG/ArchFlow/security/advisories"
          target="_blank"
          rel="noreferrer"
        >
          the repo's security tab
        </a>
        .
      </p>

      <h2>9. Children</h2>
      <p>
        The Service is not directed at children under 13 and we don't
        knowingly collect data from them.
      </p>

      <h2>10. Changes</h2>
      <p>
        We may update this policy. The "Last updated" date at the top
        reflects the most recent revision.
      </p>

      <h2>11. Contact</h2>
      <p>
        Questions or requests? Open an issue at{' '}
        <a
          href="https://github.com/TheAlexPG/ArchFlow/issues"
          target="_blank"
          rel="noreferrer"
        >
          github.com/TheAlexPG/ArchFlow/issues
        </a>
        .
      </p>
    </LegalLayout>
  )
}
