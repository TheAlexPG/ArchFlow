import { CodeBlock } from '../CodeBlock'
import { Endpoint } from '../Endpoint'

export function ObjectsSection() {
  return (
    <section id="objects">
      <h2>Objects</h2>
      <p>
        An <em>object</em> is the canonical building block of an architecture
        model — a system, container, component, person, or group. Objects live
        in a workspace and can be added to one or more diagrams (each
        membership carries its own position).
      </p>

      <h3 id="objects-shape">Shape</h3>
      <CodeBlock title="ObjectResponse" language="json">
{`{
  "id": "uuid",
  "name": "Auth Service",
  "type": "container",
  "scope": "internal",
  "status": "live",
  "c4_level": "L3",
  "description": "Issues JWTs.",
  "icon": null,
  "parent_id": null,
  "technology_ids": ["uuid"],
  "tags": ["billing"],
  "owner_team": "platform",
  "external_links": { "repo": "https://..." },
  "metadata": {},
  "created_at": "...",
  "updated_at": "..."
}`}
      </CodeBlock>
      <p className="text-sm text-neutral-400">
        <code>type</code>: <code>person | system | container | component | group</code>{' '}
        · <code>scope</code>: <code>internal | external</code> · <code>status</code>:{' '}
        <code>live | deprecated | planned</code>
      </p>

      <h3 id="objects-list">List objects</h3>
      <Endpoint
        method="GET"
        path="/api/v1/objects"
        summary="List objects in the current workspace. Filterable by type, status, parent_id, draft_id."
        auth="optional"
      >
        <CodeBlock title="Query parameters">
{`type        ? person | system | container | component | group
status      ? live | deprecated | planned
parent_id   ? uuid (only direct children)
draft_id    ? uuid (also include objects forked into this draft)`}
        </CodeBlock>
      </Endpoint>

      <h3 id="objects-get">Get object</h3>
      <Endpoint
        method="GET"
        path="/api/v1/objects/{object_id}"
        summary="Fetch a single object."
        auth="optional"
      />

      <h3 id="objects-create">Create object</h3>
      <Endpoint
        method="POST"
        path="/api/v1/objects"
        summary="Create an object. Honors X-Workspace-ID. Pass ?draft_id=<uuid> to scope to a draft."
        auth="JWT or API key"
      >
        <CodeBlock title="Request body" language="json">
{`{
  "name": "Auth Service",
  "type": "container",
  "scope": "internal",
  "status": "live",
  "description": "Issues JWTs.",
  "parent_id": null,
  "technology_ids": ["..."],
  "tags": ["billing"],
  "owner_team": "platform",
  "external_links": {},
  "metadata": {}
}`}
        </CodeBlock>
      </Endpoint>

      <h3 id="objects-update">Update object</h3>
      <Endpoint
        method="PUT"
        path="/api/v1/objects/{object_id}"
        summary="Patch any subset of object fields. All fields are optional in the body."
        auth="JWT or API key"
      />

      <h3 id="objects-delete">Delete object</h3>
      <Endpoint
        method="DELETE"
        path="/api/v1/objects/{object_id}"
        summary="Delete an object. Cascades to its diagram memberships and connections."
        auth="JWT or API key"
      />

      <h3 id="objects-children">Children</h3>
      <Endpoint
        method="GET"
        path="/api/v1/objects/{object_id}/children"
        summary="Direct children (objects whose parent_id equals this id)."
        auth="optional"
      />

      <h3 id="objects-diagrams">Containing diagrams</h3>
      <Endpoint
        method="GET"
        path="/api/v1/objects/{object_id}/diagrams"
        summary="All diagrams that include this object."
        auth="optional"
      />

      <h3 id="objects-history">History</h3>
      <Endpoint
        method="GET"
        path="/api/v1/objects/{object_id}/history"
        summary="Activity log entries for this object (limit 1-500, default 100)."
        auth="optional"
      />

      <h3 id="objects-dependencies">Dependencies</h3>
      <Endpoint
        method="GET"
        path="/api/v1/objects/{object_id}/dependencies"
        summary="Resolved upstream/downstream connections."
        auth="optional"
      >
        <CodeBlock title="200 response" language="json">
{`{
  "upstream":   [ { "connection_id": "...", "source": { /* ObjectResponse */ } } ],
  "downstream": [ { "connection_id": "...", "target": { /* ObjectResponse */ } } ]
}`}
        </CodeBlock>
      </Endpoint>

      <h3 id="objects-insights">AI Insights (optional)</h3>
      <Endpoint
        method="POST"
        path="/api/v1/objects/{object_id}/insights"
        summary="LLM-generated insights for the object. Returns 503 if AI is not configured."
        auth="JWT or API key"
      />
    </section>
  )
}
