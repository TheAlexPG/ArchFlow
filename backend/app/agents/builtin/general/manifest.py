"""Per-turn repo manifest for the supervisor.

When the supervisor visits at the start of a turn, the runtime calls
``collect_repo_manifest`` on the active diagram and renders the result
as a system block ("AVAILABLE REPO RESEARCHERS"). Each entry becomes a
``delegate_to_repo_<slug>`` tool the supervisor can invoke to delegate
to ``repo_researcher`` with the right runtime context.

D2: NON-recursive. Only collects placements directly on the active
diagram. D3 will walk descendant child diagrams with the same 3-level
cap as ``useDiagramBreadcrumbs``.

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

from app.models.diagram import DiagramObject
from app.models.object import ModelObject, ObjectType
from app.services.object_service import REPO_LINKABLE_TYPES

logger = logging.getLogger(__name__)

_RepoNodeType = Literal["system", "app", "store"]


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


async def collect_repo_manifest(
    active_diagram_id: UUID | None, db: AsyncSession
) -> list[RepoLink]:
    """Walk the active diagram's placements; return every repo-linked object.

    Returns an empty list when:
      * ``active_diagram_id`` is ``None`` (no diagram in chat context),
      * the diagram has no placements,
      * none of the placed objects carry ``repo_url``,
      * any of the queries fails (defensive — repo manifest is opt-in,
        not load-bearing for the rest of the supervisor's flow).
    """
    if active_diagram_id is None:
        return []
    try:
        stmt = (
            select(ModelObject)
            .join(DiagramObject, DiagramObject.object_id == ModelObject.id)
            .where(
                DiagramObject.diagram_id == active_diagram_id,
                ModelObject.repo_url.is_not(None),
                ModelObject.type.in_(REPO_LINKABLE_TYPES),
            )
            .order_by(ModelObject.name)
        )
        result = await db.execute(stmt)
        rows = list(result.scalars().all())
    except Exception:  # noqa: BLE001 — degrade gracefully
        logger.warning(
            "collect_repo_manifest: query failed for diagram=%s",
            active_diagram_id,
            exc_info=True,
        )
        return []

    used_slugs: set[str] = set()
    out: list[RepoLink] = []
    for obj in rows:
        if obj.repo_url is None:
            continue  # Defensive — already filtered in the WHERE clause.
        if obj.type not in REPO_LINKABLE_TYPES:
            continue
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
            )
        )
    return out


def render_repo_manifest_block(manifest: list[RepoLink]) -> str:
    """Render the supervisor's "AVAILABLE REPO RESEARCHERS" block.

    Returns an empty string when ``manifest`` is empty so the supervisor
    sees clean context (the spec is explicit: the block must NOT render
    when there are no repos linked to the active scope).
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
    return "\n".join(lines)
