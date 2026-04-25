# Objects

The canonical building block of an architecture model — a system, container, component, person, or group. Objects live in a workspace and can be added to one or more diagrams.

## Shape

```json
{
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
}
```

`type`: `person | system | container | component | group`
`scope`: `internal | external`
`status`: `live | deprecated | planned`

## GET /api/v1/objects
List objects in the current workspace. Optional filters: `type`, `status`, `parent_id`, `draft_id`.

## GET /api/v1/objects/{object_id}
Fetch a single object.

## POST /api/v1/objects
Create. Honors `X-Workspace-ID`. Optional `?draft_id=<uuid>`.

```json
{ "name": "Auth Service", "type": "container", "scope": "internal", "status": "live" }
```

## PUT /api/v1/objects/{object_id}
Patch any subset of fields.

## DELETE /api/v1/objects/{object_id}
Cascades to placements + connections.

## GET /api/v1/objects/{object_id}/children
Direct children (`parent_id == this.id`).

## GET /api/v1/objects/{object_id}/diagrams
All diagrams that include this object.

## GET /api/v1/objects/{object_id}/history?limit=100
Activity log entries (1-500, default 100).

## GET /api/v1/objects/{object_id}/dependencies
```json
{
  "upstream":   [ { "connection_id": "...", "source": { "...ObjectResponse..." } } ],
  "downstream": [ { "connection_id": "...", "target": { "...ObjectResponse..." } } ]
}
```

## POST /api/v1/objects/{object_id}/insights
LLM-generated insights. 503 if AI is not configured.
