"""Search & catalog tools — read-only, called BEFORE create_object/place_on_diagram
to avoid duplicates. Critical for the IcePanel reuse-first pattern."""
from __future__ import annotations

import contextlib
from difflib import SequenceMatcher
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select

from app.agents.tools.base import ToolContext, tool
from app.models.object import ModelObject, ObjectType
from app.models.technology import TechCategory, Technology

# ---------------------------------------------------------------------------
# Input schemas
# ---------------------------------------------------------------------------


# C4 PascalCase aliases ("SoftwareSystem", "Container") that local models love
# to invent → snake_case enum values used by the DB. Anything else is dropped
# silently rather than raising — the LLM gets an empty result it can recover
# from instead of a 500 that aborts the whole transaction.
_TYPE_ALIASES: dict[str, str] = {
    "system": "system",
    "softwaresystem": "system",
    "software_system": "system",
    "actor": "actor",
    "user": "actor",
    "person": "actor",
    "external_system": "external_system",
    "externalsystem": "external_system",
    "external": "external_system",
    "group": "group",
    "boundary": "group",
    "container": "app",
    "containerinstance": "app",
    "app": "app",
    "application": "app",
    "service": "app",
    "microservice": "app",
    "store": "store",
    "database": "store",
    "queue": "store",
    "cache": "store",
    "topic": "store",
    "component": "component",
    "module": "component",
    "node": "app",
    "code": "component",
}

_VALID_TYPES = frozenset(t.value for t in ObjectType)


def _normalise_types(raw: list[str]) -> list[str]:
    """Map free-form type strings to valid ObjectType enum values.

    Returns a deduped list of enum-valid strings. Unknown aliases are
    silently dropped — preferable to crashing the whole tool call.
    """
    seen: list[str] = []
    for v in raw or []:
        if not isinstance(v, str):
            continue
        key = v.strip().lower().replace("-", "_").replace(" ", "_")
        mapped = _TYPE_ALIASES.get(key)
        if mapped is None and key in _VALID_TYPES:
            mapped = key
        if mapped is not None and mapped not in seen:
            seen.append(mapped)
    return seen


class SearchExistingObjectsInput(BaseModel):
    query: str
    types: list[str] = Field(
        default_factory=list,
        description=(
            "Optional filter. Valid values: 'system', 'actor', 'external_system', "
            "'group', 'app', 'store', 'component'. PascalCase aliases like "
            "'SoftwareSystem' or 'Container' are accepted; unknown values are dropped."
        ),
    )
    scope: Literal["workspace", "diagram"] = "workspace"
    limit: int = Field(20, ge=1, le=50)

    @field_validator("types", mode="before")
    @classmethod
    def _normalise_types(cls, v):  # noqa: D401
        if v is None:
            return []
        if isinstance(v, str):
            v = [v]
        return _normalise_types(list(v))


class SearchExistingTechnologiesInput(BaseModel):
    query: str
    kind: str | None = None  # 'language' | 'protocol' | 'platform' | etc.
    limit: int = Field(20, ge=1, le=50)


class ListConnectionProtocolsInput(BaseModel):
    pass


class ListObjectTypeDefinitionsInput(BaseModel):
    pass


# ---------------------------------------------------------------------------
# Object type taxonomy (static, workspace-independent reference data)
# ---------------------------------------------------------------------------

_OBJECT_TYPE_DEFINITIONS = [
    {
        "type": "system",
        "description": (
            "Top-level boundary representing a logical product/system at L1. "
            "Groups related apps and stores that together form one deployable product."
        ),
        "valid_at_level": "L1",
    },
    {
        "type": "external_system",
        "description": (
            "An external third-party or out-of-scope system at L1 that the modelled "
            "architecture depends on or communicates with."
        ),
        "valid_at_level": "L1",
    },
    {
        "type": "actor",
        "description": (
            "A human user, role, or persona that interacts with the system at L1."
        ),
        "valid_at_level": "L1",
    },
    {
        "type": "app",
        "description": (
            "Container service/process inside a system, at L2. "
            "Represents a runnable unit such as a microservice, web app, or mobile client."
        ),
        "valid_at_level": "L2",
    },
    {
        "type": "store",
        "description": (
            "Database, cache, queue, or other persistent/messaging store inside a "
            "system at L2."
        ),
        "valid_at_level": "L2",
    },
    {
        "type": "component",
        "description": (
            "Module, class, or internal component inside an app or store at L3. "
            "Used for the most detailed level of decomposition."
        ),
        "valid_at_level": "L3",
    },
    {
        "type": "group",
        "description": (
            "Visual grouping (boundary/cluster) — not a strict C4 type. "
            "Used to visually organise objects on a diagram without implying ownership."
        ),
        "valid_at_level": "any",
    },
]


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------


def _score(query: str, name: str, description: str | None) -> float:
    """Simple fuzzy score in [0, 1]. Prioritises exact prefix match, then
    SequenceMatcher ratio on name, then falls back to description."""
    q = query.lower()
    n = name.lower()
    if n == q:
        return 1.0
    if n.startswith(q):
        return 0.9
    if q in n:
        return 0.8
    name_ratio = SequenceMatcher(None, q, n).ratio()
    if description:
        desc_ratio = SequenceMatcher(None, q, description.lower()).ratio() * 0.5
        return max(name_ratio, desc_ratio)
    return name_ratio


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------


@tool(
    name="search_existing_objects",
    description=(
        "Fuzzy search by name (and optional type filter) for objects already in the workspace. "
        "ALWAYS call this BEFORE create_object to avoid duplicates. Returns a ranked list with "
        "id, name, type, parent_id."
    ),
    input_schema=SearchExistingObjectsInput,
    permission="workspace:read",
    permission_target="workspace",
    required_scope="agents:read",
    mutating=False,
)
async def search_existing_objects(
    args: SearchExistingObjectsInput, ctx: ToolContext
) -> dict:
    """Returns {items: [{id, name, type, parent_id, score}], total_matches}.

    Uses direct SQLAlchemy ILIKE on object.name for the DB pre-filter, then
    applies in-process fuzzy scoring and sorting. Empty query returns an empty
    list to avoid dumping the entire workspace.
    """
    if not args.query or not args.query.strip():
        return {"items": [], "total_matches": 0}

    term = f"%{args.query.lower()}%"

    stmt = (
        select(ModelObject)
        .where(
            ModelObject.draft_id.is_(None),
            ModelObject.workspace_id == ctx.workspace_id,
            func.lower(ModelObject.name).ilike(term),
        )
        .order_by(ModelObject.name)
        .limit(args.limit * 3)  # over-fetch so post-scoring can re-rank
    )

    if args.types:
        stmt = stmt.where(ModelObject.type.in_(args.types))

    result = await ctx.db.execute(stmt)
    rows = list(result.scalars().all())

    scored = sorted(
        (
            {
                "id": str(obj.id),
                "name": obj.name,
                "type": obj.type if isinstance(obj.type, str) else obj.type.value,
                "parent_id": str(obj.parent_id) if obj.parent_id else None,
                "score": round(_score(args.query, obj.name, obj.description), 4),
            }
            for obj in rows
        ),
        key=lambda x: x["score"],
        reverse=True,
    )

    items = scored[: args.limit]
    return {"items": items, "total_matches": len(scored)}


@tool(
    name="search_existing_technologies",
    description="Fuzzy search the technology catalog (built-in + workspace-custom).",
    input_schema=SearchExistingTechnologiesInput,
    permission="workspace:read",
    permission_target="workspace",
    required_scope="agents:read",
    mutating=False,
)
async def search_existing_technologies(
    args: SearchExistingTechnologiesInput, ctx: ToolContext
) -> dict:
    """Returns {items: [{id, name, slug, category, workspace_id, score}], total_matches}.

    Delegates to technology_service.list_technologies for the DB query, then
    applies in-process scoring. Empty query returns empty list.
    """
    if not args.query or not args.query.strip():
        return {"items": [], "total_matches": 0}

    from app.services import technology_service

    category: TechCategory | None = None
    if args.kind:
        with contextlib.suppress(ValueError):
            category = TechCategory(args.kind.lower())

    techs = await technology_service.list_technologies(
        ctx.db,
        ctx.workspace_id,
        q=args.query,
        category=category,
    )

    scored = sorted(
        (
            {
                "id": str(t.id),
                "name": t.name,
                "slug": t.slug,
                "category": t.category if isinstance(t.category, str) else t.category.value,
                "workspace_id": str(t.workspace_id) if t.workspace_id else None,
                "score": round(_score(args.query, t.name, None), 4),
            }
            for t in techs
        ),
        key=lambda x: x["score"],
        reverse=True,
    )

    items = scored[: args.limit]
    return {"items": items, "total_matches": len(scored)}


@tool(
    name="list_connection_protocols",
    description=(
        "List technologies tagged as 'protocol' (HTTP, gRPC, AMQP, MCP, A2A, etc.) "
        "for use in connection.technology_ids."
    ),
    input_schema=ListConnectionProtocolsInput,
    permission="workspace:read",
    permission_target="workspace",
    required_scope="agents:read",
    mutating=False,
)
async def list_connection_protocols(
    args: ListConnectionProtocolsInput, ctx: ToolContext
) -> dict:
    """Returns {items: [{id, name, slug, category}]}.

    Queries only technologies with category='protocol', visible to this
    workspace (built-in + workspace-custom).
    """
    stmt = select(Technology).where(
        Technology.category == TechCategory.PROTOCOL,
        or_(
            Technology.workspace_id.is_(None),
            Technology.workspace_id == ctx.workspace_id,
        ),
    ).order_by(Technology.name)

    result = await ctx.db.execute(stmt)
    rows = list(result.scalars().all())

    items = [
        {
            "id": str(t.id),
            "name": t.name,
            "slug": t.slug,
            "category": "protocol",
        }
        for t in rows
    ]
    return {"items": items, "total": len(items)}


@tool(
    name="list_object_type_definitions",
    description=(
        "Return the canonical object type taxonomy with descriptions. "
        "Static reference — call once if uncertain."
    ),
    input_schema=ListObjectTypeDefinitionsInput,
    permission="workspace:read",
    permission_target="workspace",
    required_scope="agents:read",
    mutating=False,
)
async def list_object_type_definitions(
    args: ListObjectTypeDefinitionsInput, ctx: ToolContext
) -> dict:
    """Static. Returns:
    {types: [
      {type: 'system', description: '...', valid_at_level: 'L1'},
      {type: 'external_system', description: '...'},
      {type: 'actor', description: '...'},
      {type: 'app',  description: 'Container service/process inside a system, at L2.'},
      {type: 'store', description: 'Database/cache/queue inside a system at L2.'},
      {type: 'component', description: 'Module inside an app/store at L3.'},
      {type: 'group', description: 'Visual grouping (boundary/cluster) — not a strict C4 type.'},
    ]}
    Hardcoded — stable workspace-independent reference data.
    """
    return {"types": _OBJECT_TYPE_DEFINITIONS}
