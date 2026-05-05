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

D3: bidirectional walk.

Down (descendants): starts from the active diagram, then walks each
scope-object's child diagram (relationship:
``Diagram.scope_object_id == ModelObject.id``) up to :data:`MAX_DEPTH`
levels. Mirrors the frontend's ``useDiagramBreadcrumbs``
(frontend/src/hooks/use-diagrams.ts:104 — three levels of ancestor
walking, capped at the practical C4 chain depth).

Up (ancestors): starts from the active diagram's ``scope_object_id``
(the parent System / Container the active diagram decomposes), then
walks the parent placement (``DiagramObject.object_id == scope_object.id``)
to find which diagram contains that scope_object, and recurses upward
on that parent diagram's own ``scope_object_id`` until ``scope_object_id``
is null (root) or :data:`MAX_DEPTH` ancestor levels are exhausted. This
makes a repo on the active diagram's *parent* (the canonical case: user
drilled INTO a Container with a linked repo) visible to the supervisor.

Cycle-guarded by tracking visited diagram ids in BOTH directions; total
entries capped at :data:`MAX_MANIFEST_ENTRIES` (after dedup-by-URL) so a
mega-system can't blow the supervisor's prompt.

Order in returned list (kept stable so the render-block / aggregation
behaviour is deterministic across turns):

  1. Ancestors closest-first (immediate parent's scope_object → grandparent → ...)
  2. Active diagram's objects (BFS depth=0)
  3. Descendants BFS (depth=1, 2, ...)

Ancestor entries carry ``is_ancestor=True`` and ``depth=N`` where N is
the upward distance (1 = direct parent's scope_object, 2 = grandparent,
...). Descendant entries keep ``is_ancestor=False`` and ``depth=0/1/2``
matching the prior convention.

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
            "Distance from the active diagram. For descendants (and active "
            "level): 0 = active diagram, 1 = direct child diagram, 2 = "
            "grandchild. For ancestors (when ``is_ancestor=True``): 1 = the "
            "scope_object of the active diagram (i.e. the immediate parent "
            "Container/System), 2 = grandparent, 3 = great-grandparent. "
            "Surfaced for observability only — supervisor doesn't act on it."
        ),
    )
    is_ancestor: bool = Field(
        default=False,
        description=(
            "True when this entry came from the upward walk (ancestor "
            "diagrams' scope_objects). False for the active diagram's own "
            "objects and for descendants reached by the downward walk. "
            "Surfaced for observability — render block treats both kinds "
            "the same way."
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


async def _fetch_diagram_scope_object_id(
    diagram_id: UUID, db: AsyncSession
) -> UUID | None:
    """Return the ``scope_object_id`` of ``diagram_id``, or ``None`` when
    the diagram is a root (no decomposition target — e.g. a SystemLandscape).

    Used by the ancestor walk to step from a diagram up to the
    System / Container it decomposes.
    """
    stmt = (
        select(Diagram.scope_object_id).where(Diagram.id == diagram_id).limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _fetch_object_by_id(
    object_id: UUID, db: AsyncSession
) -> ModelObject | None:
    """Return the :class:`ModelObject` for ``object_id`` (or ``None`` when
    the row was deleted between the diagram lookup and now).

    Standalone fetch (no diagram_objects join) — used by the ancestor walk
    so the SQL pattern is distinguishable from the placement-listing
    query that joins ``diagram_objects``.
    """
    stmt = select(ModelObject).where(ModelObject.id == object_id).limit(1)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _fetch_parent_diagram_id(
    object_id: UUID, db: AsyncSession
) -> UUID | None:
    """Return the (first) diagram that contains ``object_id`` as a placed
    object, or ``None`` when the object is unplaced (= top of the chain).

    An object can technically be placed on multiple diagrams (e.g. a
    System rendered in both a SystemLandscape and a parent Group). We
    pick the first by diagram_id so the walk is deterministic; for the
    ancestor walk this is fine because the manifest is observational and
    we only need ONE upward path.
    """
    from app.models.diagram import DiagramObject

    stmt = (
        select(DiagramObject.diagram_id)
        .where(DiagramObject.object_id == object_id)
        .order_by(DiagramObject.diagram_id)
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _walk_ancestors_up(
    active_diagram_id: UUID,
    db: AsyncSession,
    *,
    max_depth: int = MAX_DEPTH,
) -> list[tuple[ModelObject, int]]:
    """Walk upward from ``active_diagram_id`` collecting repo-linked
    ancestor scope_objects.

    For each step:
      1. Fetch the current diagram's ``scope_object_id``. Stop when null
         (root diagram).
      2. Load the scope_object. If it carries ``repo_url`` AND its type
         is in :data:`REPO_LINKABLE_TYPES`, append ``(obj, depth)``.
      3. Find the parent diagram that contains the scope_object as a
         placed object (``DiagramObject.object_id == scope_object.id``).
      4. Stop when no parent placement exists, when we've taken
         ``max_depth`` steps, or when the parent diagram was already
         visited (cycle guard — defensively handled even though a cycle
         is structurally impossible in the live data).

    Returns ancestor entries CLOSEST-FIRST: the immediate parent's
    scope_object at index 0, grandparent at index 1, etc. Entries whose
    scope_object has no repo_url (or has a non-eligible type) are SKIPPED
    but the walk continues upward.
    """
    collected: list[tuple[ModelObject, int]] = []
    visited_diagrams: set[UUID] = {active_diagram_id}
    current_diagram_id: UUID | None = active_diagram_id

    for step in range(1, max_depth + 1):
        if current_diagram_id is None:
            break
        scope_object_id = await _fetch_diagram_scope_object_id(
            current_diagram_id, db
        )
        if scope_object_id is None:
            # Root diagram — no further upward chain.
            break
        scope_object = await _fetch_object_by_id(scope_object_id, db)
        if scope_object is None:
            # Dangling scope_object_id (FK ON DELETE SET NULL race) —
            # stop the walk, can't resolve further.
            break
        if (
            scope_object.repo_url is not None
            and scope_object.type in REPO_LINKABLE_TYPES
        ):
            collected.append((scope_object, step))
        # Step up: find which diagram contains this scope_object as a
        # placed object — that's the parent diagram.
        parent_diagram_id = await _fetch_parent_diagram_id(scope_object.id, db)
        if parent_diagram_id is None or parent_diagram_id in visited_diagrams:
            break
        visited_diagrams.add(parent_diagram_id)
        current_diagram_id = parent_diagram_id

    return collected


async def collect_repo_manifest(
    active_diagram_id: UUID | None, db: AsyncSession
) -> list[RepoLink]:
    """Walk the diagram tree in BOTH directions and return every
    repo-linked object visible from the active diagram.

    The walk has two passes (see module docstring for the full
    rationale):

      * Upward (ancestors): the active diagram's ``scope_object_id``,
        then the parent diagram's ``scope_object_id``, etc. Capped at
        :data:`MAX_DEPTH` upward steps. Closest-first ordering.
      * Downward (descendants): BFS over child diagrams via
        ``Diagram.scope_object_id == ModelObject.id``, mirroring the
        previous behaviour. Same :data:`MAX_DEPTH` cap.

    Returned ordering: ancestors (closest-first) → active level →
    descendants (BFS by depth). Ancestors carry ``is_ancestor=True``.

    Behaviour:
      * Cycle-guarded — visited diagram ids tracked in BOTH directions;
        revisits skipped silently.
      * Depth-capped at :data:`MAX_DEPTH` per direction (mirrors
        ``useDiagramBreadcrumbs`` frontend/src/hooks/use-diagrams.ts:104).
      * Total cap at :data:`MAX_MANIFEST_ENTRIES` across BOTH directions.
        When the cap is reached we stop the walk early and the renderer
        surfaces a truncation hint.
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
      * the active diagram and its ancestors / descendants carry no
        ``repo_url``,
      * any of the queries fails (defensive — repo manifest is opt-in,
        not load-bearing for the rest of the supervisor's flow).
    """
    if active_diagram_id is None:
        return []

    visited_diagrams: set[UUID] = set()

    # Pass 1a: walk UPWARD via scope_object_id chain. Ancestors come first
    # in the collected list (closest-first) so the render block lists the
    # most-relevant repo (= the immediate parent the active diagram
    # decomposes) before deeper-up or descendant entries. Failure here is
    # non-fatal — we degrade to the previous behaviour (descendants only).
    ancestor_collected: list[tuple[Any, int, bool]] = []  # (obj, depth, is_ancestor)
    try:
        for obj, step in await _walk_ancestors_up(
            active_diagram_id, db, max_depth=MAX_DEPTH
        ):
            ancestor_collected.append((obj, step, True))
    except Exception:  # noqa: BLE001 — ancestor walk is opt-in
        logger.warning(
            "collect_repo_manifest: ancestor walk failed for diagram=%s",
            active_diagram_id,
            exc_info=True,
        )

    # Pass 1b: walk the diagram tree DOWNWARD and collect every
    # (obj, depth) tuple that carries a repo link. We defer slug
    # assignment to pass 2 so we can decide owner-prefixed vs bare slugs
    # based on the global repo-name distribution (different owners with
    # same repo name → both owner-prefixed).
    descendant_collected: list[tuple[Any, int, bool]] = []  # (obj, depth, is_ancestor)

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
            # Total cap counts BOTH ancestors and descendants — the
            # supervisor's prompt budget cares about the merged list, not
            # whichever direction filled it.
            total_so_far = len(ancestor_collected) + len(descendant_collected)
            for obj in objects:
                # Surface the link if the object itself carries repo_url +
                # eligible type. Non-eligible types are skipped even when
                # the row carries a stale repo_url.
                if obj.repo_url is not None and obj.type in REPO_LINKABLE_TYPES:
                    if total_so_far >= MAX_MANIFEST_ENTRIES:
                        logger.info(
                            "collect_repo_manifest: total cap (%d) reached; "
                            "remaining objects skipped for diagram=%s",
                            MAX_MANIFEST_ENTRIES,
                            active_diagram_id,
                        )
                        break
                    descendant_collected.append((obj, depth, False))
                    total_so_far += 1

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
            if (
                len(ancestor_collected) + len(descendant_collected)
                >= MAX_MANIFEST_ENTRIES
            ):
                break
    except Exception:  # noqa: BLE001 — degrade gracefully
        logger.warning(
            "collect_repo_manifest: walk failed for diagram=%s",
            active_diagram_id,
            exc_info=True,
        )
        # Fall through with whatever we collected so the supervisor still
        # gets a partial manifest.

    # Compose the final ordered list: ancestors closest-first, then
    # descendants in BFS order (active level first, then level 1, ...).
    # This ordering is what render_repo_manifest_block (and the
    # aggregate-by-URL helper) consume — keep it stable so the supervisor
    # sees the same primary RepoLink for a given repo across turns.
    collected: list[tuple[Any, int, bool]] = (
        ancestor_collected + descendant_collected
    )

    # Pass 2: figure out which repo names need owner prefixing. A name
    # collides when two entries reference repos with the same kebab-name
    # but DIFFERENT canonical URLs (= different owners, or different
    # repos that happen to slugify the same). Same-URL duplicates are
    # NOT a collision — supervisor aggregates by URL later.
    name_to_urls: dict[str, set[str]] = {}
    parsed: list[tuple[Any, int, bool, str | None, str | None, str]] = []
    # Each entry: (obj, depth, is_ancestor, owner, repo_name, fallback_slug_base)
    for obj, depth, is_ancestor in collected:
        ownerrepo = _parse_owner_repo(obj.repo_url) if obj.repo_url else None
        if ownerrepo is not None:
            owner, repo_name = ownerrepo
            base_slug = _slugify(repo_name)
        else:
            # Malformed URL — keep the entry but fall back to node-name
            # slug; we never owner-prefix this case (no parsable owner).
            owner, repo_name = None, None
            base_slug = _slugify(obj.name)
        parsed.append((obj, depth, is_ancestor, owner, repo_name, base_slug))
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
    for obj, depth, is_ancestor, owner, repo_name, base_slug in parsed:
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
                is_ancestor=is_ancestor,
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
