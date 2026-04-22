import { LegalLayout } from './legal-layout'

export function TermsPage() {
  return (
    <LegalLayout title="Terms of Service" lastUpdated="2026-04-23">
      <p>
        These Terms of Service ("Terms") govern your use of the ArchFlow
        service hosted at <a href="https://archflow.tools">archflow.tools</a>{' '}
        (the "Service"). By signing in you agree to these Terms. The Service
        is operated by the ArchFlow maintainers on a personal, non-commercial
        basis.
      </p>

      <h2>1. The Service</h2>
      <p>
        ArchFlow is an open-source C4 architecture modeling platform released
        under the{' '}
        <a
          href="https://github.com/TheAlexPG/ArchFlow/blob/main/LICENSE"
          target="_blank"
          rel="noreferrer"
        >
          GNU Affero General Public License v3.0
        </a>
        . You may also self-host your own copy — the source is at{' '}
        <a
          href="https://github.com/TheAlexPG/ArchFlow"
          target="_blank"
          rel="noreferrer"
        >
          github.com/TheAlexPG/ArchFlow
        </a>
        .
      </p>

      <h2>2. Accounts</h2>
      <p>
        You can sign in with an email/password pair or via Google OAuth. You
        are responsible for keeping your credentials secure and for all
        activity that happens on your account. One account per human, please.
      </p>

      <h2>3. Acceptable use</h2>
      <p>Do not use the Service to:</p>
      <ul>
        <li>Upload or generate illegal content or content you don't have the right to share.</li>
        <li>Attempt to break, overload, or otherwise interfere with the Service or other users.</li>
        <li>Scrape or enumerate other users' data.</li>
        <li>Use the Service to train third-party machine-learning models on other users' content without permission.</li>
      </ul>
      <p>
        We may suspend or delete accounts that violate these rules. We try to
        give notice first, but aren't obligated to.
      </p>

      <h2>4. Your content</h2>
      <p>
        You own the architecture diagrams, objects, connections, comments, and
        any other content you create in the Service ("Your Content"). We store
        it so we can show it back to you and to collaborators you've granted
        access to. We don't sell Your Content, we don't train models on it,
        and we don't share it with third parties except as needed to operate
        the Service (e.g. cloud hosting).
      </p>

      <h2>5. Availability & changes</h2>
      <p>
        The Service is provided on a best-effort basis. It may be unavailable,
        slow, or buggy. Features may change or disappear. We may shut the
        hosted Service down at any time — but because ArchFlow is open source,
        you can always spin up your own copy and keep working.
      </p>

      <h2>6. No warranty</h2>
      <p>
        THE SERVICE IS PROVIDED "AS IS" WITHOUT WARRANTY OF ANY KIND, EXPRESS
        OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
        MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, AND
        NONINFRINGEMENT. IN NO EVENT SHALL THE MAINTAINERS BE LIABLE FOR ANY
        CLAIM, DAMAGES, OR OTHER LIABILITY ARISING FROM USE OF THE SERVICE.
      </p>

      <h2>7. Termination</h2>
      <p>
        You can stop using the Service at any time. Contact us via{' '}
        <a
          href="https://github.com/TheAlexPG/ArchFlow/issues"
          target="_blank"
          rel="noreferrer"
        >
          GitHub issues
        </a>{' '}
        to request deletion of your account and Your Content.
      </p>

      <h2>8. Changes to these Terms</h2>
      <p>
        We may update these Terms occasionally. The "Last updated" date at the
        top reflects the most recent revision. Continued use of the Service
        after changes means you accept the revised Terms.
      </p>

      <h2>9. Contact</h2>
      <p>
        Questions? Open an issue at{' '}
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
