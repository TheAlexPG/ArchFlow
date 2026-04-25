import { CodeBlock } from '../CodeBlock'
import { Endpoint } from '../Endpoint'

export function ApiKeysSection() {
  return (
    <section id="api-keys">
      <h2>API Keys</h2>
      <p>
        API keys are long-lived credentials suited for AI agents and CI
        integrations. They begin with <code>ak_</code> and are presented as
        plaintext on the <code>Authorization</code> header.
      </p>
      <p>
        The full secret is returned <strong>only at creation time</strong> — store
        it immediately. Subsequent <code>GET</code> calls return only the{' '}
        <code>key_prefix</code>.
      </p>

      <h3 id="api-keys-create">Create key</h3>
      <Endpoint
        method="POST"
        path="/api/v1/api-keys"
        summary="Create an API key for the current user."
        auth="JWT"
      >
        <CodeBlock title="Request body" language="json">
{`{
  "name": "agent-smith-prod",
  "permissions": ["read", "write"],
  "expires_in_days": 365
}`}
        </CodeBlock>
        <CodeBlock title="201 response (secret returned once)" language="json">
{`{
  "id": "9f1e...-uuid",
  "name": "agent-smith-prod",
  "key_prefix": "ak_aB3d",
  "permissions": ["read", "write"],
  "expires_at": "2027-04-25T...",
  "last_used_at": null,
  "revoked_at": null,
  "created_at": "2026-04-25T...",
  "secret": "ak_aB3d_<remainder of secret>"
}`}
        </CodeBlock>
      </Endpoint>

      <h3 id="api-keys-list">List keys</h3>
      <Endpoint
        method="GET"
        path="/api/v1/api-keys"
        summary="List all keys owned by the current user. Secret is never included."
        auth="JWT"
      />

      <h3 id="api-keys-revoke">Revoke key</h3>
      <Endpoint
        method="DELETE"
        path="/api/v1/api-keys/{key_id}"
        summary="Permanently revoke a key. Returns 204 on success, 404 if not found."
        auth="JWT"
      />

      <h3 id="api-keys-usage">Using a key</h3>
      <CodeBlock title="cURL example" language="bash">
{`curl https://api.archflow.tools/api/v1/auth/me \\
  -H "Authorization: Bearer ak_aB3d_<rest>"`}
      </CodeBlock>
      <p className="text-sm text-neutral-400">
        Mutating endpoints called this way are subject to a per-user rate
        limit. Exceeding it returns <code>429 Too Many Requests</code>.
      </p>
    </section>
  )
}
