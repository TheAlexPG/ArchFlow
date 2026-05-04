"""View-layer tools — placements, diagram CRUD, hierarchy.

Spec: §4.5 Write tools (View layer + Diagrams + Hierarchy + Layout).

These tools operate on per-diagram positions and on the diagram model itself.
Model-layer objects must already exist (use create_object for that).

Read tools (read_diagram, read_canvas_state, list_child_diagrams, read_child_diagram)
are implemented in model_tools.py (task agent-core-mvp-027).

Layout-engine integration: place_on_diagram defers to
``app.agents.layout.engine.incremental_place`` when x/y are absent. Until
task agent-core-mvp-053 lands, ``incremental_place`` raises
``NotImplementedError`` — we catch that and fall back to a simple
16-aligned grid heuristic that scans for a free cell starting at (64, 64).
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.agents.errors import ToolDenied
from app.agents.tools.base import Tool, ToolContext, register_tool, short_preview, tool

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


_DEFAULT_NODE_WIDTH = 220
_DEFAULT_NODE_HEIGHT = 120
_GRID_STEP = 16
_GRID_ORIGIN_X = 64
_GRID_ORIGIN_Y = 64
_GRID_BAND_WIDTH = _DEFAULT_NODE_WIDTH + 60   # column spacing
_GRID_BAND_HEIGHT = _DEFAULT_NODE_HEIGHT + 60  # row spacing
_GRID_MAX_SCAN = 500  # max candidates before giving up


# C4 level → DiagramType mapping. Phase 1 mapping is best-effort:
#   L1 → SYSTEM_CONTEXT
#   L2 → CONTAINER
#   L3 → COMPONENT
#   L4 → CUSTOM (we don't have a finer-grained C4 type yet)
_LEVEL_TO_DIAGRAM_TYPE: dict[str, str] = {
    "L1": "system_context",
    "L2": "container",
    "L3": "component",
    "L4": "custom",
}


# ---------------------------------------------------------------------------
# Input schemas (write-side only — read schemas live in model_tools.py)
# ---------------------------------------------------------------------------


class PlaceOnDiagramInput(BaseModel):
    """Input for place_on_diagram tool."""

    diagram_id: UUID
    object_id: UUID
    x: float | None = None
    y: float | None = None
    width: float | None = None
    height: float | None = None


class MoveOnDiagramInput(BaseModel):
    """Input for move_on_diagram tool."""

    diagram_id: UUID
    object_id: UUID
    x: float
    y: float


class UnplaceFromDiagramInput(BaseModel):
    """Input for unplace_from_diagram tool."""

    diagram_id: UUID
    object_id: UUID
    confirmed: bool = False
    reason: str = Field(
        ...,
        min_length=10,
        max_length=1000,
        description=(
            "REQUIRED. ≥10 chars. Justify why removing this placement is "
            "correct. The destructive-op reviewer LLM rejects vague "
            "reasons. Cite specifics: 'duplicate placement on same "
            "diagram', 'user asked to remove X from this view', "
            "'placement belongs on child diagram, not here'."
        ),
    )


class CreateDiagramInput(BaseModel):
    """Input for create_diagram tool."""

    name: str = Field(..., min_length=1, max_length=255)
    level: str  # 'L1' | 'L2' | 'L3' | 'L4'
    parent_object_id: UUID | None = None
    description: str | None = None


class UpdateDiagramInput(BaseModel):
    """Input for update_diagram tool."""

    diagram_id: UUID
    patch: dict[str, Any]


class DeleteDiagramInput(BaseModel):
    """Input for delete_diagram tool."""

    diagram_id: UUID
    confirmed: bool = False
    reason: str = Field(
        ...,
        min_length=10,
        max_length=1000,
        description=(
            "REQUIRED. ≥10 chars. Justify why deleting this diagram is "
            "correct. The destructive-op reviewer LLM rejects vague "
            "reasons. Cite specifics: 'duplicate of diagram X for the "
            "same scope object', 'user asked to drop empty draft scratch "
            "diagram', 'replaced by new layout in diagram Y'."
        ),
    )


class LinkObjectToChildDiagramInput(BaseModel):
    """Input for link_object_to_child_diagram tool."""

    object_id: UUID
    child_diagram_id: UUID


class UnlinkObjectFromChildDiagramInput(BaseModel):
    """Input for unlink_object_from_child_diagram tool."""

    object_id: UUID


class CreateChildDiagramForObjectInput(BaseModel):
    """Input for create_child_diagram_for_object composite tool."""

    object_id: UUID
    name: str | None = None
    level: str | None = None


class AutoLayoutDiagramInput(BaseModel):
    """Input for auto_layout_diagram tool."""

    diagram_id: UUID
    scope: str = "new_only"  # 'new_only' | 'all'
    dry_run: bool = False
    confirmed: bool = False  # required for scope='all'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _coerce_diagram_type_from_level(level: str) -> Any:
    """Translate 'L1'/'L2'/'L3'/'L4' into the corresponding DiagramType enum."""
    from app.models.diagram import DiagramType

    norm = (level or "").upper()
    type_value = _LEVEL_TO_DIAGRAM_TYPE.get(norm)
    if type_value is None:
        raise ToolDenied(
            f"unknown level {level!r}; valid: {sorted(_LEVEL_TO_DIAGRAM_TYPE)}"
        )
    return DiagramType(type_value)


def _diagram_type_to_level(value: Any) -> str:
    """Reverse mapping for diagnostics + projections."""
    raw = value.value if hasattr(value, "value") else str(value)
    reverse = {v: k for k, v in _LEVEL_TO_DIAGRAM_TYPE.items()}
    # system_landscape is also L1 even though we don't emit it ourselves.
    reverse.setdefault("system_landscape", "L1")
    return reverse.get(raw, "L1")


def _next_level(current: str | None) -> str:
    """Return the next-deeper C4 level. Defaults to L2 when current is unknown."""
    order = ["L1", "L2", "L3", "L4"]
    if current and current.upper() in order:
        idx = order.index(current.upper())
        return order[min(idx + 1, len(order) - 1)]
    return "L2"


def _diagram_meta(d: Any) -> dict:
    type_value = d.type.value if hasattr(d.type, "value") else str(d.type)
    return {
        "id": str(d.id),
        "name": d.name,
        "type": type_value,
        "level": _diagram_type_to_level(d.type),
        "description": d.description,
        "scope_object_id": str(d.scope_object_id) if d.scope_object_id else None,
    }


# ---------------------------------------------------------------------------
# Layout helpers
# ---------------------------------------------------------------------------


def _grid_fallback(
    existing: list[Any], width: float, height: float
) -> tuple[float, float]:
    """Find next free 16-aligned cell starting at (64, 64), scanning row-major.

    A candidate cell is "free" when no existing placement's bounding box overlaps
    with the candidate (width × height) box. Used when the layout engine is not
    available yet (task 053/054).
    """
    boxes: list[tuple[float, float, float, float]] = []
    for p in existing:
        ex_w = p.width if p.width is not None else _DEFAULT_NODE_WIDTH
        ex_h = p.height if p.height is not None else _DEFAULT_NODE_HEIGHT
        boxes.append(
            (float(p.position_x), float(p.position_y), float(ex_w), float(ex_h))
        )

    def overlaps(x: float, y: float) -> bool:
        for bx, by, bw, bh in boxes:
            if x < bx + bw and x + width > bx and y < by + bh and y + height > by:
                return True
        return False

    def snap(v: float) -> float:
        return float(int(v / _GRID_STEP) * _GRID_STEP)

    candidate_count = 0
    row = 0
    while candidate_count < _GRID_MAX_SCAN:
        col = 0
        while candidate_count < _GRID_MAX_SCAN:
            x = snap(_GRID_ORIGIN_X + col * _GRID_BAND_WIDTH)
            y = snap(_GRID_ORIGIN_Y + row * _GRID_BAND_HEIGHT)
            if not overlaps(x, y):
                return x, y
            candidate_count += 1
            col += 1
            if col > 20:
                break
        row += 1
        if row > 50:
            break

    if boxes:
        max_right = max(bx + bw for bx, _, bw, _ in boxes)
        return float(int(max_right / _GRID_STEP) * _GRID_STEP) + _GRID_STEP, float(_GRID_ORIGIN_Y)
    return float(_GRID_ORIGIN_X), float(_GRID_ORIGIN_Y)


async def _resolve_position(
    ctx: ToolContext,
    diagram_id: UUID,
    object_id: UUID,
    width: float,
    height: float,
) -> tuple[float, float]:
    """Try the layout engine; fall back to grid heuristic on NotImplementedError."""
    from app.agents.layout import engine as layout_engine
    from app.services import diagram_service

    try:
        result = await layout_engine.incremental_place(
            diagram_id=diagram_id, object_id=object_id, db=ctx.db
        )
        # Engine returns a PlacementResult dataclass (x, y, w, h). Honor the
        # position only — width/height come from the tool args. Earlier the
        # engine returned a tuple and we indexed [0]/[1]; the dataclass
        # rewrite broke that with "PlacementResult is not subscriptable".
        return float(result.x), float(result.y)
    except NotImplementedError:
        logger.debug(
            "layout engine not yet implemented (task 053); using grid fallback "
            "for diagram=%s object=%s",
            diagram_id,
            object_id,
        )
    except Exception:
        logger.exception(
            "layout engine failed; falling back to grid for diagram=%s object=%s",
            diagram_id,
            object_id,
        )

    placements = await diagram_service.get_diagram_objects(ctx.db, diagram_id)
    return _grid_fallback(placements, width, height)


# ---------------------------------------------------------------------------
# Place / Move / Unplace
# ---------------------------------------------------------------------------


@tool(
    name="place_on_diagram",
    description=(
        "Place a model object on a diagram. If x/y absent, use auto-layout to find "
        "a non-overlapping position. The model object must already exist (call "
        "create_object first). This is a VIEW-layer operation, not a model creation."
    ),
    input_schema=PlaceOnDiagramInput,
    permission="diagram:edit",
    permission_target="diagram",
    required_scope="agents:write",
    mutating=True,
)
async def place_on_diagram(args: PlaceOnDiagramInput, ctx: ToolContext) -> dict:
    """Create a DiagramObject row at the given (or computed) position.

    Idempotent: if the (diagram_id, object_id) pair is already placed,
    returns the existing placement instead of raising a UniqueViolation.
    Without this guard, a re-delegated diagram-agent that tried to place
    the same object twice would crash the entire transaction (cascade
    rollback dropped the agent_chat_session row, the runtime then died
    with a ForeignKeyViolationError on the next message INSERT).
    """
    from app.schemas.diagram import DiagramObjectCreate
    from app.services import diagram_service, object_service

    obj = await object_service.get_object(ctx.db, args.object_id)
    if obj is None:
        raise ToolDenied(f"object {args.object_id} not found")

    # ── Dedupe pre-check ──────────────────────────────────────────────
    existing_placements = await diagram_service.get_diagram_objects(
        ctx.db, args.diagram_id
    )
    reused = next(
        (p for p in existing_placements if p.object_id == args.object_id), None
    )
    if reused is not None:
        return {
            "action": "object.placed",  # keep verb so UI pill renders
            "status": "reused",
            "target_type": "object",
            "target_id": args.object_id,
            "diagram_id": args.diagram_id,
            "name": obj.name,
            "placement": {
                "x": reused.position_x,
                "y": reused.position_y,
                "w": reused.width,
                "h": reused.height,
            },
            "preview": short_preview("Already placed", "object", obj.name),
        }

    width = float(args.width) if args.width is not None else float(_DEFAULT_NODE_WIDTH)
    height = float(args.height) if args.height is not None else float(_DEFAULT_NODE_HEIGHT)

    if args.x is not None and args.y is not None:
        x, y = float(args.x), float(args.y)
    else:
        x, y = await _resolve_position(
            ctx, args.diagram_id, args.object_id, width, height
        )

    placement = await diagram_service.add_object_to_diagram(
        ctx.db,
        args.diagram_id,
        DiagramObjectCreate(
            object_id=args.object_id,
            position_x=x,
            position_y=y,
            width=width,
            height=height,
        ),
    )
    from app.agents.tools._handle_resolver import (
        refresh_handles_for_object_placement,
    )
    from app.agents.tools._realtime import (
        publish_connection_event,
        publish_placement_event,
    )

    await publish_placement_event(
        db=ctx.db,
        diagram_id=args.diagram_id,
        placement=placement,
        event_type="diagram_object.added",
        draft_id=ctx.active_draft_id,
    )
    # Now that a new placement landed, walk every connection touching this
    # object on this diagram and fill in null handles using the geometry
    # of both endpoints. Each updated connection emits its own WS event so
    # open canvases redraw the edge from the right side.
    if ctx.active_draft_id is None:
        updated_connections = await refresh_handles_for_object_placement(
            db=ctx.db,
            diagram_id=args.diagram_id,
            object_id=args.object_id,
        )
        for conn in updated_connections:
            await publish_connection_event(
                db=ctx.db,
                conn=conn,
                event_type="connection.updated",
                draft_id=getattr(conn, "draft_id", None),
            )

    return {
        "action": "object.placed",
        "target_type": "object",
        "target_id": args.object_id,
        "diagram_id": args.diagram_id,
        "name": obj.name,
        "placement": {
            "x": placement.position_x,
            "y": placement.position_y,
            "w": placement.width,
            "h": placement.height,
        },
        "preview": short_preview("Placed", "object", obj.name),
    }


@tool(
    name="move_on_diagram",
    description="Move an already-placed object to new coordinates on a diagram.",
    input_schema=MoveOnDiagramInput,
    permission="diagram:edit",
    permission_target="diagram",
    required_scope="agents:write",
    mutating=True,
)
async def move_on_diagram(args: MoveOnDiagramInput, ctx: ToolContext) -> dict:
    """Update DiagramObject (x, y) coordinates."""
    from app.schemas.diagram import DiagramObjectUpdate
    from app.services import diagram_service

    placement = await diagram_service.update_diagram_object(
        ctx.db,
        args.diagram_id,
        args.object_id,
        DiagramObjectUpdate(position_x=float(args.x), position_y=float(args.y)),
    )
    if placement is None:
        raise ToolDenied(
            f"object {args.object_id} is not placed on diagram {args.diagram_id}"
        )
    from app.agents.tools._handle_resolver import (
        refresh_handles_for_object_placement,
    )
    from app.agents.tools._realtime import (
        publish_connection_event,
        publish_placement_event,
    )

    await publish_placement_event(
        db=ctx.db,
        diagram_id=args.diagram_id,
        placement=placement,
        event_type="diagram_object.updated",
        draft_id=ctx.active_draft_id,
    )
    if ctx.active_draft_id is None:
        updated_connections = await refresh_handles_for_object_placement(
            db=ctx.db,
            diagram_id=args.diagram_id,
            object_id=args.object_id,
        )
        for conn in updated_connections:
            await publish_connection_event(
                db=ctx.db,
                conn=conn,
                event_type="connection.updated",
                draft_id=getattr(conn, "draft_id", None),
            )

    return {
        "action": "object.moved",
        "target_type": "object",
        "target_id": args.object_id,
        "diagram_id": args.diagram_id,
        "placement": {
            "x": placement.position_x,
            "y": placement.position_y,
            "w": placement.width,
            "h": placement.height,
        },
        "preview": (
            f"Moved object on diagram to ({placement.position_x},{placement.position_y})"
        ),
    }


@tool(
    name="unplace_from_diagram",
    description=(
        "Remove an object's visual placement from a diagram (does not delete the "
        "object). First call without confirmed=True returns a preview of orphaned "
        "connections on this diagram. Re-call with confirmed=True AND a `reason` "
        "(≥10 chars, specific) to execute. The reason is required and reviewed "
        "by an LLM — vague reasons get rejected."
    ),
    input_schema=UnplaceFromDiagramInput,
    permission="diagram:manage",
    permission_target="diagram",
    required_scope="agents:admin",
    mutating=True,
    deprecates_model=True,
    needs_confirmed_gate=True,
)
async def unplace_from_diagram(args: UnplaceFromDiagramInput, ctx: ToolContext) -> dict:
    """Two-step unplace with preview of impact on diagram-local connections."""
    from app.services import diagram_service, object_service

    if not args.confirmed:
        # Compute impact: connections from/to this object that are visible on
        # this diagram (i.e. both endpoints placed). Removing the placement
        # makes those connections invisible on the diagram.
        deps = await object_service.get_dependencies(ctx.db, args.object_id)
        placements = await diagram_service.get_diagram_objects(ctx.db, args.diagram_id)
        placed_ids = {p.object_id for p in placements}
        affected = 0
        for c in deps.get("upstream", []):
            if c.source_id in placed_ids and c.target_id in placed_ids:
                affected += 1
        for c in deps.get("downstream", []):
            if c.source_id in placed_ids and c.target_id in placed_ids:
                affected += 1

        return {
            "status": "awaiting_confirmation",
            "preview": (
                f"Will remove placement (orphans {affected} connections on this diagram)"
            ),
            "impact": {
                "will_orphan_connections_on_diagram": affected,
            },
            "target_id": args.object_id,
            "diagram_id": args.diagram_id,
        }

    # ── LLM destructive-op reviewer ────────────────────────────────────
    from app.agents.tools._destructive_review import review_destructive_op

    deps = await object_service.get_dependencies(ctx.db, args.object_id)
    placements = await diagram_service.get_diagram_objects(ctx.db, args.diagram_id)
    placed_ids = {p.object_id for p in placements}
    affected = sum(
        1 for c in deps.get("upstream", []) + deps.get("downstream", [])
        if c.source_id in placed_ids and c.target_id in placed_ids
    )
    impact = {
        "will_unplace": 1,
        "will_orphan_connections_on_diagram": affected,
    }
    verdict = await review_destructive_op(
        ctx=ctx,
        tool_name="unplace_from_diagram",
        args=args,
        impact=impact,
        reason=args.reason,
        target_summary=(
            f"placement of object {args.object_id} on diagram {args.diagram_id}"
        ),
    )
    if verdict.verdict == "REJECT":
        raise ToolDenied(
            f"destructive-op reviewer rejected: {verdict.rationale}"
        )

    removed = await diagram_service.remove_object_from_diagram(
        ctx.db, args.diagram_id, args.object_id
    )
    if not removed:
        raise ToolDenied(
            f"object {args.object_id} is not placed on diagram {args.diagram_id}"
        )
    from app.agents.tools._realtime import publish_placement_event

    await publish_placement_event(
        db=ctx.db,
        diagram_id=args.diagram_id,
        placement=None,
        event_type="diagram_object.removed",
        object_id=args.object_id,
        draft_id=ctx.active_draft_id,
    )

    return {
        "action": "object.unplaced",
        "target_type": "object",
        "target_id": args.object_id,
        "diagram_id": args.diagram_id,
        "preview": "Removed placement from diagram",
    }


# ---------------------------------------------------------------------------
# Diagram CRUD
# ---------------------------------------------------------------------------


@tool(
    name="create_diagram",
    description=(
        "Create a new diagram at the given C4 level (L1–L4) with optional parent "
        "object. Use this when the user wants a fresh canvas — not when adding "
        "an object to an existing diagram."
    ),
    input_schema=CreateDiagramInput,
    permission="diagram:manage",
    permission_target="workspace",
    required_scope="agents:write",
    mutating=True,
)
async def create_diagram(args: CreateDiagramInput, ctx: ToolContext) -> dict:
    """Create a Diagram row + return metadata."""
    from app.schemas.diagram import DiagramCreate
    from app.services import diagram_service

    diagram_type = _coerce_diagram_type_from_level(args.level)

    create_data = DiagramCreate(
        name=args.name,
        type=diagram_type,
        description=args.description,
        scope_object_id=args.parent_object_id,
    )

    diagram = await diagram_service.create_diagram(
        ctx.db, create_data, workspace_id=ctx.workspace_id
    )
    from app.agents.tools._realtime import publish_diagram_event

    publish_diagram_event(
        diagram=diagram,
        event_type="diagram.created",
        draft_id=ctx.active_draft_id,
    )

    record: dict[str, Any] = {
        "action": "diagram.created",
        "target_type": "diagram",
        "target_id": diagram.id,
        "name": diagram.name,
        "preview": short_preview("Created", "diagram", diagram.name),
    }
    record.update(_diagram_meta(diagram))
    return record


@tool(
    name="update_diagram",
    description="Apply a partial patch to a diagram's metadata (name, description, etc.).",
    input_schema=UpdateDiagramInput,
    permission="diagram:edit",
    permission_target="diagram",
    required_scope="agents:write",
    mutating=True,
)
async def update_diagram(args: UpdateDiagramInput, ctx: ToolContext) -> dict:
    """Update diagram metadata."""
    from app.schemas.diagram import DiagramUpdate
    from app.services import diagram_service

    diagram = await diagram_service.get_diagram(ctx.db, args.diagram_id)
    if diagram is None:
        raise ToolDenied(f"diagram {args.diagram_id} not found")

    patch = dict(args.patch or {})
    # Allow callers to pass 'level' as syntactic sugar for diagram type.
    if "level" in patch and "type" not in patch:
        patch["type"] = _coerce_diagram_type_from_level(patch.pop("level"))

    update_data = DiagramUpdate(**patch)
    updated = await diagram_service.update_diagram(ctx.db, diagram, update_data)
    from app.agents.tools._realtime import publish_diagram_event

    publish_diagram_event(
        diagram=updated,
        event_type="diagram.updated",
        draft_id=getattr(updated, "draft_id", None),
    )

    record: dict[str, Any] = {
        "action": "diagram.updated",
        "target_type": "diagram",
        "target_id": updated.id,
        "name": updated.name,
        "preview": short_preview("Updated", "diagram", updated.name),
    }
    record.update(_diagram_meta(updated))
    return record


@tool(
    name="delete_diagram",
    description=(
        "Delete a diagram. First call returns impact preview (placements + "
        "child-diagram-of-object linkage). Re-call with confirmed=True AND a "
        "`reason` (≥10 chars, specific) to execute. The reason is required and "
        "reviewed by an LLM — vague reasons get rejected. The model objects "
        "themselves are NOT deleted, only the diagram and its placements."
    ),
    input_schema=DeleteDiagramInput,
    permission="diagram:manage",
    permission_target="diagram",
    required_scope="agents:admin",
    mutating=True,
    deprecates_model=True,
    needs_confirmed_gate=True,
)
async def delete_diagram(args: DeleteDiagramInput, ctx: ToolContext) -> dict:
    """Two-step diagram delete."""
    from app.services import diagram_service

    diagram = await diagram_service.get_diagram(ctx.db, args.diagram_id)
    if diagram is None:
        raise ToolDenied(f"diagram {args.diagram_id} not found")

    if not args.confirmed:
        placements = await diagram_service.get_diagram_objects(ctx.db, args.diagram_id)
        placement_count = len(placements)
        impact = {
            "will_delete_diagram": 1,
            "will_drop_placements": placement_count,
            "is_child_of_object": (
                str(diagram.scope_object_id) if diagram.scope_object_id else None
            ),
        }
        return {
            "status": "awaiting_confirmation",
            "preview": (
                f"Will delete diagram {diagram.name} ({placement_count} placements)"
            ),
            "impact": impact,
            "target_id": diagram.id,
            "name": diagram.name,
        }

    # ── LLM destructive-op reviewer ────────────────────────────────────
    from app.agents.tools._destructive_review import review_destructive_op

    placements = await diagram_service.get_diagram_objects(ctx.db, args.diagram_id)
    impact = {
        "will_delete_diagram": 1,
        "will_drop_placements": len(placements),
        "is_child_of_object": (
            str(diagram.scope_object_id) if diagram.scope_object_id else None
        ),
    }
    verdict = await review_destructive_op(
        ctx=ctx,
        tool_name="delete_diagram",
        args=args,
        impact=impact,
        reason=args.reason,
        target_summary=f"diagram {diagram.name!r} (id={diagram.id})",
    )
    if verdict.verdict == "REJECT":
        raise ToolDenied(
            f"destructive-op reviewer rejected: {verdict.rationale}"
        )

    name = diagram.name
    target_id = diagram.id
    snapshot_workspace = getattr(diagram, "workspace_id", None)
    snapshot_draft = getattr(diagram, "draft_id", None)
    await diagram_service.delete_diagram(ctx.db, diagram)
    from app.agents.tools._realtime import publish_diagram_event

    publish_diagram_event(
        diagram=type(
            "_DStub",
            (),
            {
                "id": target_id,
                "workspace_id": snapshot_workspace,
                "draft_id": snapshot_draft,
            },
        )(),
        event_type="diagram.deleted",
        draft_id=snapshot_draft,
    )
    return {
        "action": "diagram.deleted",
        "target_type": "diagram",
        "target_id": target_id,
        "name": name,
        "preview": short_preview("Deleted", "diagram", name),
    }


# ---------------------------------------------------------------------------
# Hierarchy
# ---------------------------------------------------------------------------


@tool(
    name="link_object_to_child_diagram",
    description=(
        "Link an existing object to an existing diagram as its child (drill-down). "
        "Sets the diagram's scope_object_id."
    ),
    input_schema=LinkObjectToChildDiagramInput,
    permission="diagram:manage",
    permission_target="object",
    required_scope="agents:write",
    mutating=True,
)
async def link_object_to_child_diagram(
    args: LinkObjectToChildDiagramInput, ctx: ToolContext
) -> dict:
    """Set diagram.scope_object_id = object_id."""
    from app.schemas.diagram import DiagramUpdate
    from app.services import diagram_service, object_service

    obj = await object_service.get_object(ctx.db, args.object_id)
    if obj is None:
        raise ToolDenied(f"object {args.object_id} not found")
    diagram = await diagram_service.get_diagram(ctx.db, args.child_diagram_id)
    if diagram is None:
        raise ToolDenied(f"diagram {args.child_diagram_id} not found")

    updated = await diagram_service.update_diagram(
        ctx.db, diagram, DiagramUpdate(scope_object_id=args.object_id)
    )
    from app.agents.tools._realtime import publish_diagram_event

    publish_diagram_event(
        diagram=updated,
        event_type="diagram.updated",
        draft_id=getattr(updated, "draft_id", None),
    )

    return {
        "action": "diagram.updated",
        "target_type": "diagram",
        "target_id": updated.id,
        "name": updated.name,
        "linked_to_object_id": args.object_id,
        "preview": (
            f"Linked diagram {updated.name} as child of object {obj.name}"
        ),
    }


@tool(
    name="unlink_object_from_child_diagram",
    description=(
        "Unlink the drill-down child diagram from an object. Sets the linked "
        "diagram's scope_object_id back to NULL. The diagram itself is preserved."
    ),
    input_schema=UnlinkObjectFromChildDiagramInput,
    permission="diagram:manage",
    permission_target="object",
    required_scope="agents:write",
    mutating=True,
)
async def unlink_object_from_child_diagram(
    args: UnlinkObjectFromChildDiagramInput, ctx: ToolContext
) -> dict:
    """Find diagrams whose scope_object_id == object_id, clear the link."""
    from app.schemas.diagram import DiagramUpdate
    from app.services import diagram_service

    diagrams = await diagram_service.get_diagrams(
        ctx.db, scope_object_id=args.object_id, workspace_id=ctx.workspace_id
    )
    cleared: list[str] = []
    for diagram in diagrams:
        updated = await diagram_service.update_diagram(
            ctx.db, diagram, DiagramUpdate(scope_object_id=None)
        )
        cleared.append(str(updated.id))

    return {
        "action": "object.updated",
        "target_type": "object",
        "target_id": args.object_id,
        "unlinked_diagram_ids": cleared,
        "preview": f"Unlinked {len(cleared)} child diagram(s) from object",
    }


@tool(
    name="create_child_diagram_for_object",
    description=(
        "Composite tool: create a new diagram AND link it as a child of the given "
        "object. Atomic. Default name is f'{object.name} components'; default level "
        "is one deeper than the parent object's level."
    ),
    input_schema=CreateChildDiagramForObjectInput,
    permission="diagram:manage",
    permission_target="object",
    required_scope="agents:admin",
    mutating=True,
)
async def create_child_diagram_for_object(
    args: CreateChildDiagramForObjectInput, ctx: ToolContext
) -> dict:
    """Create + link in one step."""
    from app.schemas.diagram import DiagramCreate
    from app.services import diagram_service, object_service

    obj = await object_service.get_object(ctx.db, args.object_id)
    if obj is None:
        raise ToolDenied(f"object {args.object_id} not found")

    # ── Dedup guard: an object can have at most one canonical drill-in diagram.
    # If a diagram with ``scope_object_id == object_id`` already exists in this
    # workspace (live, non-draft), reuse it instead of creating a second one.
    # Without this guard, a re-run of the same plan after a session restart
    # silently creates "Facade Internal" alongside "Facade Internal Components"
    # and the new components land on the wrong canvas (see trace 355785c7).
    existing_children = await diagram_service.get_diagrams(
        ctx.db,
        scope_object_id=args.object_id,
        workspace_id=ctx.workspace_id,
    )
    existing_live = next(
        (d for d in existing_children if getattr(d, "draft_id", None) is None),
        None,
    )
    if existing_live is not None:
        record: dict[str, Any] = {
            "action": "diagram.reused",
            "status": "reused",
            "target_type": "diagram",
            "target_id": existing_live.id,
            "name": existing_live.name,
            "linked_to_object_id": args.object_id,
            "preview": (
                f"Object {obj.name} already has child diagram "
                f"{existing_live.name!r} — reusing it"
            ),
        }
        record.update(_diagram_meta(existing_live))
        return record

    parent_level = obj.c4_level if hasattr(obj, "c4_level") else "L1"
    level = args.level or _next_level(parent_level)
    diagram_type = _coerce_diagram_type_from_level(level)
    name = args.name or f"{obj.name} components"

    diagram = await diagram_service.create_diagram(
        ctx.db,
        DiagramCreate(
            name=name,
            type=diagram_type,
            scope_object_id=args.object_id,
        ),
        workspace_id=ctx.workspace_id,
    )
    from app.agents.tools._realtime import publish_diagram_event

    publish_diagram_event(
        diagram=diagram,
        event_type="diagram.created",
        draft_id=ctx.active_draft_id,
    )

    record = {
        "action": "diagram.created",
        "target_type": "diagram",
        "target_id": diagram.id,
        "name": diagram.name,
        "linked_to_object_id": args.object_id,
        "preview": (
            f"Created child diagram {diagram.name} for object {obj.name}"
        ),
    }
    record.update(_diagram_meta(diagram))
    return record


# ---------------------------------------------------------------------------
# Layout (auto_layout_diagram — task 054)
# ---------------------------------------------------------------------------


async def _handle_auto_layout_diagram(args: AutoLayoutDiagramInput, ctx: ToolContext) -> dict:
    """Run the layout engine on a diagram.

    Behaviour matrix:
      - ``scope='all'`` without ``confirmed=True`` → return ``awaiting_confirmation``
        with a preview of the moves the engine would perform.
      - ``dry_run=True`` → run the engine but don't apply; return the plan.
      - Otherwise → apply ``moves`` via :mod:`app.services.diagram_service` and
        return the resulting move count + metrics.
    """
    from app.agents.layout import engine as layout_engine
    from app.schemas.diagram import DiagramObjectUpdate
    from app.services import diagram_service

    scope = (args.scope or "new_only").lower()
    if scope not in ("new_only", "all"):
        raise ToolDenied(
            f"unknown scope {args.scope!r}; valid: 'new_only' | 'all'"
        )

    plan = await layout_engine.batch_layout(
        ctx.db, diagram_id=args.diagram_id, scope=scope  # type: ignore[arg-type]
    )

    moves_preview = [
        {"object_id": str(oid), "x": x, "y": y} for oid, x, y in plan.moves
    ]

    # scope='all' requires explicit confirmation.
    if scope == "all" and not args.confirmed:
        return {
            "status": "awaiting_confirmation",
            "preview": (
                f"Will reposition {len(plan.moves)} object(s) on diagram "
                f"{args.diagram_id} (scope='all')"
            ),
            "impact": {
                "moves_planned": len(plan.moves),
                "metrics": plan.metrics,
            },
            "target_id": args.diagram_id,
            "diagram_id": args.diagram_id,
            "moves": moves_preview,
        }

    # Dry run — return the plan without writing.
    if args.dry_run:
        return {
            "action": "diagram.relayout_planned",
            "target_type": "diagram",
            "target_id": args.diagram_id,
            "diagram_id": args.diagram_id,
            "dry_run": True,
            "moves": moves_preview,
            "moves_planned": len(plan.moves),
            "metrics": plan.metrics,
            "preview": (
                f"Planned {len(plan.moves)} move(s) on diagram (dry run)"
            ),
        }

    # Apply the moves.
    from app.agents.tools._realtime import publish_placement_event

    applied = 0
    for object_id, x, y in plan.moves:
        updated = await diagram_service.update_diagram_object(
            ctx.db,
            args.diagram_id,
            object_id,
            DiagramObjectUpdate(position_x=float(x), position_y=float(y)),
        )
        if updated is not None:
            applied += 1
            await publish_placement_event(
                db=ctx.db,
                diagram_id=args.diagram_id,
                placement=updated,
                event_type="diagram_object.updated",
                draft_id=ctx.active_draft_id,
            )

    return {
        "action": "diagram.relayouted",
        "target_type": "diagram",
        "target_id": args.diagram_id,
        "diagram_id": args.diagram_id,
        "moves_applied": applied,
        "metrics": plan.metrics,
        "preview": (
            f"Re-laid out diagram ({applied} object(s) moved, scope='{scope}')"
        ),
    }


AUTO_LAYOUT_DIAGRAM: Tool = Tool(
    name="auto_layout_diagram",
    description=(
        "Re-layout a diagram. scope='new_only' (recommended) only places objects "
        "without coordinates. scope='all' moves all existing objects — REQUIRES "
        "confirmed=True. dry_run=True returns the plan without applying."
    ),
    input_schema=AutoLayoutDiagramInput,
    handler=_handle_auto_layout_diagram,
    required_permission="diagram:edit",
    permission_target="diagram",
    required_scope="agents:write",
    mutating=True,
    needs_confirmed_gate=False,  # we do our own gate for scope='all'
)


register_tool(AUTO_LAYOUT_DIAGRAM)
