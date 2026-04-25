# Realtime (WebSocket)

Three WebSocket endpoints. All authenticate via JWT access token in the `?token=` query param.

## ws/diagrams/{diagram_id}
Per-diagram presence + cursor + selection.

```
ws://host/api/v1/ws/diagrams/<diagram_id>?token=<access jwt>
```

**Server frames**
```json
{ "type": "presence.init",  "users": [ { "user_id": "...", "user_name": "..." } ] }
{ "type": "presence.join",  "user":  { "user_id": "...", "user_name": "..." } }
{ "type": "presence.leave", "user":  { "user_id": "...", "user_name": "..." } }
{ "type": "cursor",         "x": 120, "y": 240, "user_id": "...", "user_name": "..." }
{ "type": "selection",      "ids": ["..."],       "user_id": "...", "user_name": "..." }
{ "type": "pong" }
```

**Client frames**
```json
{ "type": "cursor",    "x": 100, "y": 200 }
{ "type": "selection", "ids": ["uuid"] }
{ "type": "ping" }
```

## ws/workspace/{workspace_id}
Workspace firehose for change events.

```json
{ "type": "object.created",      "object":     { "...ObjectResponse..." } }
{ "type": "object.updated",      "object":     { "...ObjectResponse..." } }
{ "type": "object.deleted",      "id":         "uuid" }
{ "type": "connection.created",  "connection": { "...ConnectionResponse..." } }
{ "type": "connection.updated",  "connection": { "...ConnectionResponse..." } }
{ "type": "connection.deleted",  "id":         "uuid" }
{ "type": "diagram.created",     "diagram":    { "...DiagramResponse..." } }
{ "type": "diagram.updated",     "diagram":    { "...DiagramResponse..." } }
{ "type": "diagram.deleted",     "id":         "uuid" }
{ "type": "diagram_object.added"   /* + diagram_id, diagram_object */ }
{ "type": "diagram_object.updated" /* + diagram_id, diagram_object */ }
{ "type": "diagram_object.removed" /* + diagram_id, object_id     */ }
{ "type": "technology.created" /* updated / deleted */ }
```

## ws/me
Per-user notification stream. Stays connected across workspace switches. Heartbeat: send `{ "type": "ping" }`, server replies `{ "type": "pong" }`.

## Tips for agents
- Send `ping` every ~25s.
- Reconnect on close with backoff and re-fetch state via REST after reconnect.
- The token must be an access JWT (refresh tokens are rejected). API keys aren't accepted on WebSocket — use a JWT.
