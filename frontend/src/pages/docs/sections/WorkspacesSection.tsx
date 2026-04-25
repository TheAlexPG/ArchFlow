import { CodeBlock } from '../CodeBlock'
import { Endpoint } from '../Endpoint'

export function WorkspacesSection() {
  return (
    <section id="workspaces">
      <h2>Workspaces</h2>
      <p>
        The unit of isolation for objects, connections, diagrams, technologies,
        teams and members. Every user is provisioned one at sign-up; most
        resource calls scope to it via the <code>X-Workspace-ID</code> header.
        Mutating endpoints check the caller's role — <code>owner</code>,{' '}
        <code>admin</code>, <code>editor</code>, or <code>viewer</code>.
      </p>

      <h3 id="workspaces-list">List my workspaces</h3>
      <Endpoint
        method="GET"
        path="/api/v1/workspaces"
        summary="Return all workspaces the caller is a member of, with their role."
        auth="JWT or API key"
      >
        <CodeBlock title="200 response" language="json">
{`[
  {
    "id": "uuid",
    "org_id": "uuid",
    "name": "Personal",
    "slug": "agent-personal",
    "role": "owner",
    "created_at": "2026-04-25T..."
  }
]`}
        </CodeBlock>
      </Endpoint>

      <h3 id="workspaces-create">Create workspace</h3>
      <Endpoint
        method="POST"
        path="/api/v1/workspaces"
        summary="Create a new workspace owned by the caller."
        auth="JWT or API key"
      >
        <CodeBlock title="Request body" language="json">
{`{ "name": "Acme Inc" }`}
        </CodeBlock>
      </Endpoint>

      <h3 id="workspaces-get">Get workspace</h3>
      <Endpoint
        method="GET"
        path="/api/v1/workspaces/{workspace_id}"
        summary="Fetch a workspace the caller is a member of. 404 otherwise (no leakage)."
        auth="JWT or API key"
      />

      <h3 id="workspaces-rename">Rename</h3>
      <Endpoint
        method="PATCH"
        path="/api/v1/workspaces/{workspace_id}"
        summary="Rename a workspace. Requires admin role."
        auth="JWT, role >= admin"
      >
        <CodeBlock title="Request body" language="json">
{`{ "name": "Acme Holdings" }`}
        </CodeBlock>
      </Endpoint>

      <h3 id="workspaces-delete">Delete</h3>
      <Endpoint
        method="DELETE"
        path="/api/v1/workspaces/{workspace_id}"
        summary="Delete an empty workspace. Returns 400 if it still contains content. Owner-only."
        auth="JWT, role = owner"
      />

      <h3 id="workspace-header">Workspace header</h3>
      <p>
        For endpoints that operate on workspace-scoped resources (objects,
        connections, diagrams, …), set:
      </p>
      <CodeBlock language="http">
{`X-Workspace-ID: <workspace uuid>`}
      </CodeBlock>
      <p className="text-sm text-neutral-400">
        Without the header, the user's default (oldest) workspace is used.
      </p>
    </section>
  )
}
