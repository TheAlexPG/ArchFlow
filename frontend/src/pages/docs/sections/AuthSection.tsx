import { CodeBlock } from '../CodeBlock'
import { Endpoint } from '../Endpoint'

export function AuthSection() {
  return (
    <section id="auth">
      <h2>Authentication</h2>
      <p>
        Register users, trade credentials for tokens, and resolve the current
        identity. Two credential types are accepted on the same{' '}
        <code>Authorization</code> header — short-lived JWTs (good for browser
        sessions) and long-lived API keys prefixed <code>ak_</code> (good for
        agents; see <a href="#api-keys">API Keys</a>).
      </p>
      <CodeBlock title="Authorization header (either)">
{`Authorization: Bearer <jwt access token>
Authorization: Bearer ak_<api key secret>`}
      </CodeBlock>

      <h3 id="auth-register">Register</h3>
      <Endpoint
        method="POST"
        path="/api/v1/auth/register"
        summary="Create a new user. Returns access + refresh JWTs and provisions a personal workspace."
        auth="public"
      >
        <CodeBlock title="Request body" language="json">
{`{
  "email": "agent@example.com",
  "name": "Agent Smith",
  "password": "min-6-chars"
}`}
        </CodeBlock>
        <CodeBlock title="201 response" language="json">
{`{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer"
}`}
        </CodeBlock>
      </Endpoint>

      <h3 id="auth-login">Login</h3>
      <Endpoint
        method="POST"
        path="/api/v1/auth/login"
        summary="Exchange email + password for access + refresh JWTs."
        auth="public"
      >
        <CodeBlock title="Request body" language="json">
{`{ "email": "agent@example.com", "password": "..." }`}
        </CodeBlock>
        <CodeBlock title="200 response" language="json">
{`{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer"
}`}
        </CodeBlock>
      </Endpoint>

      <h3 id="auth-refresh">Refresh</h3>
      <Endpoint
        method="POST"
        path="/api/v1/auth/refresh"
        summary="Trade a refresh token for a fresh access + refresh pair. Pass refresh_token as a query parameter."
        auth="refresh JWT"
      >
        <CodeBlock title="Request" language="http">
{`POST /api/v1/auth/refresh?refresh_token=eyJ...`}
        </CodeBlock>
      </Endpoint>

      <h3 id="auth-me">Current user</h3>
      <Endpoint
        method="GET"
        path="/api/v1/auth/me"
        summary="Return the authenticated user's profile."
        auth="JWT or API key"
      >
        <CodeBlock title="200 response" language="json">
{`{
  "id": "f0a8...-uuid",
  "email": "agent@example.com",
  "name": "Agent Smith",
  "created_at": "2026-04-25T10:00:00Z"
}`}
        </CodeBlock>
      </Endpoint>
    </section>
  )
}
