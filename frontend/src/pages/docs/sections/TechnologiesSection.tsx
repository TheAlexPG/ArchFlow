import { CodeBlock } from '../CodeBlock'
import { Endpoint } from '../Endpoint'

export function TechnologiesSection() {
  return (
    <section id="technologies">
      <h2>Technologies</h2>
      <p>
        Technologies are the labels you attach to objects and connections
        ("PostgreSQL", "REST", "gRPC"). Each workspace gets the read-only
        built-in catalog plus its own custom set. Custom technologies are
        scoped to a single workspace.
      </p>

      <h3 id="technologies-shape">Shape</h3>
      <CodeBlock title="TechnologyResponse" language="json">
{`{
  "id": "uuid",
  "workspace_id": "uuid|null",
  "slug": "postgres",
  "name": "PostgreSQL",
  "iconify_name": "simple-icons:postgresql",
  "category": "database",
  "color": "#336791",
  "aliases": ["postgresql", "psql"],
  "created_by_user_id": "uuid|null",
  "created_at": "...",
  "updated_at": "..."
}`}
      </CodeBlock>
      <p className="text-sm text-neutral-400">
        <code>category</code>:{' '}
        <code>language | framework | database | messaging | cloud | protocol | tool | other</code>
      </p>

      <h3 id="technologies-list">List / search</h3>
      <Endpoint
        method="GET"
        path="/api/v1/workspaces/{workspace_id}/technologies"
        summary="Search the workspace's catalog (built-in + custom)."
        auth="JWT, role >= viewer"
      >
        <CodeBlock title="Query parameters">
{`q        ? fuzzy match over name / slug / aliases
category ? language|framework|database|messaging|cloud|protocol|tool|other
scope    ? all (default) | builtin | custom`}
        </CodeBlock>
      </Endpoint>

      <h3 id="technologies-create">Create custom</h3>
      <Endpoint
        method="POST"
        path="/api/v1/workspaces/{workspace_id}/technologies"
        summary="Add a custom technology to this workspace."
        auth="JWT, role >= editor"
      >
        <CodeBlock title="Request body" language="json">
{`{
  "name": "Internal RPC",
  "slug": "internal-rpc",
  "iconify_name": "mdi:server",
  "category": "protocol",
  "color": "#FF6B35",
  "aliases": ["irpc"]
}`}
        </CodeBlock>
      </Endpoint>

      <h3 id="technologies-update">Update custom</h3>
      <Endpoint
        method="PATCH"
        path="/api/v1/workspaces/{workspace_id}/technologies/{technology_id}"
        summary="Patch a custom technology. 403 for built-in entries."
        auth="JWT, role >= editor"
      />

      <h3 id="technologies-usage">Usage snapshot</h3>
      <Endpoint
        method="GET"
        path="/api/v1/workspaces/{workspace_id}/technologies/{technology_id}/usage"
        summary="How many objects/connections reference this technology. Pre-flight for delete."
        auth="JWT, role >= viewer"
      >
        <CodeBlock title="200 response" language="json">
{`{ "object_refs": 4, "connection_refs": 1, "detail": "Referenced by 4 objects and 1 connections" }`}
        </CodeBlock>
      </Endpoint>

      <h3 id="technologies-delete">Delete custom</h3>
      <Endpoint
        method="DELETE"
        path="/api/v1/workspaces/{workspace_id}/technologies/{technology_id}"
        summary="Delete a custom technology. Returns 409 if it's still referenced."
        auth="JWT, role >= editor"
      />
    </section>
  )
}
