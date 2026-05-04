"""Per-turn repo manifest for the supervisor.

When the supervisor visits at the start of a turn, the runtime calls
``collect_repo_manifest`` on the active diagram and renders the result
as a system block ("AVAILABLE REPO RESEARCHERS"). Each unique repo URL
becomes a ``delegate_to_git_researcher_<slug>`` tool the supervisor can
invoke to delegate to ``repo_researcher`` with the right runtime context.

Slug derivation: kebab-case of the repo NAME (the ``<name>`` part of
``<owner>/<name>`` in the canonical github URL). When two manifest
entries reference different-owner repos that happen to share a name
(e.g. ``my-org/auth-service`` and ``other-org/auth-service``), the slug
includes the owner: ``my-org-auth-service`` / ``other-org-auth-service``.
When two entries point to the SAME repo URL (e.g. one repo linked from
two diagram nodes), the manifest still carries one ``RepoLink`` per
node — :mod:`supervisor` aggregates by repo URL when building the tool
list so the supervisor sees one tool per repo (with each linked
component listed in the description).

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
from typing import Any, Literal
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
            "repo (``delegate_to_git_researcher_<slug>``). Derived from "
            "the repo NAME (the ``<name>`` part of ``<owner>/<name>``). "
            "When two different-owner repos share a name, the slug is "
            "owner-prefixed (``<owner>-<name>``) so the LLM can tell "
            "them apart at routing time."
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
    """Lower-case kebab-case slug derived from a string. Falls back to
    ``"repo"`` when ``name`` has no usable characters (the caller appends
    an owner prefix or uuid suffix for uniqueness if needed).
    """
    base = _KEBAB_RE.sub("-", (name or "").strip().lower()).strip("-")
    return base or "repo"


def _parse_owner_repo(repo_url: str) -> tuple[str, str] | None:
    """Return ``(owner, repo)`` parsed from a canonical github URL, or
    ``None`` when the URL doesn't match (defensive — the manifest already
    filters on canonical form, but a malformed legacy row should degrade
    gracefully here rather than crash the whole walk).
    """
    from app.services.repo_credentials_service import parse_repo_url

    try:
        return parse_repo_url(repo_url)
    except (ValueError, TypeError):
        return None


def _slug_for_repo(owner: str, repo_name: str, *, with_owner: bool) -> str:
    """Build the slug for a repo. ``with_owner=True`` prepends the kebab
    owner so two different-owner repos with the same name don't collide.
    """
    repo_slug = _slugify(repo_name)
    if not with_owner:
        return repo_slug
    owner_slug = _slugify(owner)
    return f"{owner_slug}-{repo_slug}"


def _disambiguate(slug: str, used: set[str], node_id: UUID) -> str:
    """Last-resort uniqueness suffix for slugs that *still* collide after
    repo-name + owner-prefix derivation. Almost never fires in practice
    (it would take e.g. ``my-org/auth-service`` and ``my-org-auth/service``
    rendering to the same kebab string), but kept so the dynamic tool
    name is guaranteed unique even on pathological inputs.
    """
    if slug not in used:
        return slug
    suffix = node_id.hex[:4]
    candidate = f"{slug}-{suffix}"
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
      * Slug derivation: kebab-case of the repo NAME (the ``<name>`` part
        of ``<owner>/<name>``). When two manifest entries reference
        different-owner repos that share a name, both slugs are
        owner-prefixed (``<owner>-<name>``) so the LLM can disambiguate
        at routing time. Two entries pointing at the SAME repo URL keep
        the same slug — the supervisor aggregates by repo URL when
        building tools.

    Returns an empty list when:
      * ``active_diagram_id`` is ``None`` (no diagram in chat context),
      * the active diagram has no placements,
      * none of the placed objects (recursively) carry ``repo_url``,
      * any of the queries fails (defensive — repo manifest is opt-in,
        not load-bearing for the rest of the supervisor's flow).
    """
    if active_diagram_id is None:
        return []

    visited_diagrams: set[UUID] = set()

    # Pass 1: walk the diagram tree and collect every (obj, depth) tuple
    # that carries a repo link. We defer slug assignment to pass 2 so we
    # can decide owner-prefixed vs bare slugs based on the global
    # repo-name distribution (different owners with same repo name → both
    # owner-prefixed).
    collected: list[tuple[Any, int]] = []  # (obj, depth)

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
                    if len(collected) >= MAX_MANIFEST_ENTRIES:
                        logger.info(
                            "collect_repo_manifest: total cap (%d) reached; "
                            "remaining objects skipped for diagram=%s",
                            MAX_MANIFEST_ENTRIES,
                            active_diagram_id,
                        )
                        break
                    collected.append((obj, depth))

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
            else:
                continue
            # If we hit the inner ``break`` (manifest cap reached), stop
            # the BFS walk altogether.
            if len(collected) >= MAX_MANIFEST_ENTRIES:
                break
    except Exception:  # noqa: BLE001 — degrade gracefully
        logger.warning(
            "collect_repo_manifest: walk failed for diagram=%s",
            active_diagram_id,
            exc_info=True,
        )
        # Fall through with whatever we collected so the supervisor still
        # gets a partial manifest.

    # Pass 2: figure out which repo names need owner prefixing. A name
    # collides when two entries reference repos with the same kebab-name
    # but DIFFERENT canonical URLs (= different owners, or different
    # repos that happen to slugify the same). Same-URL duplicates are
    # NOT a collision — supervisor aggregates by URL later.
    name_to_urls: dict[str, set[str]] = {}
    parsed: list[tuple[Any, int, str | None, str | None, str]] = []
    # Each entry: (obj, depth, owner, repo_name, fallback_slug_base)
    for obj, depth in collected:
        ownerrepo = _parse_owner_repo(obj.repo_url) if obj.repo_url else None
        if ownerrepo is not None:
            owner, repo_name = ownerrepo
            base_slug = _slugify(repo_name)
        else:
            # Malformed URL — keep the entry but fall back to node-name
            # slug; we never owner-prefix this case (no parsable owner).
            owner, repo_name = None, None
            base_slug = _slugify(obj.name)
        parsed.append((obj, depth, owner, repo_name, base_slug))
        name_to_urls.setdefault(base_slug, set()).add(obj.repo_url)

    # A name needs owner-prefixing when the SAME slug base maps to ≥2
    # distinct URLs. (One URL = same repo from multiple nodes → keep
    # bare slug → supervisor aggregates.)
    needs_owner_prefix: set[str] = {
        base for base, urls in name_to_urls.items() if len(urls) >= 2
    }

    # Final emission: build slugs, run last-resort dedup against the
    # generated slug set, and assemble the RepoLink list.
    used_slugs: set[str] = set()
    out: list[RepoLink] = []
    for obj, depth, owner, repo_name, base_slug in parsed:
        if base_slug in needs_owner_prefix and owner is not None and repo_name is not None:
            slug = _slug_for_repo(owner, repo_name, with_owner=True)
        else:
            slug = base_slug
        # Defensive: if two SAME-URL entries collide on slug, _disambiguate
        # is a no-op (slug already in used_slugs from the first entry → we
        # WANT them to share). But if two different URLs still collide
        # post-owner-prefix (very rare), suffix to keep tool names unique.
        # We share-or-suffix based on whether the entries reference the
        # same repo URL.
        if slug in used_slugs:
            # Walk back to see if any prior emitted entry has the same URL.
            shared = any(
                e.slug == slug and e.repo_url == obj.repo_url for e in out
            )
            if not shared:
                slug = _disambiguate(slug, used_slugs, obj.id)
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

    return out


def aggregate_manifest_by_repo(
    manifest: list[RepoLink],
) -> list[tuple[RepoLink, list[RepoLink]]]:
    """Group ``manifest`` by ``repo_url`` so the supervisor sees one tool
    per unique GitHub repo.

    Returns a list of ``(primary, all_links)`` tuples in first-seen order
    (BFS — root first, then descendants). ``primary`` is the first
    :class:`RepoLink` seen for the URL (used for the slug + branch + the
    primary node name). ``all_links`` is every :class:`RepoLink` that
    references the same URL — supervisor renders the "linked to ..." list
    from this so the LLM can see every component the repo is wired to.
    """
    seen: dict[str, list[RepoLink]] = {}
    order: list[str] = []
    for entry in manifest:
        url = entry.repo_url
        if url not in seen:
            seen[url] = []
            order.append(url)
        seen[url].append(entry)
    return [(seen[u][0], seen[u]) for u in order]


def _format_linked_to(links: list[RepoLink]) -> str:
    """Render the "linked to <ComponentA> Container and <ComponentB>
    Container" suffix for a repo that's referenced from one or more
    diagram nodes. Preserves diagram order (BFS / depth-first as supplied
    by ``aggregate_manifest_by_repo``).
    """
    parts = [f"the **{e.node_name}** {e.node_type}" for e in links]
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} and {parts[1]}"
    return ", ".join(parts[:-1]) + f", and {parts[-1]}"


def render_repo_manifest_block(manifest: list[RepoLink]) -> str:
    """Render the supervisor's "AVAILABLE REPO RESEARCHERS" block.

    One bullet per UNIQUE repo URL — when a repo is linked from multiple
    nodes, the linked-to clause lists every component (preserving BFS
    diagram order).

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
        "``delegate_to_git_researcher_<slug>(question=...)`` — same shape "
        "as ``delegate_to_researcher`` but scoped to the repo's source "
        "code. Use them when the user asks about code, when a "
        "researcher's findings need ground-truth from the source, or "
        "when planning a Component diagram from real implementation "
        "details. The repo agent is read-only and returns free-form "
        "markdown. Note: ``delegate_to_researcher`` has NO access to "
        "GitHub repos — it only reads the workspace's C4 model."
    )
    for primary, all_links in aggregate_manifest_by_repo(manifest):
        branch = primary.repo_branch or "(default)"
        short = primary.repo_url
        if short.startswith("https://github.com/"):
            short = short[len("https://github.com/") :]
        linked_to = _format_linked_to(all_links)
        lines.append(
            f"- **repo:{primary.slug}** — Reads `{short}` on `{branch}` "
            f"(linked to {linked_to})"
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
