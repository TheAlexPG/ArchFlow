# Technologies

Technology labels you attach to objects and connections. Each workspace has a built-in catalog plus its own custom set.

## Shape

```json
{
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
}
```

`category`: `language | framework | database | messaging | cloud | protocol | tool | other`

## GET /api/v1/workspaces/{workspace_id}/technologies
Viewer+. Search the catalog.

Query: `q` (fuzzy), `category`, `scope` (`all|builtin|custom`).

## POST /api/v1/workspaces/{workspace_id}/technologies
Editor+. Add a custom.

```json
{
  "name": "Internal RPC",
  "iconify_name": "mdi:server",
  "category": "protocol",
  "color": "#FF6B35",
  "aliases": ["irpc"]
}
```

## PATCH /api/v1/workspaces/{workspace_id}/technologies/{technology_id}
Editor+. Patch a custom (403 for built-in).

## GET /api/v1/workspaces/{workspace_id}/technologies/{technology_id}/usage
Viewer+. Reference snapshot.

```json
{ "object_refs": 4, "connection_refs": 1, "detail": "Referenced by 4 objects and 1 connections" }
```

## DELETE /api/v1/workspaces/{workspace_id}/technologies/{technology_id}
Editor+. 409 if still referenced.
