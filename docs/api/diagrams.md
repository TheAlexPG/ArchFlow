# Diagrams

A 2D canvas that pins a set of objects at specific positions. Each diagram has a type (C4 level) and lives in a workspace.

## Shape

```json
{
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
}
```

`type`: `L1 | L2 | L3 | L4 | flow`

## GET /api/v1/diagrams?scope_object_id=<uuid>
List in current workspace, ACL-filtered.

## GET /api/v1/diagrams/{diagram_id}
Fetch (403 if no team access).

## POST /api/v1/diagrams
```json
{ "name": "Auth — L3 components", "type": "L3", "description": "Auth subsystem.", "settings": {} }
```

## PUT /api/v1/diagrams/{diagram_id}
Patch any subset, including `pinned`.

## DELETE /api/v1/diagrams/{diagram_id}
Delete + cascade placements.

## Diagram objects (placements)

### GET /api/v1/diagrams/{diagram_id}/objects
List placements.

### POST /api/v1/diagrams/{diagram_id}/objects
```json
{ "object_id": "uuid", "position_x": 240, "position_y": 120, "width": 220, "height": 100 }
```

### PUT /api/v1/diagrams/{diagram_id}/objects/{object_id}
Move / resize.

### DELETE /api/v1/diagrams/{diagram_id}/objects/{object_id}
Remove the placement (object is preserved).

## PUT /api/v1/diagrams/{diagram_id}/pack
Assign or clear the pack.

## GET /api/v1/diagrams/{diagram_id}/drafts
Open drafts that include this diagram as a source.
