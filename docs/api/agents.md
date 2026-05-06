# Agents

## Endpoints

### List agents
`GET /api/v1/agents`

Filtered by ApiKey scopes / WorkspaceMember.agent_access. Optional `?surface=a2a` to filter by surface.

Response:
```json
{
  "agents": [
    {
      "id": "general",
      "name": "General Architecture Assistant",
      "description": "...",
      "schema_version": "v1",
      "surfaces": ["chat_bubble", "a2a"],
      "allowed_contexts": ["workspace", "diagram", "object"],
      "supported_modes": ["full", "read_only"],
      "required_scope": "agents:invoke",
      "tools_overview": ["search_existing_objects", "create_object", "..."],
      "limits": {"turn_limit": 200, "budget_usd": "1.00", "budget_scope": "per_invocation"},
      "streaming": true
    }
  ]
}
```

### Invoke (one-shot)
`POST /api/v1/agents/{agent_id}/invoke`

Headers:
- `Authorization: Bearer ak_…` (or session cookie)
- `Idempotency-Key: <uuid>` (optional, 24h cache)

Body: see InvokeBody schema.

### Chat (SSE streaming)
`POST /api/v1/agents/{agent_id}/chat`

Returns `text/event-stream`. See SSE event protocol below.

### Sessions
- `GET /api/v1/agents/sessions` — list
- `GET /api/v1/agents/sessions/{id}` — get with messages
- `GET /api/v1/agents/sessions/{id}/stream?since=N` — reconnect
- `POST /api/v1/agents/sessions/{id}/cancel` — cancel
- `POST /api/v1/agents/sessions/{id}/respond` — respond to requires_choice
- `DELETE /api/v1/agents/sessions/{id}` — hard delete

### Settings
- `GET/PUT /api/v1/agents/settings` — workspace admin only

## Scopes

| Scope | What it allows |
|---|---|
| agents:read | discovery + read-only agents |
| agents:invoke | + general agent in read-only mode |
| agents:write | + full mode + mutating tools |
| agents:admin | + delete operations + settings |
