import { CodeBlock } from '../CodeBlock'

export function IntroSection() {
  return (
    <section id="intro">
      <h1>ArchFlow API Reference</h1>
      <p className="text-neutral-400 text-sm">
        Curated reference for AI agents and integrators. Covers the REST and
        WebSocket surface of an ArchFlow backend.
      </p>

      <h2 id="base-url">Base URL & versioning</h2>
      <p>
        All HTTP routes are mounted under <code>/api/v1</code>. There is one
        version line; breaking changes will introduce <code>/api/v2</code>.
      </p>
      <CodeBlock title="Example base URL">
        {`https://api.archflow.tools/api/v1`}
      </CodeBlock>

      <h2 id="conventions">Conventions</h2>
      <ul>
        <li>
          Identifiers are <code>UUID</code> (v4) unless explicitly noted.
        </li>
        <li>
          Timestamps are ISO 8601 strings in UTC (e.g.{' '}
          <code>2026-04-25T12:34:56Z</code>).
        </li>
        <li>
          Bodies are <code>application/json</code>; responses set{' '}
          <code>Content-Type: application/json</code>.
        </li>
        <li>
          Errors return an envelope of the form{' '}
          <code>{`{"detail": "<message>"}`}</code> with HTTP status codes
          (<code>400/401/403/404/409/429/5xx</code>).
        </li>
        <li>
          Most workspace-scoped reads honor an{' '}
          <code>X-Workspace-ID</code> request header — set it to the UUID of
          the workspace you are operating in. If omitted, the user's default
          workspace is used.
        </li>
      </ul>

      <h2 id="health">Health</h2>
      <CodeBlock language="http">
        {`GET /health  →  200 {"status":"ok"}`}
      </CodeBlock>
    </section>
  )
}
