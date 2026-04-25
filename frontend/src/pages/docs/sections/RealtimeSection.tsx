import { CodeBlock } from '../CodeBlock'
import { Endpoint } from '../Endpoint'

export function RealtimeSection() {
  return (
    <section id="realtime">
      <h2>Realtime (WebSocket)</h2>
      <p>
        Three WebSocket endpoints surface live state. All authenticate via a
        JWT access token passed as a <code>?token=</code> query parameter
        (the standard browser WebSocket API does not support custom auth
        headers).
      </p>

      <h3 id="realtime-diagram">Diagram room</h3>
      <Endpoint
        method="WS"
        path="/api/v1/ws/diagrams/{diagram_id}?token=<jwt>"
        summary="Per-diagram presence + cursor + selection broadcast."
        auth="JWT (access)"
      >
        <CodeBlock title="Server-to-client frames" language="json">
{`{ "type": "presence.init",  "users": [ { "user_id": "...", "user_name": "..." } ] }
{ "type": "presence.join",  "user":  { "user_id": "...", "user_name": "..." } }
{ "type": "presence.leave", "user":  { "user_id": "...", "user_name": "..." } }
{ "type": "cursor",         "x": 120, "y": 240, "user_id": "...", "user_name": "..." }
{ "type": "selection",      "ids": ["..."],       "user_id": "...", "user_name": "..." }
{ "type": "pong" }`}
        </CodeBlock>
        <CodeBlock title="Client-to-server frames" language="json">
{`{ "type": "cursor",    "x": 100, "y": 200 }
{ "type": "selection", "ids": ["uuid"] }
{ "type": "ping" }`}
        </CodeBlock>
      </Endpoint>

      <h3 id="realtime-workspace">Workspace firehose</h3>
      <Endpoint
        method="WS"
        path="/api/v1/ws/workspace/{workspace_id}?token=<jwt>"
        summary="Workspace-wide change events so a client can refetch without polling."
        auth="JWT (access)"
      >
        <CodeBlock title="Frame shapes" language="json">
{`{ "type": "object.created",      "object":     { /* ObjectResponse */ } }
{ "type": "object.updated",      "object":     { /* ObjectResponse */ } }
{ "type": "object.deleted",      "id":         "uuid" }
{ "type": "connection.created",  "connection": { /* ConnectionResponse */ } }
{ "type": "connection.updated",  "connection": { /* ConnectionResponse */ } }
{ "type": "connection.deleted",  "id":         "uuid" }
{ "type": "diagram.created",     "diagram":    { /* DiagramResponse */ } }
{ "type": "diagram.updated",     "diagram":    { /* DiagramResponse */ } }
{ "type": "diagram.deleted",     "id":         "uuid" }
{ "type": "diagram_object.added"   /* + diagram_id, diagram_object */ }
{ "type": "diagram_object.updated" /* + diagram_id, diagram_object */ }
{ "type": "diagram_object.removed" /* + diagram_id, object_id     */ }
{ "type": "technology.created" /* updated / deleted */ }`}
        </CodeBlock>
      </Endpoint>

      <h3 id="realtime-me">User stream</h3>
      <Endpoint
        method="WS"
        path="/api/v1/ws/me?token=<jwt>"
        summary="Per-user notification stream. Stays connected across workspace switches."
        auth="JWT (access)"
      >
        <CodeBlock title="Heartbeat" language="json">
{`// Send periodically
{ "type": "ping" }
// Server replies
{ "type": "pong" }`}
        </CodeBlock>
      </Endpoint>

      <h3 id="realtime-tips">Tips for agents</h3>
      <ul>
        <li>Send a <code>ping</code> every ~25 seconds to keep idle proxies from closing the socket.</li>
        <li>
          Reconnect on close with exponential backoff. Re-fetch state via
          REST after reconnect since you may have missed events.
        </li>
        <li>
          The token query parameter is validated as an <code>access</code>{' '}
          JWT (not a refresh token). API keys are not currently accepted on
          WebSocket — use a JWT.
        </li>
      </ul>
    </section>
  )
}
