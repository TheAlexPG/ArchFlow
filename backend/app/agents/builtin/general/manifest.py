"""Per-turn repo manifest for the supervisor.

When the supervisor visits at the start of a turn, the runtime calls
``collect_repo_manifest`` on the active diagram and renders the result
as a system block ("AVAILABLE REPO RESEARCHERS"). Each entry becomes a
``delegate_to_repo_<slug>`` tool the supervisor can invoke to delegate
to ``repo_researcher`` with the right runtime context.

D3: recursive descendant walk. Starts from the active diagram, then
walks each scope-object's child diagram (relationship:
``Diagram.scope_object_id == ModelObject.id``) up to a 3-level cap that
mirrors the frontend's ``useDiagramBreadcrumbs`` (frontend/src/hooks/
use-diagrams.ts:104 — three levels of ancestor walking, capped at the
practical C4 chain depth). Cycle-guarded by tracking visited diagram
ids; total entries capped at :data:`MAX_MANIFEST_ENTRIES` so a
mega-system can't blow the supervisor's prompt.

Every collected entry is filtered to repo-linkable types (System / app /
store) — non-eligible objects can't carry ``repo_url`` per the service
layer rules, but we double-check here so a malformed DB row doesn't
leak into the supervisor's tool list.
"""
from __future__ import annotations

import logging
import re
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.diagram import Diagram, DiagramObject
from app.models.object import ModelObject, ObjectType
from app.services.object_service import REPO_LINKABLE_TYPES

logger = logging.getLogger(__name__)

_RepoNodeType = Literal["system", "app", "store"]


# Total-entries cap so a workspace with 200+ linked repos doesn't blow the
# supervisor's prompt budget. Truncation is signalled via a hint line in
# :func:`render_repo_manifest_block` so the user knows about the cut-off.
MAX_MANIFEST_ENTRIES = 50

# Depth cap for the descendant walk. Mirrors ``useDiagramBreadcrumbs``
# (frontend hook walks at most 3 ancestor levels — l0/l1/l2 — which is the
# practical C4 chain depth). We hard-cap at ``MAX_DEPTH`` levels so a
# pathologically deep tree (e.g. someone nested Component diagrams beyond
# the C4 spec) can't burn the entire prompt budget.
MAX_DEPTH = 3


class RepoLink(BaseModel):
    """One repo-linked object visible to the supervisor."""

    node_id: UUID
    node_name: str
    node_type: _RepoNodeType
    repo_url: str
    repo_branch: str | None = None
    slug: str = Field(
        ...,
        description=(
            "Kebab-cased identifier the supervisor uses to address this "
            "repo (``delegate_to_repo_<slug>``). Collision-suffixed when "
            "two nodes share a name."
        ),
    )
    depth: int = Field(
        default=0,
        ge=0,
        description=(
            "0 = active diagram, 1 = direct child diagram, 2 = grandchild. "
            "Surfaced for observability only — supervisor doesn't act on it."
        ),
    )


_KEBAB_RE = re.compile(r"[^a-z0-9]+")


def _slugify(name: str) -> str:
    """Lower-case kebab-case slug derived from a node name. Falls back to
    ``"repo"`` when ``name`` has no usable characters (the caller appends
    a uuid suffix for uniqueness anyway).
    """
    base = _KEBAB_RE.sub("-", (name or "").strip().lower()).strip("-")
    return base or "repo"


def _disambiguate(slug: str, used: set[str], node_id: UUID) -> str:
    """Make ``slug`` unique within ``used`` by appending a 4-char uuid
    fragment. The uuid hex is deterministic per-node so subsequent turns
    see the same slug for the same object.
    """
    if slug not in used:
        return slug
    suffix = node_id.hex[:4]
    candidate = f"{slug}-{suffix}"
    # Astronomically unlikely double collision; keep extending if needed.
    n = 1
    while candidate in used:
        candidate = f"{slug}-{suffix}-{n}"
        n += 1
    return candidate


def _node_type_str(t: ObjectType) -> _RepoNodeType:
    if t is ObjectType.SYSTEM:
        return "system"
    if t is ObjectType.APP:
        return "app"
    if t is ObjectType.STORE:
        return "store"
    # Should never happen because we filter by REPO_LINKABLE_TYPES upstream.
    raise ValueError(f"Object type {t!r} is not repo-linkable")


async def _fetch_diagram_objects(
    diagram_id: UUID, db: AsyncSession
) -> list[ModelObject]:
    """Return every object placed on ``diagram_id``, ordered by name.

    Includes objects with ``repo_url`` IS NULL — descendants need to walk
    even non-linked scope-objects so we can reach repos nested deeper.
    Filtering by ``repo_url`` happens in :func:`collect_repo_manifest`
    after the walk, not here.
    """
    stmt = (
        select(ModelObject)
        .join(DiagramObject, DiagramObject.object_id == ModelObject.id)
        .where(DiagramObject.diagram_id == diagram_id)
        .order_by(ModelObject.name)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def _fetch_child_diagram_id(
    object_id: UUID, db: AsyncSession
) -> UUID | None:
    """Return the (first) child diagram whose ``scope_object_id`` equals
    ``object_id``, or ``None`` when the object has no decomposition.

    A scope-object can technically be the scope of multiple diagrams
    (e.g. live + draft) — we pick the first one ordered by id so the walk
    is deterministic across turns. Draft diagrams aren't filtered out
    here because the manifest is read-only and only used to populate the
    supervisor's tool list; including a draft variant just means the
    supervisor sees the repo once (slug collision is handled).
    """
    stmt = (
        select(Diagram.id)
        .where(Diagram.scope_object_id == object_id)
        .order_by(Diagram.id)
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def collect_repo_manifest(
    active_diagram_id: UUID | None, db: AsyncSession
) -> list[RepoLink]:
    """Walk the active diagram + descendant child diagrams; return every
    repo-linked object in BFS order (root first, then level-1 children, …).

    Behaviour:
      * Cycle-guarded — visited diagram ids tracked in a set; revisits
        skipped silently.
      * Depth-capped at :data:`MAX_DEPTH` (mirrors ``useDiagramBreadcrumbs``
        frontend/src/hooks/use-diagrams.ts:104). A tree deeper than
        ``MAX_DEPTH`` is pruned at level ``MAX_DEPTH - 1``.
      * Total cap at :data:`MAX_MANIFEST_ENTRIES`. When the cap is reached
        we stop the walk early and the renderer surfaces a truncation hint.
      * Filters non-eligible types: only system / app / store may surface,
        regardless of whether a malformed row carries ``repo_url``.
      * Slug collisions resolved across the whole walk (not per-level), so
        two nodes named ``auth-service`` at different depths get distinct
        identifiers.

    Returns an empty list when:
      * ``active_diagram_id`` is ``None`` (no diagram in chat context),
      * the active diagram has no placements,
      * none of the placed objects (recursively) carry ``repo_url``,
      * any of the queries fails (defensive — repo manifest is opt-in,
        not load-bearing for the rest of the supervisor's flow).
    """
    if active_diagram_id is None:
        return []

    used_slugs: set[str] = set()
    visited_diagrams: set[UUID] = set()
    out: list[RepoLink] = []

    # BFS queue of (diagram_id, depth). Depth=0 is the active diagram.
    queue: list[tuple[UUID, int]] = [(active_diagram_id, 0)]

    try:
        while queue:
            diagram_id, depth = queue.pop(0)
            if diagram_id in visited_diagrams:
                # Cycle guard — same diagram reached via two paths or via
                # the parent-of-self loop. Skip silently so a misshapen
                # tree never makes the runtime hang.
                continue
            visited_diagrams.add(diagram_id)

            objects = await _fetch_diagram_objects(diagram_id, db)
            for obj in objects:
                # Surface the link if the object itself carries repo_url +
                # eligible type. Non-eligible types are skipped even when
                # the row carries a stale repo_url.
                if obj.repo_url is not None and obj.type in REPO_LINKABLE_TYPES:
                    if len(out) >= MAX_MANIFEST_ENTRIES:
                        logger.info(
                            "collect_repo_manifest: total cap (%d) reached; "
                            "remaining objects skipped for diagram=%s",
                            MAX_MANIFEST_ENTRIES,
                            active_diagram_id,
                        )
                        return out
                    slug = _disambiguate(_slugify(obj.name), used_slugs, obj.id)
                    used_slugs.add(slug)
                    out.append(
                        RepoLink(
                            node_id=obj.id,
                            node_name=obj.name,
                            node_type=_node_type_str(obj.type),
                            repo_url=obj.repo_url,
                            repo_branch=obj.repo_branch,
                            slug=slug,
                            depth=depth,
                        )
                    )

                # Recurse into the object's child diagram only when we're
                # below the depth cap. Non-eligible types CAN still have a
                # child diagram (e.g. a Group → Container drilldown), so we
                # don't gate the descent on type — only the surface check
                # above gates the link emission.
                if depth + 1 >= MAX_DEPTH:
                    continue
                child_id = await _fetch_child_diagram_id(obj.id, db)
                if child_id is None:
                    continue
                if child_id in visited_diagrams:
                    # Already-visited child: cycle guard hits next pop too,
                    # but we also skip enqueueing to keep the queue small.
                    continue
                queue.append((child_id, depth + 1))
    except Exception:  # noqa: BLE001 — degrade gracefully
        logger.warning(
            "collect_repo_manifest: walk failed for diagram=%s",
            active_diagram_id,
            exc_info=True,
        )
        return out  # Return whatever we collected before the failure.

    return out


def render_repo_manifest_block(manifest: list[RepoLink]) -> str:
    """Render the supervisor's "AVAILABLE REPO RESEARCHERS" block.

    Returns an empty string when ``manifest`` is empty so the supervisor
    sees clean context (the spec is explicit: the block must NOT render
    when there are no repos linked to the active scope).

    Truncation hint: when the manifest reaches :data:`MAX_MANIFEST_ENTRIES`
    a parenthetical note is appended so the supervisor can mention the
    cut-off to the user (e.g. "I see 50 of N linked repos; ask for a
    specific one if it's missing").
    """
    if not manifest:
        return ""
    lines = ["## AVAILABLE REPO RESEARCHERS"]
    lines.append(
        "Each entry is a virtual sub-agent that reads one linked GitHub "
        "repository on your behalf. Invoke with "
        "``delegate_to_repo_<slug>(question=...)`` — same shape as "
        "``delegate_to_researcher`` but scoped to the repo. Use them when "
        "the user asks about code, when a researcher's findings need "
        "ground-truth from the source, or when planning a Component "
        "diagram from real implementation details. The repo agent is "
        "read-only and returns free-form markdown."
    )
    for entry in manifest:
        branch = entry.repo_branch or "(default)"
        # Strip the canonical https://github.com/ prefix to keep the line short.
        short = entry.repo_url
        if short.startswith("https://github.com/"):
            short = short[len("https://github.com/") :]
        lines.append(
            f"- **repo:{entry.slug}** — Reads `{short}` on `{branch}` "
            f"(the **{entry.node_name}** {entry.node_type})"
        )
    if len(manifest) >= MAX_MANIFEST_ENTRIES:
        lines.append(
            f"\n_Note: showing the first {MAX_MANIFEST_ENTRIES} linked "
            "repos found while walking the active diagram and its "
            "descendants. Additional repos may exist deeper in the tree; "
            "ask the user to navigate closer to a specific scope if "
            "they need one that isn't listed._"
        )
    return "\n".join(lines)
