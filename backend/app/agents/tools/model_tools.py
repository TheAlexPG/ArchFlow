"""Read tools for the model layer (objects, connections, dependencies).

Implements task agent-core-mvp-027. Write tools (create_*, update_*, delete_*)
are stubbed here and implemented in task agent-core-mvp-029.

Spec: §4.3 Read tools, §4.8 Output projections.
"""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agents.errors import ToolDenied
from app.agents.tools.base import ToolContext, short_preview, tool

# ---------------------------------------------------------------------------
# Input schemas
# ---------------------------------------------------------------------------


class ReadObjectInput(BaseModel):
    object_id: UUID


class ReadObjectFullInput(BaseModel):
    object_id: UUID


class ReadConnectionInput(BaseModel):
    connection_id: UUID


class DependenciesInput(BaseModel):
    object_id: UUID
    depth: int = Field(1, ge=1, le=3)


class ListObjectsInput(BaseModel):
    types: list[str] = Field(default_factory=list)
    parent_id: UUID | None = None
    limit: int = Field(50, ge=1, le=200)
    cursor: str | None = None


class ListDiagramsInput(BaseModel):
    level: str | None = None  # 'L1' | 'L2' | 'L3' | 'L4'
    parent_object_id: UUID | None = None
    limit: int = Field(50, ge=1, le=200)
    cursor: str | None = None


class CreateObjectInput(BaseModel):
    """Input for create_object tool."""

    name: str = Field(..., min_length=1, max_length=255)
    type: str
    parent_id: UUID | None = None
    technology_ids: list[UUID] = Field(default_factory=list)
    description: str | None = None
    status: str | None = None
    tags: list[str] = Field(default_factory=list)
    owner_team: str | None = None


class UpdateObjectInput(BaseModel):
    """Input for update_object tool."""

    object_id: UUID
    patch: dict[str, Any]


class DeleteObjectInput(BaseModel):
    """Input for delete_object tool."""

    object_id: UUID
    confirmed: bool = False


class CreateConnectionInput(BaseModel):
    """Input for create_connection tool."""

    source_object_id: UUID
    target_object_id: UUID
    label: str | None = None
    direction: str = "outgoing"
    technology_ids: list[UUID] = Field(default_factory=list)
    description: str | None = None


class UpdateConnectionInput(BaseModel):
    """Input for update_connection tool."""

    connection_id: UUID
    patch: dict[str, Any]


class DeleteConnectionInput(BaseModel):
    """Input for delete_connection tool."""

    connection_id: UUID
    confirmed: bool = False


class ReadDiagramInput(BaseModel):
    diagram_id: UUID


class ReadCanvasStateInput(BaseModel):
    diagram_id: UUID


class ListChildDiagramsInput(BaseModel):
    object_id: UUID


class ReadChildDiagramInput(BaseModel):
    diagram_id: UUID


# ---------------------------------------------------------------------------
# Projection helpers
# ---------------------------------------------------------------------------

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str | None) -> str:
    """Strip HTML tags from a string, returning plain text (or empty string)."""
    if not text:
        return ""
    return _HTML_TAG_RE.sub("", text).strip()


def _project_object_basic(obj: Any) -> dict:
    """Return the basic object projection per spec §4.8.

    Fields: id, name, type, parent_id, has_child_diagram, technology_ids.
    Intentionally excludes description, coords, owner, tags.
    """
    return {
        "id": str(obj.id),
        "name": obj.name,
        "type": obj.type.value if hasattr(obj.type, "value") else str(obj.type),
        "parent_id": str(obj.parent_id) if obj.parent_id else None,
        "has_child_diagram": getattr(obj, "_has_child_diagram", False),
        "technology_ids": [str(t) for t in (obj.technology_ids or [])],
    }


def _project_object_full(obj: Any) -> dict:
    """Extended projection: basic fields + description (plain-text), tags, owner,
    created_at, updated_at. HTML never sent to LLM.
    """
    basic = _project_object_basic(obj)
    basic.update(
        {
            "description": _strip_html(obj.description),
            "tags": list(obj.tags or []),
            "owner_team": obj.owner_team,
            "status": obj.status.value if hasattr(obj.status, "value") else str(obj.status),
            "scope": obj.scope.value if hasattr(obj.scope, "value") else str(obj.scope),
            "created_at": str(obj.created_at) if getattr(obj, "created_at", None) else None,
            "updated_at": str(obj.updated_at) if getattr(obj, "updated_at", None) else None,
        }
    )
    return basic


def _project_connection(conn: Any) -> dict:
    """Connection projection per spec §4.8: id, source_id, target_id, label, technology_ids."""
    return {
        "id": str(conn.id),
        "source_id": str(conn.source_id),
        "target_id": str(conn.target_id),
        "label": conn.label,
        "technology_ids": [str(t) for t in (conn.protocol_ids or [])],
        "direction": (
            conn.direction.value if hasattr(conn.direction, "value") else str(conn.direction)
        ),
    }


def _project_diagram_meta(diagram: Any) -> dict:
    """Diagram metadata projection (no placements/connections)."""
    return {
        "id": str(diagram.id),
        "name": diagram.name,
        "type": (
            diagram.type.value if hasattr(diagram.type, "value") else str(diagram.type)
        ),
        "description": diagram.description or "",
        "scope_object_id": (
            str(diagram.scope_object_id) if diagram.scope_object_id else None
        ),
        "workspace_id": str(diagram.workspace_id) if diagram.workspace_id else None,
    }


def _cursor_encode(offset: int) -> str:
    return str(offset)


def _cursor_decode(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        return int(cursor)
    except ValueError:
        return 0


# ---------------------------------------------------------------------------
# Async service helpers (resolve has_child_diagram etc.)
# ---------------------------------------------------------------------------


async def _check_has_child_diagram(db: Any, object_id: UUID) -> bool:
    """Return True if any diagram has scope_object_id == object_id."""
    from app.models.diagram import Diagram

    result = await db.execute(
        select(Diagram.id).where(Diagram.scope_object_id == object_id).limit(1)
    )
    return result.scalar_one_or_none() is not None


async def _get_object_with_child_flag(db: Any, object_id: UUID) -> Any | None:
    """Fetch object from DB and attach `_has_child_diagram` flag."""
    from app.services import object_service

    obj = await object_service.get_object(db, object_id)
    if obj is None:
        return None
    obj._has_child_diagram = await _check_has_child_diagram(db, object_id)
    return obj


async def _get_diagram_connections(db: Any, diagram_id: UUID) -> list[Any]:
    """Return connections where both source and target are placed on the diagram."""
    from app.models.connection import Connection
    from app.models.diagram import DiagramObject

    # Sub-select: object_ids placed on this diagram.
    placed_ids_subq = select(DiagramObject.object_id).where(
        DiagramObject.diagram_id == diagram_id
    )
    result = await db.execute(
        select(Connection).where(
            Connection.source_id.in_(placed_ids_subq),
            Connection.target_id.in_(placed_ids_subq),
        )
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Tool implementations — READ tools (task 027)
# ---------------------------------------------------------------------------


@tool(
    name="read_object",
    description=(
        "Read basic facts about a model-level object: id, name, type, parent_id, "
        "has_child_diagram, technology_ids. Does NOT include description or coords."
    ),
    input_schema=ReadObjectInput,
    permission="diagram:read",
    permission_target="object",
    required_scope="agents:read",
    mutating=False,
)
async def read_object(args: ReadObjectInput, ctx: ToolContext) -> dict:
    """Returns projected object dict (basic projection)."""
    obj = await _get_object_with_child_flag(ctx.db, args.object_id)
    if obj is None:
        return {"error": "object_not_found", "object_id": str(args.object_id)}
    return _project_object_basic(obj)


@tool(
    name="read_object_full",
    description=(
        "Read full object info: basic fields + plain-text description, tags, owner, "
        "created_at, updated_at. HTML is never included."
    ),
    input_schema=ReadObjectFullInput,
    permission="diagram:read",
    permission_target="object",
    required_scope="agents:read",
    mutating=False,
)
async def read_object_full(args: ReadObjectFullInput, ctx: ToolContext) -> dict:
    """Returns projected object dict with description (plain text) and metadata."""
    obj = await _get_object_with_child_flag(ctx.db, args.object_id)
    if obj is None:
        return {"error": "object_not_found", "object_id": str(args.object_id)}
    return _project_object_full(obj)


@tool(
    name="read_connection",
    description=(
        "Read a connection's basic projection: id, source_id, target_id, label, "
        "technology_ids (protocol_ids), direction."
    ),
    input_schema=ReadConnectionInput,
    permission="diagram:read",
    permission_target="connection",
    required_scope="agents:read",
    mutating=False,
)
async def read_connection(args: ReadConnectionInput, ctx: ToolContext) -> dict:
    """Returns projected connection dict."""
    from app.services import connection_service

    conn = await connection_service.get_connection(ctx.db, args.connection_id)
    if conn is None:
        return {"error": "connection_not_found", "connection_id": str(args.connection_id)}
    return _project_connection(conn)


@tool(
    name="dependencies",
    description=(
        "Return upstream and downstream connections for an object. "
        "depth=1 returns direct neighbors only (Phase 1 recommended). "
        "depth>1 walks further but use carefully — results may be large."
    ),
    input_schema=DependenciesInput,
    permission="diagram:read",
    permission_target="object",
    required_scope="agents:read",
    mutating=False,
)
async def dependencies(args: DependenciesInput, ctx: ToolContext) -> dict:
    """Returns {upstream: [...projected_connections], downstream: [...projected_connections]}.

    Phase 1: only direct neighbors (depth=1) are fully supported.
    depth>1 performs iterative BFS but may be slow on large graphs.
    """
    from app.services import object_service

    if args.depth == 1:
        deps = await object_service.get_dependencies(ctx.db, args.object_id)
        return {
            "upstream": [_project_connection(c) for c in deps["upstream"]],
            "downstream": [_project_connection(c) for c in deps["downstream"]],
        }

    # Multi-hop BFS (depth > 1) — walk outward iteratively.
    visited_objects: set[UUID] = {args.object_id}
    frontier: set[UUID] = {args.object_id}
    all_upstream: list[dict] = []
    all_downstream: list[dict] = []
    seen_conn_ids: set[UUID] = set()

    for _ in range(args.depth):
        next_frontier: set[UUID] = set()
        for oid in frontier:
            deps = await object_service.get_dependencies(ctx.db, oid)
            for c in deps["upstream"]:
                if c.id not in seen_conn_ids:
                    seen_conn_ids.add(c.id)
                    all_upstream.append(_project_connection(c))
                if c.source_id not in visited_objects:
                    next_frontier.add(c.source_id)
                    visited_objects.add(c.source_id)
            for c in deps["downstream"]:
                if c.id not in seen_conn_ids:
                    seen_conn_ids.add(c.id)
                    all_downstream.append(_project_connection(c))
                if c.target_id not in visited_objects:
                    next_frontier.add(c.target_id)
                    visited_objects.add(c.target_id)
        frontier = next_frontier
        if not frontier:
            break

    return {"upstream": all_upstream, "downstream": all_downstream}


@tool(
    name="list_objects",
    description=(
        "List workspace objects. Optional filters: types (list of type strings), "
        "parent_id. Results paginated at limit (max 200). "
        "Returns {items: [...], next_cursor: str|None}."
    ),
    input_schema=ListObjectsInput,
    permission="workspace:read",
    permission_target="workspace",
    required_scope="agents:read",
    mutating=False,
)
async def list_objects(args: ListObjectsInput, ctx: ToolContext) -> dict:
    """Returns {items: [...basic_projections], next_cursor: str|None}."""
    from app.models.diagram import Diagram
    from app.models.object import ModelObject

    offset = _cursor_decode(args.cursor)

    query = select(ModelObject).where(
        ModelObject.draft_id.is_(None),
        ModelObject.workspace_id == ctx.workspace_id,
    )
    if args.types:
        query = query.where(ModelObject.type.in_(args.types))
    if args.parent_id is not None:
        query = query.where(ModelObject.parent_id == args.parent_id)

    # Fetch one extra to detect next page.
    query = query.order_by(ModelObject.name).offset(offset).limit(args.limit + 1)
    result = await ctx.db.execute(query)
    rows = list(result.scalars().all())

    has_more = len(rows) > args.limit
    page = rows[: args.limit]

    # Batch-check child diagrams: find which object_ids have a child diagram.
    page_ids = [obj.id for obj in page]
    child_diagram_set: set[UUID] = set()
    if page_ids:
        child_result = await ctx.db.execute(
            select(Diagram.scope_object_id).where(
                Diagram.scope_object_id.in_(page_ids)
            )
        )
        child_diagram_set = {row[0] for row in child_result.all() if row[0]}

    items = []
    for obj in page:
        obj._has_child_diagram = obj.id in child_diagram_set
        items.append(_project_object_basic(obj))

    next_cursor = _cursor_encode(offset + args.limit) if has_more else None
    return {"items": items, "next_cursor": next_cursor}


@tool(
    name="list_diagrams",
    description=(
        "List diagrams in the workspace. Optional filters: level ('L1'–'L4'), "
        "parent_object_id (scope_object_id). Paginated. "
        "Returns {items: [...diagram_meta], next_cursor: str|None}."
    ),
    input_schema=ListDiagramsInput,
    permission="workspace:read",
    permission_target="workspace",
    required_scope="agents:read",
    mutating=False,
)
async def list_diagrams(args: ListDiagramsInput, ctx: ToolContext) -> dict:
    """Returns {items: [...diagram_meta], next_cursor: str|None}."""
    from app.models.diagram import Diagram, DiagramType

    offset = _cursor_decode(args.cursor)

    query = select(Diagram).where(
        Diagram.workspace_id == ctx.workspace_id,
        Diagram.draft_id.is_(None),
    )

    if args.parent_object_id is not None:
        query = query.where(Diagram.scope_object_id == args.parent_object_id)

    if args.level:
        # Map L1/L2/L3/L4 → diagram types that correspond.
        # L1 = system_landscape / system_context
        # L2 = container
        # L3 = component
        # L4 = custom (fine-grained)
        _level_to_types: dict[str, list[str]] = {
            "L1": [DiagramType.SYSTEM_LANDSCAPE.value, DiagramType.SYSTEM_CONTEXT.value],
            "L2": [DiagramType.CONTAINER.value],
            "L3": [DiagramType.COMPONENT.value],
            "L4": [DiagramType.CUSTOM.value],
        }
        allowed_types = _level_to_types.get(args.level.upper(), [])
        if allowed_types:
            query = query.where(Diagram.type.in_(allowed_types))

    query = query.order_by(Diagram.name).offset(offset).limit(args.limit + 1)
    result = await ctx.db.execute(query)
    rows = list(result.scalars().all())

    has_more = len(rows) > args.limit
    page = rows[: args.limit]

    items = [_project_diagram_meta(d) for d in page]
    next_cursor = _cursor_encode(offset + args.limit) if has_more else None
    return {"items": items, "next_cursor": next_cursor}


@tool(
    name="read_diagram",
    description=(
        "Read diagram metadata including all placements (object_id, x, y, width, height) "
        "and connections between placed objects. Placements truncated at 50."
    ),
    input_schema=ReadDiagramInput,
    permission="diagram:read",
    permission_target="diagram",
    required_scope="agents:read",
    mutating=False,
)
async def read_diagram(args: ReadDiagramInput, ctx: ToolContext) -> dict:
    """Returns metadata + placements (up to 50) + connections."""
    from app.services import diagram_service

    diagram = await diagram_service.get_diagram(ctx.db, args.diagram_id)
    if diagram is None:
        return {"error": "diagram_not_found", "diagram_id": str(args.diagram_id)}

    placements_raw = diagram.objects  # loaded via selectinload in get_diagram
    total_placements = len(placements_raw)

    # Truncate placements at 50 per spec §4.8.
    placements_page = placements_raw[:50]

    placements = [
        {
            "object_id": str(p.object_id),
            "x": p.position_x,
            "y": p.position_y,
            "width": p.width,
            "height": p.height,
        }
        for p in placements_page
    ]
    if total_placements > 50:
        placements.append({"_truncated": total_placements - 50})

    # Connections between placed objects.
    conns = await _get_diagram_connections(ctx.db, args.diagram_id)
    connections = [_project_connection(c) for c in conns]

    meta = _project_diagram_meta(diagram)
    meta["placements"] = placements
    meta["connections"] = connections
    return meta


@tool(
    name="read_canvas_state",
    description=(
        "Read canvas state optimised for diagram-agent verify-after-mutate. "
        "Returns {placements: [{object_id, x, y, w, h, type, name}], connections: [...]}. "
        "No description-html. No long fields."
    ),
    input_schema=ReadCanvasStateInput,
    permission="diagram:read",
    permission_target="diagram",
    required_scope="agents:read",
    mutating=False,
)
async def read_canvas_state(args: ReadCanvasStateInput, ctx: ToolContext) -> dict:
    """Like read_diagram but minimal — for post-mutate verification loops."""
    from app.models.object import ModelObject
    from app.services import diagram_service

    diagram = await diagram_service.get_diagram(ctx.db, args.diagram_id)
    if diagram is None:
        return {"error": "diagram_not_found", "diagram_id": str(args.diagram_id)}

    placements_raw = diagram.objects[:50]

    # Resolve object names and types in batch.
    obj_ids = [p.object_id for p in placements_raw]
    obj_map: dict[UUID, Any] = {}
    if obj_ids:
        obj_result = await ctx.db.execute(
            select(ModelObject).where(ModelObject.id.in_(obj_ids))
        )
        for obj in obj_result.scalars().all():
            obj_map[obj.id] = obj

    placements = []
    for p in placements_raw:
        obj = obj_map.get(p.object_id)
        entry: dict[str, Any] = {
            "object_id": str(p.object_id),
            "x": p.position_x,
            "y": p.position_y,
            "w": p.width,
            "h": p.height,
        }
        if obj:
            entry["name"] = obj.name
            entry["type"] = obj.type.value if hasattr(obj.type, "value") else str(obj.type)
        placements.append(entry)

    conns = await _get_diagram_connections(ctx.db, args.diagram_id)
    connections = [_project_connection(c) for c in conns]

    return {
        "diagram_id": str(args.diagram_id),
        "placements": placements,
        "connections": connections,
    }


@tool(
    name="list_child_diagrams",
    description=(
        "Return diagrams linked to an object as child (drill-down) diagrams. "
        "Empty list if the object has no child diagram."
    ),
    input_schema=ListChildDiagramsInput,
    permission="diagram:read",
    permission_target="object",
    required_scope="agents:read",
    mutating=False,
)
async def list_child_diagrams(args: ListChildDiagramsInput, ctx: ToolContext) -> dict:
    """Returns {items: [...diagram_meta]}."""
    from app.services import diagram_service

    diagrams = await diagram_service.get_diagrams(
        ctx.db, scope_object_id=args.object_id, workspace_id=ctx.workspace_id
    )
    return {"items": [_project_diagram_meta(d) for d in diagrams]}


@tool(
    name="read_child_diagram",
    description=(
        "Read a child (drill-down) diagram. Equivalent to read_diagram but signals "
        "intent — caller expects this diagram to be a child of a parent object. "
        "Phase 1: simple delegation to read_diagram logic."
    ),
    input_schema=ReadChildDiagramInput,
    permission="diagram:read",
    permission_target="diagram",
    required_scope="agents:read",
    mutating=False,
)
async def read_child_diagram(args: ReadChildDiagramInput, ctx: ToolContext) -> dict:
    """Phase 1: delegates to read_diagram with same diagram_id."""
    # read_diagram is a Tool instance after @tool decoration; call its handler directly.
    return await read_diagram.handler(
        ReadDiagramInput(diagram_id=args.diagram_id), ctx
    )


# ---------------------------------------------------------------------------
# Write-tool helpers (coercion, projections)
# ---------------------------------------------------------------------------


def _coerce_object_type(value: str) -> Any:
    """Map a string into the ObjectType enum, raising ToolDenied on failure."""
    from app.models.object import ObjectType

    try:
        return ObjectType(value)
    except ValueError as exc:
        valid = sorted(t.value for t in ObjectType)
        raise ToolDenied(
            f"unknown object type {value!r}; valid: {valid}"
        ) from exc


def _coerce_object_status(value: str | None) -> Any:
    """Map a status string into the ObjectStatus enum (optional).

    Accepts a few common LLM-friendly aliases ('planned', 'in-development') and
    falls back to ObjectStatus.LIVE on totally unknown values rather than raising.
    """
    if value is None:
        return None
    from app.models.object import ObjectStatus

    aliases = {
        "planned": ObjectStatus.FUTURE,
        "future": ObjectStatus.FUTURE,
        "in-development": ObjectStatus.FUTURE,
        "in_development": ObjectStatus.FUTURE,
        "live": ObjectStatus.LIVE,
        "active": ObjectStatus.LIVE,
        "deprecated": ObjectStatus.DEPRECATED,
        "removed": ObjectStatus.REMOVED,
    }
    if value in aliases:
        return aliases[value]
    try:
        return ObjectStatus(value)
    except ValueError:
        return ObjectStatus.LIVE


def _coerce_connection_direction(value: str) -> Any:
    """Map an agent-friendly direction onto ConnectionDirection."""
    from app.models.connection import ConnectionDirection

    norm = (value or "").lower()
    if norm in ("outgoing", "unidirectional", "out"):
        return ConnectionDirection.UNIDIRECTIONAL
    if norm in ("bidirectional", "both", "two-way"):
        return ConnectionDirection.BIDIRECTIONAL
    if norm in ("undirected", "neither", "none"):
        return ConnectionDirection.UNDIRECTED
    try:
        return ConnectionDirection(norm)
    except ValueError:
        return ConnectionDirection.UNIDIRECTIONAL


# ---------------------------------------------------------------------------
# Write-tool implementations (task agent-core-mvp-029)
# ---------------------------------------------------------------------------


@tool(
    name="create_object",
    description=(
        "Create a NEW model-level object. Object exists in the workspace model "
        "but does NOT appear on any diagram until you call place_on_diagram. "
        "ALWAYS call search_existing_objects BEFORE this to avoid duplicates."
    ),
    input_schema=CreateObjectInput,
    permission="diagram:edit",
    permission_target="workspace",
    required_scope="agents:write",
    mutating=True,
)
async def create_object(args: CreateObjectInput, ctx: ToolContext) -> dict:
    """Create a new model-level object. Returns action='object.created'."""
    from app.schemas.object import ObjectCreate
    from app.services import object_service

    obj_type = _coerce_object_type(args.type)
    status = _coerce_object_status(args.status)

    payload: dict[str, Any] = {
        "name": args.name,
        "type": obj_type,
        "parent_id": args.parent_id,
        "description": args.description,
        "technology_ids": list(args.technology_ids) if args.technology_ids else None,
        "tags": list(args.tags) if args.tags else None,
        "owner_team": getattr(args, "owner_team", None),
    }
    if status is not None:
        payload["status"] = status

    create_data = ObjectCreate(**{k: v for k, v in payload.items() if v is not None})

    obj = await object_service.create_object(
        ctx.db,
        create_data,
        draft_id=ctx.active_draft_id,
        workspace_id=ctx.workspace_id,
    )

    record: dict[str, Any] = {
        "action": "object.created",
        "target_type": "object",
        "target_id": obj.id,
        "name": obj.name,
        "preview": short_preview("Created", "object", obj.name),
    }
    record.update(_project_object_basic(obj))
    return record


@tool(
    name="update_object",
    description=(
        "Update fields on an existing model object. patch is partial — only "
        "provided keys are changed."
    ),
    input_schema=UpdateObjectInput,
    permission="diagram:edit",
    permission_target="object",
    required_scope="agents:write",
    mutating=True,
)
async def update_object(args: UpdateObjectInput, ctx: ToolContext) -> dict:
    """Apply a partial patch to an object."""
    from app.schemas.object import ObjectUpdate
    from app.services import object_service

    obj = await object_service.get_object(ctx.db, args.object_id)
    if obj is None:
        raise ToolDenied(f"object {args.object_id} not found")

    patch = dict(args.patch or {})
    if "type" in patch and patch["type"] is not None:
        patch["type"] = _coerce_object_type(patch["type"])
    if "status" in patch and patch["status"] is not None:
        patch["status"] = _coerce_object_status(patch["status"])

    update_data = ObjectUpdate(**patch)
    updated = await object_service.update_object(ctx.db, obj, update_data)

    record: dict[str, Any] = {
        "action": "object.updated",
        "target_type": "object",
        "target_id": updated.id,
        "name": updated.name,
        "preview": short_preview("Updated", "object", updated.name),
    }
    record.update(_project_object_basic(updated))
    return record


@tool(
    name="delete_object",
    description=(
        "Delete a model object. Will cascade to its connections + placements. "
        "First call without confirmed=True returns a preview with impact. "
        "Call again with confirmed=True to execute."
    ),
    input_schema=DeleteObjectInput,
    permission="diagram:manage",
    permission_target="object",
    required_scope="agents:admin",
    mutating=True,
    deprecates_model=True,
    needs_confirmed_gate=True,
)
async def delete_object(args: DeleteObjectInput, ctx: ToolContext) -> dict:
    """Two-step delete: preview without confirmed=True, then execute."""
    from app.services import diagram_service, object_service

    obj = await object_service.get_object(ctx.db, args.object_id)
    if obj is None:
        raise ToolDenied(f"object {args.object_id} not found")

    if not args.confirmed:
        deps = await object_service.get_dependencies(ctx.db, args.object_id)
        connections_count = len(deps.get("upstream", [])) + len(deps.get("downstream", []))
        placement_diagrams = await diagram_service.get_diagrams_containing_object(
            ctx.db, args.object_id
        )
        placement_count = len(placement_diagrams)
        child_diagrams = await diagram_service.get_diagrams(
            ctx.db,
            scope_object_id=args.object_id,
            workspace_id=ctx.workspace_id,
        )
        impact = {
            "will_delete": 1,
            "will_orphan_connections": connections_count,
            "will_orphan_placements": placement_count,
            "child_diagrams": [str(d.id) for d in child_diagrams],
        }
        return {
            "status": "awaiting_confirmation",
            "preview": (
                f"Will delete object {obj.name} "
                f"({connections_count} connections, {placement_count} placements)"
            ),
            "impact": impact,
            "target_id": obj.id,
            "name": obj.name,
        }

    name = obj.name
    target_id = obj.id
    await object_service.delete_object(ctx.db, obj)
    return {
        "action": "object.deleted",
        "target_type": "object",
        "target_id": target_id,
        "name": name,
        "preview": short_preview("Deleted", "object", name),
    }


@tool(
    name="create_connection",
    description="Create a new model-level connection between two objects.",
    input_schema=CreateConnectionInput,
    permission="diagram:edit",
    permission_target="workspace",
    required_scope="agents:write",
    mutating=True,
)
async def create_connection(args: CreateConnectionInput, ctx: ToolContext) -> dict:
    """Create a connection. Returns action='connection.created'."""
    from app.schemas.connection import ConnectionCreate
    from app.services import connection_service

    direction = _coerce_connection_direction(args.direction)
    create_data = ConnectionCreate(
        source_id=args.source_object_id,
        target_id=args.target_object_id,
        label=args.label,
        protocol_ids=list(args.technology_ids) if args.technology_ids else None,
        direction=direction,
    )

    conn = await connection_service.create_connection(
        ctx.db, create_data, draft_id=ctx.active_draft_id
    )

    record: dict[str, Any] = {
        "action": "connection.created",
        "target_type": "connection",
        "name": conn.label or "",
        "preview": short_preview("Created", "connection", conn.label or ""),
    }
    record.update(_project_connection(conn))
    # The connection projection sets target_id = conn.target_id (the destination
    # object). For agent applied_changes, target_id must point at the connection
    # itself — overwrite after the projection merge.
    record["target_id"] = conn.id
    return record


@tool(
    name="update_connection",
    description="Apply a partial patch to an existing connection's fields.",
    input_schema=UpdateConnectionInput,
    permission="diagram:edit",
    permission_target="connection",
    required_scope="agents:write",
    mutating=True,
)
async def update_connection(args: UpdateConnectionInput, ctx: ToolContext) -> dict:
    """Apply patch to an existing connection."""
    from app.schemas.connection import ConnectionUpdate
    from app.services import connection_service

    conn = await connection_service.get_connection(ctx.db, args.connection_id)
    if conn is None:
        raise ToolDenied(f"connection {args.connection_id} not found")

    patch = dict(args.patch or {})
    if "direction" in patch and isinstance(patch["direction"], str):
        patch["direction"] = _coerce_connection_direction(patch["direction"])
    if "technology_ids" in patch and "protocol_ids" not in patch:
        patch["protocol_ids"] = patch.pop("technology_ids")

    update_data = ConnectionUpdate(**patch)
    updated = await connection_service.update_connection(ctx.db, conn, update_data)

    record: dict[str, Any] = {
        "action": "connection.updated",
        "target_type": "connection",
        "name": updated.label or "",
        "preview": short_preview("Updated", "connection", updated.label or ""),
    }
    record.update(_project_connection(updated))
    record["target_id"] = updated.id
    return record


@tool(
    name="delete_connection",
    description=(
        "Delete a connection. First call without confirmed returns preview. "
        "Re-call with confirmed=True to execute."
    ),
    input_schema=DeleteConnectionInput,
    permission="diagram:manage",
    permission_target="connection",
    required_scope="agents:admin",
    mutating=True,
    deprecates_model=True,
    needs_confirmed_gate=True,
)
async def delete_connection(args: DeleteConnectionInput, ctx: ToolContext) -> dict:
    """Two-step delete with preview gate."""
    from app.services import connection_service

    conn = await connection_service.get_connection(ctx.db, args.connection_id)
    if conn is None:
        raise ToolDenied(f"connection {args.connection_id} not found")

    if not args.confirmed:
        return {
            "status": "awaiting_confirmation",
            "preview": (
                f"Will delete connection {conn.label or conn.id} "
                f"(source={conn.source_id} -> target={conn.target_id})"
            ),
            "impact": {
                "will_delete": 1,
                "source_id": str(conn.source_id),
                "target_id": str(conn.target_id),
            },
            "target_id": conn.id,
            "name": conn.label or "",
        }

    label = conn.label or ""
    target_id = conn.id
    await connection_service.delete_connection(ctx.db, conn)
    return {
        "action": "connection.deleted",
        "target_type": "connection",
        "target_id": target_id,
        "name": label,
        "preview": short_preview("Deleted", "connection", label),
    }
