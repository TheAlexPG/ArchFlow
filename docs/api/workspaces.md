# Workspaces

A workspace is the unit of isolation for objects, connections, diagrams, technologies, teams and members. Most resource calls are workspace-scoped via the `X-Workspace-ID` header.

Roles: `owner`, `admin`, `editor`, `viewer`.

## GET /api/v1/workspaces
JWT. List workspaces the caller is a member of.

```json
[ { "id": "uuid", "org_id": "uuid", "name": "Personal", "slug": "...", "role": "owner", "created_at": "..." } ]
```

## POST /api/v1/workspaces
JWT. Create a workspace owned by the caller.

```json
{ "name": "Acme Inc" }
```

## GET /api/v1/workspaces/{workspace_id}
JWT. Fetch a workspace. 404 if not a member.

## PATCH /api/v1/workspaces/{workspace_id}
Admin. Rename.

```json
{ "name": "Acme Holdings" }
```

## DELETE /api/v1/workspaces/{workspace_id}
Owner only. 400 if not empty.

## Workspace header
```
X-Workspace-ID: <workspace uuid>
```
Without the header, the user's oldest workspace is used.
