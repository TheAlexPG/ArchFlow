# Connections

Directed relationships between objects.

## Shape

```json
{
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
}
```

`direction`: `unidirectional | bidirectional`
`shape`: `smoothstep | bezier | step | straight`

## GET /api/v1/connections
List in the current workspace. Optional `?draft_id`.

## GET /api/v1/connections/between?src=<uuid>&tgt=<uuid>
All connections between a pair of objects (both directions).

## GET /api/v1/connections/{connection_id}
Fetch one.

## POST /api/v1/connections
```json
{
  "source_id": "uuid",
  "target_id": "uuid",
  "label": "writes",
  "direction": "unidirectional",
  "shape": "smoothstep",
  "label_size": 11.0
}
```

## PUT /api/v1/connections/{connection_id}
Patch any subset.

## POST /api/v1/connections/{connection_id}/flip
Swap source and target.

## DELETE /api/v1/connections/{connection_id}
Delete.
