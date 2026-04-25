import { CodeBlock } from '../CodeBlock'
import { Endpoint } from '../Endpoint'

export function DiagramsSection() {
  return (
    <section id="diagrams">
      <h2>Diagrams</h2>
      <p>
        A 2D canvas that pins a set of objects at specific positions. Each
        diagram has a C4 level (<code>L1</code>–<code>L4</code> or{' '}
        <code>flow</code>) and lives in one workspace. Place objects onto it
        with <code>POST /diagrams/{'{id}'}/objects</code>; the same object can
        appear on many diagrams with independent positions.
      </p>

      <h3 id="diagrams-shape">Shape</h3>
      <CodeBlock title="DiagramResponse" language="json">
{`{
  "id": "uuid",
  "name": "Auth — L3 components",
  "type": "L3",
  "description": "...",
  "scope_object_id": "uuid|null",
  "settings": {},
  "pinned": false,
  "draft_id": null,
  "pack_id": null,
  "created_at": "...",
  "updated_at": "..."
}`}
      </CodeBlock>
      <p className="text-sm text-neutral-400">
        <code>type</code>: <code>L1 | L2 | L3 | L4 | flow</code>
      </p>

      <h3 id="diagrams-list">List</h3>
      <Endpoint
        method="GET"
        path="/api/v1/diagrams?scope_object_id=<uuid>"
        summary="List diagrams in the current workspace. Filtered by team-ACL for non-admins."
        auth="optional"
      />

      <h3 id="diagrams-get">Get</h3>
      <Endpoint
        method="GET"
        path="/api/v1/diagrams/{diagram_id}"
        summary="Fetch a diagram. Returns 403 if the workspace member lacks team access."
        auth="optional"
      />

      <h3 id="diagrams-create">Create</h3>
      <Endpoint
        method="POST"
        path="/api/v1/diagrams"
        summary="Create a diagram in the workspace selected by X-Workspace-ID."
        auth="JWT or API key"
      >
        <CodeBlock title="Request body" language="json">
{`{
  "name": "Auth — L3 components",
  "type": "L3",
  "description": "Auth subsystem.",
  "scope_object_id": null,
  "settings": {}
}`}
        </CodeBlock>
      </Endpoint>

      <h3 id="diagrams-update">Update</h3>
      <Endpoint
        method="PUT"
        path="/api/v1/diagrams/{diagram_id}"
        summary="Patch any subset of diagram fields, including pinned."
        auth="JWT or API key"
      />

      <h3 id="diagrams-delete">Delete</h3>
      <Endpoint
        method="DELETE"
        path="/api/v1/diagrams/{diagram_id}"
        summary="Delete a diagram and all its object placements."
        auth="JWT or API key"
      />

      <h3 id="diagrams-objects">Diagram objects (placements)</h3>
      <p>
        Each placement records where an object sits on this particular
        diagram. Objects can appear on multiple diagrams.
      </p>
      <Endpoint
        method="GET"
        path="/api/v1/diagrams/{diagram_id}/objects"
        summary="List object placements for a diagram."
        auth="optional"
      />
      <Endpoint
        method="POST"
        path="/api/v1/diagrams/{diagram_id}/objects"
        summary="Add an existing object to this diagram with a position/size."
        auth="JWT or API key"
      >
        <CodeBlock title="Request body" language="json">
{`{
  "object_id": "uuid",
  "position_x": 240,
  "position_y": 120,
  "width": 220,
  "height": 100
}`}
        </CodeBlock>
      </Endpoint>
      <Endpoint
        method="PUT"
        path="/api/v1/diagrams/{diagram_id}/objects/{object_id}"
        summary="Move/resize an object placement. All fields optional."
        auth="JWT or API key"
      />
      <Endpoint
        method="DELETE"
        path="/api/v1/diagrams/{diagram_id}/objects/{object_id}"
        summary="Remove the object from this diagram (object itself is preserved)."
        auth="JWT or API key"
      />

      <h3 id="diagrams-pack">Set diagram pack</h3>
      <Endpoint
        method="PUT"
        path="/api/v1/diagrams/{diagram_id}/pack"
        summary="Assign or clear the visual pack for a diagram. pack_id must be in the same workspace."
        auth="JWT or API key"
      />

      <h3 id="diagrams-drafts">Drafts containing this diagram</h3>
      <Endpoint
        method="GET"
        path="/api/v1/diagrams/{diagram_id}/drafts"
        summary="List open drafts that include this diagram as a source."
        auth="optional"
      />
    </section>
  )
}
