---
name: archflow-api-client
description: Use when the user has an ArchFlow API key (starts with ak_) and wants to programmatically create or query architecture diagrams — listing workspaces, creating objects (people, systems, containers, components, groups), wiring connections between them, creating diagrams, placing objects on diagrams with x/y positions, or reading existing diagrams. Covers Authorization Bearer authentication, the X-Workspace-ID header, error handling for 401/403/404/409/429, and the constraint that API keys cannot authenticate WebSocket connections (use polling instead).
---

# ArchFlow API client skill

## Overview

ArchFlow exposes a REST API at `/api/v1` for programmatically building C4-style architecture models. This skill is a practical guide for an agent that has been given an API key and wants to drive the API end-to-end: pick a workspace, create objects, wire connections, lay them out on a diagram, and read the result back.

You do not need to clone the ArchFlow repository to use this skill. You only need:

- A reachable ArchFlow base URL (e.g. `https://api.archflow.tools` or a self-hosted instance like `http://localhost:8000`).
- An API key the user has issued you (a bearer token starting with `ak_`).

## Mental model

Three resource types, in this order of dependency:

```
Workspace      ← isolation boundary; everything below lives in one workspace
  ├─ Object   ← a thing in the architecture: person, system, container, component, group
  ├─ Connection ← directed edge from object A to object B
  └─ Diagram  ← a 2D canvas
       └─ DiagramObject ← "object O placed at x,y on diagram D" (a junction row)
```

Important consequences:

- **Objects and connections exist independent of any diagram.** You first create the objects, *then* build a diagram, *then* place the objects on it with positions. The same object can appear on many diagrams at different x/y coordinates.
- **Workspace is implicit.** Most endpoints read the current workspace from the `X-Workspace-ID` header. Forget the header and you'll silently land on the user's *oldest* workspace, which is rarely what you want.
- **Connection endpoints reference object UUIDs that already exist.** Create both objects first; the API will 400 if `source_id` or `target_id` is unknown.

## Configuration

Read these from environment variables (or ask the user once and remember them for the session):

| Variable               | Example                              | Required                                        |
| ---------------------- | ------------------------------------ | ----------------------------------------------- |
| `ARCHFLOW_API_URL`     | `https://api.archflow.tools`         | yes — base URL, no trailing slash               |
| `ARCHFLOW_API_KEY`     | `ak_aB3d_...`                        | yes — must start with `ak_`                     |
| `ARCHFLOW_WORKSPACE_ID`| `9f1e...`                            | optional — sets `X-Workspace-ID` for every call |

If the user hasn't given you a workspace id, list their workspaces (see below) and pick one explicitly before mutating. Don't rely on the "oldest workspace" fallback for anything that creates state — confirm first.

## Authentication

Every authenticated request needs:

```http
Authorization: Bearer ak_<the rest of the key>
```

The same `Authorization` header carries either a JWT or an API key — the server detects API keys by the `ak_` prefix. WebSockets are the one exception: `/api/v1/ws/*` only accept JWT access tokens (passed as `?token=`), so you can't subscribe to realtime updates with an API key. Poll the relevant REST endpoints instead.

API keys today inherit the owning user's full access (`permissions` array on a key is stored but unenforced). That means: if the user can do it, the key can do it. Workspace-mutating endpoints still enforce per-workspace role checks (`viewer < reviewer < editor < admin < owner`) — those check the *user's* role, not anything on the key.

### One-call sanity check

Before doing anything else, confirm the key works and identify the user:

```bash
curl -s "$ARCHFLOW_API_URL/api/v1/auth/me" \
  -H "Authorization: Bearer $ARCHFLOW_API_KEY"
```

Expect `200` with `{ "id": "...", "email": "...", "name": "...", "created_at": "..." }`. A `401` means the key is wrong, revoked, or expired — stop and tell the user.

## Workspace management

Choose a workspace before creating anything.

```bash
# List workspaces the key's owner is a member of
curl -s "$ARCHFLOW_API_URL/api/v1/workspaces" \
  -H "Authorization: Bearer $ARCHFLOW_API_KEY"
```

Response shape:

```json
[
  { "id": "uuid", "org_id": "uuid", "name": "Personal",
    "slug": "agent-personal", "role": "owner",
    "created_at": "2026-04-25T..." }
]
```

Pick one and pass its `id` as `X-Workspace-ID` on subsequent calls. If the user hasn't told you which workspace to use and there are multiple, ask them — don't guess.

If you need a brand-new workspace for the work you're about to do (e.g., a "scratch" sandbox so you don't pollute their main one):

```bash
curl -s -X POST "$ARCHFLOW_API_URL/api/v1/workspaces" \
  -H "Authorization: Bearer $ARCHFLOW_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{ "name": "Agent scratchpad" }'
```

## Step 1 — Create objects

`POST /api/v1/objects`. The two fields you almost always set are `name` and `type`. Everything else is optional.

```bash
curl -s -X POST "$ARCHFLOW_API_URL/api/v1/objects" \
  -H "Authorization: Bearer $ARCHFLOW_API_KEY" \
  -H "X-Workspace-ID: $ARCHFLOW_WORKSPACE_ID" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Auth Service",
    "type": "container",
    "scope": "internal",
    "status": "live",
    "description": "Issues and validates JWTs.",
    "tags": ["platform"]
  }'
```

Allowed enum values:

- `type`: `person | system | container | component | group`
- `scope`: `internal | external` (default `internal`)
- `status`: `live | deprecated | planned` (default `live`)

Capture the returned `id` — you'll need it for connections and diagram placements.

```json
{
  "id": "f0a8...-uuid",
  "name": "Auth Service",
  "type": "container",
  "c4_level": "L3",
  "...": "..."
}
```

`c4_level` is computed by the server from `type` (`person/system → L1/L2`, `container → L3`, `component → L4`). You don't set it; you read it.

### Creating a hierarchy

Pass `parent_id` to nest. A `container` with `parent_id` set to a `system` says "this container belongs to that system." A `group` is a visual cluster (e.g., "all microservices in this VPC").

```bash
# Parent system
SYSTEM_ID=$(curl -s -X POST "$ARCHFLOW_API_URL/api/v1/objects" \
  -H "Authorization: Bearer $ARCHFLOW_API_KEY" \
  -H "X-Workspace-ID: $ARCHFLOW_WORKSPACE_ID" \
  -H "Content-Type: application/json" \
  -d '{"name": "Identity Platform", "type": "system"}' \
  | jq -r .id)

# Child container
curl -s -X POST "$ARCHFLOW_API_URL/api/v1/objects" \
  -H "Authorization: Bearer $ARCHFLOW_API_KEY" \
  -H "X-Workspace-ID: $ARCHFLOW_WORKSPACE_ID" \
  -H "Content-Type: application/json" \
  -d "{\"name\": \"Auth Service\", \"type\": \"container\", \"parent_id\": \"$SYSTEM_ID\"}"
```

## Step 2 — Wire connections

`POST /api/v1/connections`. Connections are directed: `source_id → target_id`.

```bash
curl -s -X POST "$ARCHFLOW_API_URL/api/v1/connections" \
  -H "Authorization: Bearer $ARCHFLOW_API_KEY" \
  -H "X-Workspace-ID: $ARCHFLOW_WORKSPACE_ID" \
  -H "Content-Type: application/json" \
  -d '{
    "source_id": "<auth-service uuid>",
    "target_id": "<postgres uuid>",
    "label": "reads/writes",
    "direction": "unidirectional",
    "shape": "smoothstep"
  }'
```

- `direction`: `unidirectional` (single arrow) or `bidirectional` (arrow on both ends).
- `shape`: `smoothstep | bezier | step | straight` — purely visual; pick `smoothstep` if you don't have a preference.
- `label` is freeform text. Use it to describe the verb of the relationship ("reads", "publishes events to", "authenticates against").

Both endpoints must already exist; you'll get `400 Source object not found` if not.

If you got the direction wrong after the fact, don't recreate — flip:

```bash
curl -s -X POST "$ARCHFLOW_API_URL/api/v1/connections/$CONN_ID/flip" \
  -H "Authorization: Bearer $ARCHFLOW_API_KEY"
```

## Step 3 — Create a diagram

`POST /api/v1/diagrams`. A diagram is a canvas; its `type` is the C4 level you intend to draw at.

```bash
DIAGRAM_ID=$(curl -s -X POST "$ARCHFLOW_API_URL/api/v1/diagrams" \
  -H "Authorization: Bearer $ARCHFLOW_API_KEY" \
  -H "X-Workspace-ID: $ARCHFLOW_WORKSPACE_ID" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Identity Platform — L3 components",
    "type": "L3",
    "description": "Containers inside the Identity Platform system."
  }' \
  | jq -r .id)
```

`type`: `L1 | L2 | L3 | L4 | flow`. The diagram does not auto-include any objects — that's the next step.

## Step 4 — Place objects on the diagram

`POST /api/v1/diagrams/{diagram_id}/objects` adds an existing object to a diagram with a position.

```bash
curl -s -X POST "$ARCHFLOW_API_URL/api/v1/diagrams/$DIAGRAM_ID/objects" \
  -H "Authorization: Bearer $ARCHFLOW_API_KEY" \
  -H "X-Workspace-ID: $ARCHFLOW_WORKSPACE_ID" \
  -H "Content-Type: application/json" \
  -d '{
    "object_id": "<auth-service uuid>",
    "position_x": 240,
    "position_y": 120,
    "width": 220,
    "height": 100
  }'
```

Coordinate system: top-left origin, units are pixels at 1× zoom. The web canvas uses a 24px grid, so multiples of 24 (or 120 = 5 × 24) lay out cleanly. Reasonable defaults:

- `width`: 220 for a container, 180 for a component, 260 for a system, 80 for a person.
- `height`: 100 for boxes, 120 for grouped boxes.
- Spacing: leave at least 80px of horizontal gap and 60px of vertical gap between siblings, so labels don't collide with the connection routing.

A simple "left-to-right pipeline" layout for N items: place the i-th item at `x = 120 + i * 320`, `y = 200`.

You **must** add an object to a diagram for it to render there. Connections are *not* placed — they auto-route between whichever placements exist on the diagram. So the pattern is "place both endpoints of a connection on the diagram, and the edge appears."

To move or resize a placement later:

```bash
curl -s -X PUT "$ARCHFLOW_API_URL/api/v1/diagrams/$DIAGRAM_ID/objects/$OBJECT_ID" \
  -H "Authorization: Bearer $ARCHFLOW_API_KEY" \
  -H "X-Workspace-ID: $ARCHFLOW_WORKSPACE_ID" \
  -H "Content-Type: application/json" \
  -d '{"position_x": 480, "position_y": 320}'
```

To remove an object from a diagram (it survives elsewhere):

```bash
curl -s -X DELETE "$ARCHFLOW_API_URL/api/v1/diagrams/$DIAGRAM_ID/objects/$OBJECT_ID" \
  -H "Authorization: Bearer $ARCHFLOW_API_KEY" \
  -H "X-Workspace-ID: $ARCHFLOW_WORKSPACE_ID"
```

## Querying existing diagrams

| Need                            | Endpoint                                                    |
| ------------------------------- | ----------------------------------------------------------- |
| List diagrams in workspace      | `GET /api/v1/diagrams`                                      |
| One diagram's metadata          | `GET /api/v1/diagrams/{id}`                                 |
| Object placements on a diagram  | `GET /api/v1/diagrams/{id}/objects`                         |
| All objects in workspace        | `GET /api/v1/objects` (filter with `?type=`, `?status=`)    |
| Diagrams that contain an object | `GET /api/v1/objects/{id}/diagrams`                         |
| All connections                 | `GET /api/v1/connections`                                   |
| Connections between two objects | `GET /api/v1/connections/between?src=<uuid>&tgt=<uuid>`     |
| Direct children of an object    | `GET /api/v1/objects/{id}/children`                         |
| Resolved upstream/downstream    | `GET /api/v1/objects/{id}/dependencies`                     |

To reconstruct the full picture of a diagram (objects + their positions + the edges between them):

1. `GET /api/v1/diagrams/{id}/objects` → list of `{object_id, position_x, position_y, width, height}`.
2. For each `object_id`, `GET /api/v1/objects/{object_id}` → the actual object metadata (name, type, description, tags).
3. `GET /api/v1/connections` → filter to those whose `source_id` and `target_id` are both in step 1's set; those are the edges that render on this diagram.

## Error handling

| Status | What it means                                                                 | What to do                                                  |
| ------ | ----------------------------------------------------------------------------- | ----------------------------------------------------------- |
| 400    | Validation error — bad enum, missing required field, unknown referenced UUID | Read `detail`, fix the payload, retry                       |
| 401    | Missing/invalid/revoked/expired token                                         | Stop. Ask the user for a new key                            |
| 403    | Authenticated but not allowed (e.g., editor-only endpoint, workspace member with insufficient role) | Stop. Tell the user which role is required               |
| 404    | Resource doesn't exist *or* the caller can't see it (workspace isolation often surfaces as 404) | Verify your `X-Workspace-ID`; verify the UUID exists; don't retry blindly |
| 409    | Conflict — most commonly a duplicate slug on technologies, or deleting a tech that's still referenced | Read `detail`; for tech deletes, fetch `/usage` and clean refs first |
| 429    | Rate limited — per-key sliding window                                         | Inspect `Retry-After`/`X-RateLimit-Reset` headers, sleep, retry |
| 5xx    | Server error                                                                  | Retry with exponential backoff up to ~3 attempts; surface to user if persistent |

Error envelope is always `{"detail": "<human-readable message>"}` (sometimes `detail` is an object for structured errors like 409 on technology deletes).

Always inspect response status before parsing the body. A non-2xx body usually doesn't match the success schema and will crash a strict parser if you skip the status check.

### Idempotency

The API is **not** idempotent at the HTTP level — there is no `Idempotency-Key` header today. If you retry a `POST /objects` after a network blip you may end up with two duplicate objects. Defenses:

- Before retrying a create, list the resource (`GET /objects?type=container`) and check whether the previous attempt already landed.
- For batch jobs, write a small client-side dedupe based on `name + type + parent_id`.
- For destructive retries, `DELETE` first, then re-create.

## Realtime

API keys cannot authenticate the WebSocket endpoints (`/api/v1/ws/*`) — those need a JWT access token. If the user wants realtime updates from an agent that only has an API key, the agent must poll. Reasonable polling intervals:

- Workspace-level overview (objects + connections changing): 10–30 s.
- One specific diagram (you're watching for collaborator edits): 5–10 s.

For most agent workflows this doesn't matter — you make a change, you got the response, you already know the new state. Polling is only needed if you're watching for *other* clients' edits.

## Putting it all together — a runnable Python example

The single most useful pattern: build a small system end-to-end and verify it. This script creates two objects, connects them, makes a diagram, and places them.

```python
"""Build a tiny architecture diagram via the ArchFlow API.

Usage:
    export ARCHFLOW_API_URL=https://api.archflow.tools
    export ARCHFLOW_API_KEY=ak_xxx
    export ARCHFLOW_WORKSPACE_ID=<uuid>   # optional; uses default workspace if unset
    python build_demo_diagram.py
"""
import os
import sys
import requests

BASE = os.environ["ARCHFLOW_API_URL"].rstrip("/")
KEY = os.environ["ARCHFLOW_API_KEY"]
WORKSPACE = os.environ.get("ARCHFLOW_WORKSPACE_ID")

session = requests.Session()
session.headers["Authorization"] = f"Bearer {KEY}"
if WORKSPACE:
    session.headers["X-Workspace-ID"] = WORKSPACE


def call(method: str, path: str, **kwargs) -> dict | None:
    """Wrapper that surfaces ArchFlow's {"detail": ...} error envelope."""
    response = session.request(method, f"{BASE}{path}", timeout=15, **kwargs)
    if not response.ok:
        try:
            detail = response.json().get("detail")
        except ValueError:
            detail = response.text
        sys.exit(f"{method} {path} -> {response.status_code}: {detail}")
    return response.json() if response.content else None


# 0) sanity check — confirms the key works
me = call("GET", "/api/v1/auth/me")
print(f"Authenticated as {me['email']}")

# 1) ensure we know which workspace we're operating in
if not WORKSPACE:
    workspaces = call("GET", "/api/v1/workspaces")
    if len(workspaces) != 1:
        sys.exit(
            "ARCHFLOW_WORKSPACE_ID is unset and the user belongs to "
            f"{len(workspaces)} workspaces. Please set it explicitly."
        )
    session.headers["X-Workspace-ID"] = workspaces[0]["id"]
    print(f"Using workspace {workspaces[0]['name']}")

# 2) create the objects
user = call("POST", "/api/v1/objects",
            json={"name": "End User", "type": "person", "scope": "external"})
api = call("POST", "/api/v1/objects",
           json={"name": "Public API", "type": "container",
                 "description": "FastAPI service.", "tags": ["edge"]})
db = call("POST", "/api/v1/objects",
          json={"name": "Postgres", "type": "container",
                "description": "Primary datastore.", "tags": ["data"]})
print(f"Created: user={user['id']}  api={api['id']}  db={db['id']}")

# 3) wire the connections
call("POST", "/api/v1/connections",
     json={"source_id": user["id"], "target_id": api["id"],
           "label": "uses", "shape": "smoothstep"})
call("POST", "/api/v1/connections",
     json={"source_id": api["id"], "target_id": db["id"],
           "label": "reads/writes", "shape": "smoothstep"})

# 4) make a diagram
diagram = call("POST", "/api/v1/diagrams",
               json={"name": "Demo system — L3", "type": "L3"})
print(f"Diagram id: {diagram['id']}")

# 5) place the objects left-to-right
for i, obj in enumerate([user, api, db]):
    call("POST", f"/api/v1/diagrams/{diagram['id']}/objects",
         json={"object_id": obj["id"],
               "position_x": 120 + i * 320,
               "position_y": 240,
               "width": 220, "height": 100})

# 6) verify
placements = call("GET", f"/api/v1/diagrams/{diagram['id']}/objects")
print(f"Diagram now has {len(placements)} placed objects.")
```

Bash flavor of the same flow is mechanical — replace `session.request(...)` with `curl`, capture ids with `jq -r .id`.

## Common pitfalls

- **Forgetting `X-Workspace-ID`.** The default-workspace fallback is silent; you'll only notice when the objects you "created" don't appear where the user is looking. Always set the header on mutations.
- **Creating a connection before both endpoints exist.** API returns 400. Create both objects, then the connection.
- **Expecting connections to render without placing both endpoints.** The diagram only renders edges where both endpoints are placed on *that* diagram.
- **Using the API key on a WebSocket.** Won't work. Poll, or get a JWT.
- **Treating placements like edits to the object.** Moving an object on diagram A doesn't move it on diagram B — placements are per-diagram.
- **Retrying a `POST` after a timeout.** Without idempotency, you'll create duplicates. List first, then act.
- **Hardcoding a workspace UUID across users.** If you're sharing a script, always look up the workspace by name or ask the user — UUIDs are per-account.
- **Ignoring 429.** The rate limit is per-API-key. Honor `Retry-After`; back off don't hammer.

## Quick reference

| Action                          | Endpoint                                                     |
| ------------------------------- | ------------------------------------------------------------ |
| Verify key                      | `GET /api/v1/auth/me`                                        |
| List workspaces                 | `GET /api/v1/workspaces`                                     |
| Create workspace                | `POST /api/v1/workspaces`                                    |
| Create object                   | `POST /api/v1/objects`                                       |
| Update object                   | `PUT /api/v1/objects/{id}`                                   |
| Delete object                   | `DELETE /api/v1/objects/{id}` (cascades placements + edges)  |
| Create connection               | `POST /api/v1/connections`                                   |
| Flip connection                 | `POST /api/v1/connections/{id}/flip`                         |
| Delete connection               | `DELETE /api/v1/connections/{id}`                            |
| Create diagram                  | `POST /api/v1/diagrams`                                      |
| Add object to diagram           | `POST /api/v1/diagrams/{id}/objects`                         |
| Move/resize placement           | `PUT /api/v1/diagrams/{id}/objects/{object_id}`              |
| Remove placement (keep object)  | `DELETE /api/v1/diagrams/{id}/objects/{object_id}`           |
| Read placements                 | `GET /api/v1/diagrams/{id}/objects`                          |
| Read all diagrams               | `GET /api/v1/diagrams`                                       |

For the full HTTP surface, see ArchFlow's own `/docs` page or the markdown mirror under [`docs/api/`](https://github.com/TheAlexPG/ArchFlow/tree/main/docs/api).
