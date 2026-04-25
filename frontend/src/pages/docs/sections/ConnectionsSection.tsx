import { CodeBlock } from '../CodeBlock'
import { Endpoint } from '../Endpoint'

export function ConnectionsSection() {
  return (
    <section id="connections">
      <h2>Connections</h2>
      <p>
        Directed edges between two objects. Each connection carries an
        optional label, protocol tags, edge shape, and direction
        (uni- or bidirectional), plus optional waypoints for routing the line
        on the canvas.
      </p>

      <h3 id="connections-shape">Shape</h3>
      <CodeBlock title="ConnectionResponse" language="json">
{`{
  "id": "uuid",
  "source_id": "uuid",
  "target_id": "uuid",
  "label": "writes",
  "protocol_ids": ["uuid"],
  "direction": "unidirectional",
  "tags": ["sync"],
  "source_handle": null,
  "target_handle": null,
  "shape": "smoothstep",
  "label_size": 11.0,
  "via_object_ids": null,
  "created_at": "...",
  "updated_at": "..."
}`}
      </CodeBlock>
      <p className="text-sm text-neutral-400">
        <code>direction</code>: <code>unidirectional | bidirectional</code> ·{' '}
        <code>shape</code>: <code>smoothstep | bezier | step | straight</code>
      </p>

      <h3 id="connections-list">List</h3>
      <Endpoint
        method="GET"
        path="/api/v1/connections"
        summary="List connections in the current workspace. Optional ?draft_id."
        auth="optional"
      />

      <h3 id="connections-between">Between two objects</h3>
      <Endpoint
        method="GET"
        path="/api/v1/connections/between?src=<uuid>&tgt=<uuid>"
        summary="All connections whose endpoints match the given pair (both directions)."
        auth="optional"
      />

      <h3 id="connections-get">Get</h3>
      <Endpoint
        method="GET"
        path="/api/v1/connections/{connection_id}"
        summary="Fetch a single connection."
        auth="optional"
      />

      <h3 id="connections-create">Create</h3>
      <Endpoint
        method="POST"
        path="/api/v1/connections"
        summary="Create a connection between two existing objects."
        auth="JWT or API key"
      >
        <CodeBlock title="Request body" language="json">
{`{
  "source_id": "uuid",
  "target_id": "uuid",
  "label": "writes",
  "protocol_ids": [],
  "direction": "unidirectional",
  "tags": [],
  "shape": "smoothstep",
  "label_size": 11.0
}`}
        </CodeBlock>
      </Endpoint>

      <h3 id="connections-update">Update</h3>
      <Endpoint
        method="PUT"
        path="/api/v1/connections/{connection_id}"
        summary="Patch any subset of connection fields. All optional."
        auth="JWT or API key"
      />

      <h3 id="connections-flip">Flip direction</h3>
      <Endpoint
        method="POST"
        path="/api/v1/connections/{connection_id}/flip"
        summary="Swap source_id and target_id. Useful when fixing an arrow."
        auth="JWT or API key"
      />

      <h3 id="connections-delete">Delete</h3>
      <Endpoint
        method="DELETE"
        path="/api/v1/connections/{connection_id}"
        summary="Delete a connection."
        auth="JWT or API key"
      />
    </section>
  )
}
