"""Tests for app/agents/builtin/general/manifest.py.

Covers:
- Slug derivation (kebab-case from REPO NAME, ASCII fallback).
- Owner-prefixed slugs when two manifest entries reference different-owner
  repos with the same name.
- Filtering: only system / app / store types are exposed.
- Render block: empty manifest → empty string; populated → block markdown.
- D3 recursive walk: descendants surfaced, depth cap, cycle guard,
  total-entries cap, slug derivation across depths.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from app.agents.builtin.general.manifest import (
    MAX_DEPTH,
    MAX_MANIFEST_ENTRIES,
    RepoLink,
    _disambiguate,
    _slugify,
    collect_repo_manifest,
    render_repo_manifest_block,
)
from app.models.object import ObjectType


# ---------------------------------------------------------------------------
# Slug helpers
# ---------------------------------------------------------------------------


def test_slugify_kebab_lowercases_and_replaces_punctuation():
    assert _slugify("Auth Service") == "auth-service"
    assert _slugify("Auth/Service v2") == "auth-service-v2"
    assert _slugify("AUTH-SERVICE") == "auth-service"


def test_slugify_strips_non_alphanumeric_runs():
    assert _slugify("user@inc.com") == "user-inc-com"


def test_slugify_falls_back_to_repo_for_empty_input():
    assert _slugify("") == "repo"
    assert _slugify("   ") == "repo"
    assert _slugify("...") == "repo"


def test_disambiguate_keeps_unique_slugs():
    used: set[str] = set()
    nid = UUID(int=0xABCDEFAB_CDEF_4567_89AB_CDEF12345678)
    assert _disambiguate("auth", used, nid) == "auth"


def test_disambiguate_appends_short_uuid_on_collision():
    used: set[str] = {"auth"}
    nid = UUID(int=0xABCDEFAB_CDEF_4567_89AB_CDEF12345678)
    out = _disambiguate("auth", used, nid)
    assert out.startswith("auth-")
    # The 4-char fragment is hex from the uuid.
    assert len(out) == len("auth-") + 4


# ---------------------------------------------------------------------------
# collect_repo_manifest — fixtures
# ---------------------------------------------------------------------------


class _FakeObject:
    def __init__(
        self,
        *,
        name: str,
        type: ObjectType,
        repo_url: str | None = None,
        repo_branch: str | None = None,
        id: UUID | None = None,
    ) -> None:
        self.id = id or uuid4()
        self.name = name
        self.type = type
        self.repo_url = repo_url
        self.repo_branch = repo_branch


class _ScalarsResult:
    """Mimic the SQLAlchemy ``Result.scalars().all()`` chain."""

    def __init__(self, items: list[Any]) -> None:
        self._items = list(items)

    def all(self) -> list[Any]:
        return list(self._items)


class _ListResult:
    def __init__(self, items: list[Any]) -> None:
        self._items = list(items)

    def scalars(self) -> _ScalarsResult:
        return _ScalarsResult(self._items)


class _ScalarResult:
    """Mimic the ``Result.scalar_one_or_none()`` shape used by the
    child-diagram-id lookup query."""

    def __init__(self, value: Any | None) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any | None:
        return self._value


class _FakeTreeSession:
    """Sessions that handle every query the manifest walk emits:

      1. Diagram-objects placement listing — returns objects placed on a
         diagram (SQL: ``FROM model_objects JOIN diagram_objects``).
      2. Child-diagram-id lookup — diagram whose ``scope_object_id``
         matches a given object id (SQL: ``FROM diagrams WHERE
         scope_object_id``).
      3. (D3 bidirectional) Diagram scope_object_id lookup — the
         ``scope_object_id`` of a given diagram (SQL: ``FROM diagrams
         WHERE id``).
      4. (D3 bidirectional) Object-by-id fetch — the ModelObject row
         matching an id (SQL: ``FROM model_objects WHERE id``, no join).
      5. (D3 bidirectional) Parent-diagram-of-object lookup — the
         diagram that contains an object as a placed entity (SQL:
         ``FROM diagram_objects WHERE object_id``).

    The walk dispatches on the SQL string the production code generates;
    we use coarse heuristics (which ``FROM`` table appears, presence of a
    join, which UUID parameter is bound) which are robust for the
    in-process tests we run here.

    Optional kwargs:
      * ``scope_object_of_diagram``: ``{diagram_id: scope_object_id}`` —
        what query 3 returns. Missing entries return ``None`` (= root
        diagram, ancestor walk stops).
      * ``object_by_id``: ``{object_id: _FakeObject}`` — what query 4
        returns. Missing entries return ``None``.
      * ``parent_diagram_of_object``: ``{object_id: diagram_id}`` — what
        query 5 returns. Missing entries return ``None`` (= unplaced).
    """

    def __init__(
        self,
        *,
        diagram_objects: dict[UUID, list[_FakeObject]],
        child_diagram_of_object: dict[UUID, UUID],
        scope_object_of_diagram: dict[UUID, UUID] | None = None,
        object_by_id: dict[UUID, _FakeObject] | None = None,
        parent_diagram_of_object: dict[UUID, UUID] | None = None,
    ) -> None:
        self._objects_by_diagram = diagram_objects
        self._child_by_object = child_diagram_of_object
        self._scope_of_diagram = scope_object_of_diagram or {}
        self._object_by_id = object_by_id or {}
        self._parent_of_object = parent_diagram_of_object or {}
        self.call_count = 0
        self.execute = AsyncMock(side_effect=self._execute)

    async def _execute(self, stmt) -> Any:
        self.call_count += 1
        sql = str(stmt).lower()
        # Object-list query joins diagram_objects and filters by diagram_id.
        # Match this BEFORE the bare ``from model_objects`` branch so the
        # join-form is handled correctly.
        if "join diagram_objects" in sql:
            diagram_id = _extract_uuid_param(stmt, "diagram_id")
            return _ListResult(self._objects_by_diagram.get(diagram_id, []))
        # Parent-diagram-of-object query: ``FROM diagram_objects`` with
        # ``WHERE object_id = ...``. Distinct from the join-form above.
        if "from diagram_objects" in sql:
            object_id = _extract_uuid_param(stmt, "object_id")
            parent_id = self._parent_of_object.get(object_id)
            return _ScalarResult(parent_id)
        # Diagram-targeted queries: either the child-diagram-id lookup
        # (WHERE scope_object_id = ...) or the diagram scope_object_id
        # lookup (WHERE id = ...). Distinguish by which column is bound.
        if "from diagrams" in sql:
            if "where diagrams.scope_object_id" in sql:
                object_id = _extract_uuid_param(stmt, "scope_object_id")
                child_id = self._child_by_object.get(object_id)
                return _ScalarResult(child_id)
            if "where diagrams.id" in sql:
                diagram_id = _extract_uuid_param(stmt, "id")
                return _ScalarResult(self._scope_of_diagram.get(diagram_id))
            # Fallback (shouldn't fire): treat as the legacy scope-object
            # lookup so the test still degrades gracefully.
            object_id = _extract_uuid_param(stmt, "scope_object_id")
            return _ScalarResult(self._child_by_object.get(object_id))
        # Standalone object-by-id fetch: ``FROM model_objects`` with no
        # diagram_objects join. Comes AFTER the join check above so the
        # placement listing wins when both patterns would match.
        if "from model_objects" in sql:
            object_id = _extract_uuid_param(stmt, "id")
            return _ScalarResult(self._object_by_id.get(object_id))
        # Fallback: empty.
        return _ListResult([])


def _extract_uuid_param(stmt, hint: str) -> UUID | None:
    """Pull the bound parameter value matching ``hint`` from a SQLAlchemy
    Select. We don't compile the statement; we walk
    ``stmt.compile().params`` and find the first UUID-typed param whose
    key contains the hint string. This is brittle for production code but
    fine for the in-process tests where we control all the queries.
    """
    try:
        compiled = stmt.compile()
        params = compiled.params or {}
    except Exception:  # pragma: no cover — defensive
        return None
    for key, value in params.items():
        if hint not in key:
            continue
        if isinstance(value, UUID):
            return value
        if isinstance(value, str):
            try:
                return UUID(value)
            except ValueError:
                continue
    # Fallback: first UUID-shaped value.
    for value in params.values():
        if isinstance(value, UUID):
            return value
    return None


# ---------------------------------------------------------------------------
# collect_repo_manifest — basic cases (D2 backwards-compat)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_collect_repo_manifest_returns_empty_for_no_diagram():
    session = _FakeTreeSession(diagram_objects={}, child_diagram_of_object={})
    out = await collect_repo_manifest(None, session)  # type: ignore[arg-type]
    assert out == []


@pytest.mark.asyncio
async def test_collect_repo_manifest_handles_db_failure():
    """Defensive: a query error returns whatever was already collected
    (empty list when nothing has been collected yet)."""
    session = _FakeTreeSession(diagram_objects={}, child_diagram_of_object={})
    session.execute = AsyncMock(side_effect=RuntimeError("db down"))
    out = await collect_repo_manifest(uuid4(), session)  # type: ignore[arg-type]
    assert out == []


@pytest.mark.asyncio
async def test_collect_repo_manifest_returns_links_for_eligible_objects():
    """Slugs come from the REPO NAME (the ``<name>`` part of
    ``<owner>/<name>``), NOT from the diagram node name. So a node named
    "Backend" linked to ``acme/auth-service`` slugifies to ``auth-service``
    — the repo-bound naming the LLM can match without re-deriving."""
    diagram_id = uuid4()
    objs = [
        _FakeObject(
            name="Backend",  # node name distinct from repo name
            type=ObjectType.APP,
            repo_url="https://github.com/acme/auth-service",
            repo_branch="main",
        ),
        _FakeObject(
            name="Billing Container",  # node name distinct from repo name
            type=ObjectType.SYSTEM,
            repo_url="https://github.com/acme/billing",
        ),
    ]
    session = _FakeTreeSession(
        diagram_objects={diagram_id: objs},
        child_diagram_of_object={},
    )
    out = await collect_repo_manifest(diagram_id, session)  # type: ignore[arg-type]
    assert len(out) == 2
    slugs = sorted(link.slug for link in out)
    assert slugs == ["auth-service", "billing"]
    types = sorted(link.node_type for link in out)
    assert types == ["app", "system"]
    # Every entry is reported at depth 0 (active diagram, no descent).
    assert {link.depth for link in out} == {0}


@pytest.mark.asyncio
async def test_collect_repo_manifest_distinct_repo_names_no_collision():
    """Two nodes with the same display name but DIFFERENT repo URLs (and
    different repo names) get distinct slugs derived from the repo names.
    No owner prefix is needed because the repo names already differ."""
    diagram_id = uuid4()
    obj_a = _FakeObject(
        name="Auth",
        type=ObjectType.APP,
        repo_url="https://github.com/acme/auth-1",
    )
    obj_b = _FakeObject(
        name="Auth",
        type=ObjectType.APP,
        repo_url="https://github.com/acme/auth-2",
    )
    session = _FakeTreeSession(
        diagram_objects={diagram_id: [obj_a, obj_b]},
        child_diagram_of_object={},
    )
    out = await collect_repo_manifest(diagram_id, session)  # type: ignore[arg-type]
    slugs = sorted(link.slug for link in out)
    # Repo names already disambiguate — slugs are clean repo names.
    assert slugs == ["auth-1", "auth-2"]


@pytest.mark.asyncio
async def test_collect_repo_manifest_owner_prefixes_same_name_different_owners():
    """Two repos with the SAME name from DIFFERENT owners → both slugs
    are owner-prefixed so the LLM can disambiguate at routing time."""
    diagram_id = uuid4()
    obj_a = _FakeObject(
        name="Auth Service A",
        type=ObjectType.APP,
        repo_url="https://github.com/my-org/auth-service",
    )
    obj_b = _FakeObject(
        name="Auth Service B",
        type=ObjectType.APP,
        repo_url="https://github.com/other-org/auth-service",
    )
    session = _FakeTreeSession(
        diagram_objects={diagram_id: [obj_a, obj_b]},
        child_diagram_of_object={},
    )
    out = await collect_repo_manifest(diagram_id, session)  # type: ignore[arg-type]
    slugs = sorted(link.slug for link in out)
    # Both colliding entries are owner-prefixed — neither keeps the bare
    # ``auth-service`` slug because that would still be ambiguous.
    assert slugs == ["my-org-auth-service", "other-org-auth-service"]


@pytest.mark.asyncio
async def test_collect_repo_manifest_same_url_two_nodes_keeps_one_slug():
    """When the SAME repo URL is linked to two diagram nodes, the manifest
    contains two RepoLink entries (preserving recursion + per-node depth
    metadata) but they SHARE one slug — the supervisor's tool builder
    aggregates by URL so the LLM sees one tool for the repo."""
    diagram_id = uuid4()
    same_url = "https://github.com/acme/auth-service"
    obj_a = _FakeObject(
        name="AuthService",
        type=ObjectType.APP,
        repo_url=same_url,
    )
    obj_b = _FakeObject(
        name="AuthGateway",
        type=ObjectType.APP,
        repo_url=same_url,
    )
    session = _FakeTreeSession(
        diagram_objects={diagram_id: [obj_a, obj_b]},
        child_diagram_of_object={},
    )
    out = await collect_repo_manifest(diagram_id, session)  # type: ignore[arg-type]
    assert len(out) == 2
    # Same slug for both entries — supervisor aggregates by URL.
    assert {link.slug for link in out} == {"auth-service"}
    assert {link.repo_url for link in out} == {same_url}


# ---------------------------------------------------------------------------
# D3: recursive descendant walk
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_collect_walks_descendants_to_depth_3():
    """Three-level chain (System → Container → Component diagram), each
    level placed on its own diagram, every scope-object carrying a repo
    link → all three repos surface in BFS order. Slugs come from the
    REPO NAME (not the node name), so a node "Billing System" linked to
    ``acme/billing`` slugifies to ``billing``."""
    diagram_l0 = uuid4()
    diagram_l1 = uuid4()
    diagram_l2 = uuid4()

    obj_system = _FakeObject(
        name="Billing System",
        type=ObjectType.SYSTEM,
        repo_url="https://github.com/acme/billing",
    )
    obj_container = _FakeObject(
        name="Billing API",
        type=ObjectType.APP,
        repo_url="https://github.com/acme/billing-api",
    )
    # depth=2 — child diagrams of containers usually hold components, but
    # a Container/store can still carry a repo so we use APP again here to
    # exercise the type-eligibility path at depth 2.
    obj_inner = _FakeObject(
        name="Billing Worker",
        type=ObjectType.APP,
        repo_url="https://github.com/acme/billing-worker",
    )

    session = _FakeTreeSession(
        diagram_objects={
            diagram_l0: [obj_system],
            diagram_l1: [obj_container],
            diagram_l2: [obj_inner],
        },
        child_diagram_of_object={
            obj_system.id: diagram_l1,
            obj_container.id: diagram_l2,
        },
    )

    out = await collect_repo_manifest(diagram_l0, session)  # type: ignore[arg-type]
    slugs = [link.slug for link in out]
    depths = [link.depth for link in out]
    assert slugs == ["billing", "billing-api", "billing-worker"]
    assert depths == [0, 1, 2]


@pytest.mark.asyncio
async def test_collect_caps_at_depth_3():
    """A 4-level chain only produces entries for the top 3 levels;
    anything at depth >= MAX_DEPTH is pruned."""
    assert MAX_DEPTH == 3  # sanity — test relies on the literal cap.
    d0, d1, d2, d3 = (uuid4() for _ in range(4))
    o0 = _FakeObject(name="L0", type=ObjectType.SYSTEM, repo_url="https://github.com/acme/l0")
    o1 = _FakeObject(name="L1", type=ObjectType.APP, repo_url="https://github.com/acme/l1")
    o2 = _FakeObject(name="L2", type=ObjectType.APP, repo_url="https://github.com/acme/l2")
    o3 = _FakeObject(name="L3", type=ObjectType.APP, repo_url="https://github.com/acme/l3")

    session = _FakeTreeSession(
        diagram_objects={d0: [o0], d1: [o1], d2: [o2], d3: [o3]},
        child_diagram_of_object={o0.id: d1, o1.id: d2, o2.id: d3},
    )
    out = await collect_repo_manifest(d0, session)  # type: ignore[arg-type]
    slugs = [link.slug for link in out]
    # L3 is below MAX_DEPTH and must NOT appear in the output.
    assert slugs == ["l0", "l1", "l2"]
    assert all(link.depth < MAX_DEPTH for link in out)


@pytest.mark.asyncio
async def test_collect_cycle_guard():
    """A → B → A child-diagram cycle: walk completes without infinite
    looping and does not duplicate entries."""
    d_a, d_b = uuid4(), uuid4()
    o_a = _FakeObject(name="A", type=ObjectType.SYSTEM, repo_url="https://github.com/acme/a")
    o_b = _FakeObject(name="B", type=ObjectType.SYSTEM, repo_url="https://github.com/acme/b")
    session = _FakeTreeSession(
        diagram_objects={d_a: [o_a], d_b: [o_b]},
        child_diagram_of_object={
            o_a.id: d_b,
            o_b.id: d_a,  # cycle — d_a → d_b → d_a
        },
    )
    out = await collect_repo_manifest(d_a, session)  # type: ignore[arg-type]
    slugs = sorted(link.slug for link in out)
    # Each repo appears exactly once, and we did not hang.
    assert slugs == ["a", "b"]
    assert len(out) == 2


@pytest.mark.asyncio
async def test_collect_caps_total_at_50_entries():
    """A wide tree with 60 repo-linked nodes only surfaces the first 50;
    the renderer's truncation hint signals the cut-off."""
    d0 = uuid4()
    objs = [
        _FakeObject(
            name=f"S{i:02d}",
            type=ObjectType.SYSTEM,
            repo_url=f"https://github.com/acme/s{i:02d}",
        )
        for i in range(60)
    ]
    session = _FakeTreeSession(
        diagram_objects={d0: objs},
        child_diagram_of_object={},
    )
    out = await collect_repo_manifest(d0, session)  # type: ignore[arg-type]
    assert len(out) == MAX_MANIFEST_ENTRIES
    # Renderer surfaces the truncation hint.
    block = render_repo_manifest_block(out)
    assert "first" in block.lower()
    assert str(MAX_MANIFEST_ENTRIES) in block


@pytest.mark.asyncio
async def test_collect_filters_non_eligible_types_at_depth():
    """A depth-1 group with a (malformed) repo_url is excluded; a depth-1
    store with a repo_url is included. Group is L2 conceptually but is
    not repo-linkable per service layer rules. Slug is derived from the
    repo NAME, not the node name."""
    d0, d1 = uuid4(), uuid4()
    o_root = _FakeObject(name="Root", type=ObjectType.SYSTEM)
    # Group: NOT in REPO_LINKABLE_TYPES → excluded even though repo_url is set.
    o_group = _FakeObject(
        name="Some Group",
        type=ObjectType.GROUP,
        repo_url="https://github.com/acme/should-not-surface",
    )
    o_store = _FakeObject(
        name="Postgres",
        type=ObjectType.STORE,
        repo_url="https://github.com/acme/postgres-config",
    )
    session = _FakeTreeSession(
        diagram_objects={d0: [o_root], d1: [o_group, o_store]},
        child_diagram_of_object={o_root.id: d1},
    )
    out = await collect_repo_manifest(d0, session)  # type: ignore[arg-type]
    slugs = sorted(link.slug for link in out)
    # Slug from REPO NAME (postgres-config), not node name (postgres).
    assert "postgres-config" in slugs
    # Group is filtered out regardless of slug.
    assert "should-not-surface" not in [link.repo_url for link in out]
    # Group never appears.
    assert all(link.node_name != "Some Group" for link in out)


@pytest.mark.asyncio
async def test_collect_distinct_repo_urls_no_owner_prefix_at_depth():
    """Two nodes named 'Auth Service' at different depths but linked to
    DIFFERENT repos (with different repo names) → each slug comes from
    its own repo name. No owner-prefixing is needed because the repo
    names already differ."""
    d0, d1 = uuid4(), uuid4()
    o_root = _FakeObject(
        name="Auth Service",
        type=ObjectType.SYSTEM,
        repo_url="https://github.com/acme/auth-l0",
    )
    o_inner = _FakeObject(
        name="Auth Service",
        type=ObjectType.APP,
        repo_url="https://github.com/acme/auth-l1",
    )
    session = _FakeTreeSession(
        diagram_objects={d0: [o_root], d1: [o_inner]},
        child_diagram_of_object={o_root.id: d1},
    )
    out = await collect_repo_manifest(d0, session)  # type: ignore[arg-type]
    slugs = [link.slug for link in out]
    # Slugs come from the repo names — no collision so no prefix needed.
    assert slugs[0] == "auth-l0"
    assert slugs[1] == "auth-l1"
    assert len(set(slugs)) == 2


# ---------------------------------------------------------------------------
# D3 (bidirectional): ancestor walk via scope_object_id chain
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_walks_ancestors_up_to_3_levels():
    """Three-level ancestor chain (SystemLandscape root → Container child →
    Component grandchild). User opens the grandchild diagram. The
    Container scope_object carries a repo. The manifest must surface
    that repo with ``is_ancestor=True`` and ``depth=1`` (= the immediate
    scope_object of the grandchild = the Container)."""
    diagram_root = uuid4()  # System Landscape (root)
    diagram_container = uuid4()  # Frontend Components (active)

    # The Container scope_object — carries a repo.
    obj_container = _FakeObject(
        name="Frontend",
        type=ObjectType.APP,
        repo_url="https://github.com/me/frontend",
    )

    session = _FakeTreeSession(
        diagram_objects={
            # Active diagram has no objects (leaf — components don't link
            # to repos in this scenario).
            diagram_container: [],
            diagram_root: [obj_container],
        },
        child_diagram_of_object={},
        scope_object_of_diagram={
            diagram_container: obj_container.id,
            diagram_root: None,  # explicit None tolerated
        },
        object_by_id={obj_container.id: obj_container},
        parent_diagram_of_object={obj_container.id: diagram_root},
    )
    out = await collect_repo_manifest(diagram_container, session)  # type: ignore[arg-type]
    assert len(out) == 1
    entry = out[0]
    assert entry.slug == "frontend"
    assert entry.is_ancestor is True
    # depth=1 = immediate scope_object of the active diagram.
    assert entry.depth == 1
    assert entry.repo_url == "https://github.com/me/frontend"


@pytest.mark.asyncio
async def test_ancestor_walk_caps_at_3_levels():
    """A 4-level ancestor chain: from the deepest diagram, only the top 3
    ancestors are collected. The 4th-up scope_object is pruned."""
    assert MAX_DEPTH == 3
    # Build chain: d0 (root) ← obj_l1 placed on d0 ← d1 (decomposes obj_l1)
    # ← obj_l2 placed on d1 ← d2 ← obj_l3 placed on d2 ← d3 (active)
    # ← obj_l4 placed on … wait, we want 4 ANCESTOR levels above the active.
    # Active diagram = d_active. Ancestors:
    #   step 1 = scope_object of d_active = obj_a1 (placed on d_a1)
    #   step 2 = scope_object of d_a1 = obj_a2 (placed on d_a2)
    #   step 3 = scope_object of d_a2 = obj_a3 (placed on d_a3)
    #   step 4 = scope_object of d_a3 = obj_a4 — MUST NOT be collected.
    d_active, d_a1, d_a2, d_a3 = (uuid4() for _ in range(4))
    obj_a1 = _FakeObject(name="A1", type=ObjectType.APP, repo_url="https://github.com/me/a1")
    obj_a2 = _FakeObject(name="A2", type=ObjectType.APP, repo_url="https://github.com/me/a2")
    obj_a3 = _FakeObject(name="A3", type=ObjectType.APP, repo_url="https://github.com/me/a3")
    obj_a4 = _FakeObject(name="A4", type=ObjectType.APP, repo_url="https://github.com/me/a4")

    session = _FakeTreeSession(
        diagram_objects={d_active: []},
        child_diagram_of_object={},
        scope_object_of_diagram={
            d_active: obj_a1.id,
            d_a1: obj_a2.id,
            d_a2: obj_a3.id,
            d_a3: obj_a4.id,  # Would-be 4th level — never reached
        },
        object_by_id={
            obj_a1.id: obj_a1,
            obj_a2.id: obj_a2,
            obj_a3.id: obj_a3,
            obj_a4.id: obj_a4,
        },
        parent_diagram_of_object={
            obj_a1.id: d_a1,
            obj_a2.id: d_a2,
            obj_a3.id: d_a3,
        },
    )
    out = await collect_repo_manifest(d_active, session)  # type: ignore[arg-type]
    slugs = [link.slug for link in out]
    # Only top-3 ancestors surface. ``a4`` is below the cap and never
    # appears.
    assert slugs == ["a1", "a2", "a3"]
    assert all(link.is_ancestor for link in out)
    # depth values are 1 / 2 / 3 — closest-first ordering.
    assert [link.depth for link in out] == [1, 2, 3]


@pytest.mark.asyncio
async def test_root_diagram_has_no_ancestors():
    """When the active diagram is a root (``scope_object_id`` is null),
    the ancestor walk returns empty. No crash. Descendants still walk."""
    diagram_root = uuid4()
    obj = _FakeObject(
        name="Some System",
        type=ObjectType.SYSTEM,
        repo_url="https://github.com/me/some-system",
    )
    session = _FakeTreeSession(
        diagram_objects={diagram_root: [obj]},
        child_diagram_of_object={},
        scope_object_of_diagram={diagram_root: None},
        object_by_id={},
        parent_diagram_of_object={},
    )
    out = await collect_repo_manifest(diagram_root, session)  # type: ignore[arg-type]
    # No ancestors — but descendants (= the active level here) still
    # surface.
    assert len(out) == 1
    assert out[0].is_ancestor is False
    assert out[0].slug == "some-system"


@pytest.mark.asyncio
async def test_ancestor_with_no_repo_url_skipped_but_walk_continues():
    """Middle ancestor has no repo_url. The walk SKIPS it (no entry
    emitted) but continues upward and surfaces the further-up parent's
    repo at the correct depth."""
    d_active, d_a1, d_a2 = (uuid4() for _ in range(3))
    # Direct parent has NO repo — must not surface.
    obj_a1_no_repo = _FakeObject(
        name="Middle Container",
        type=ObjectType.APP,
        repo_url=None,
    )
    # Grandparent HAS a repo — must surface at depth=2.
    obj_a2_with_repo = _FakeObject(
        name="Top System",
        type=ObjectType.SYSTEM,
        repo_url="https://github.com/me/top-system",
    )
    session = _FakeTreeSession(
        diagram_objects={d_active: []},
        child_diagram_of_object={},
        scope_object_of_diagram={
            d_active: obj_a1_no_repo.id,
            d_a1: obj_a2_with_repo.id,
        },
        object_by_id={
            obj_a1_no_repo.id: obj_a1_no_repo,
            obj_a2_with_repo.id: obj_a2_with_repo,
        },
        parent_diagram_of_object={
            obj_a1_no_repo.id: d_a1,
            obj_a2_with_repo.id: d_a2,
        },
    )
    out = await collect_repo_manifest(d_active, session)  # type: ignore[arg-type]
    assert len(out) == 1
    entry = out[0]
    assert entry.slug == "top-system"
    assert entry.is_ancestor is True
    assert entry.depth == 2  # grandparent — middle is skipped


@pytest.mark.asyncio
async def test_ancestor_and_descendant_share_repo_url_aggregates():
    """The same repo URL is linked from BOTH an ancestor (the active
    diagram's scope_object, depth=1) AND a descendant of the active
    diagram. ``collect_repo_manifest`` returns two RepoLink entries (one
    per node), but they share the same slug, and the render block
    aggregates them into ONE bullet that lists both linked components."""
    d_active, d_parent, d_child = (uuid4() for _ in range(3))
    same_url = "https://github.com/me/shared"
    # Ancestor (active diagram's scope_object)
    obj_ancestor = _FakeObject(
        name="ParentContainer",
        type=ObjectType.APP,
        repo_url=same_url,
    )
    # Descendant: an object placed on the active diagram, linking to the
    # same repo.
    obj_descendant = _FakeObject(
        name="ChildLinker",
        type=ObjectType.APP,
        repo_url=same_url,
    )
    session = _FakeTreeSession(
        diagram_objects={
            d_active: [obj_descendant],
            d_parent: [obj_ancestor],
        },
        child_diagram_of_object={},
        scope_object_of_diagram={
            d_active: obj_ancestor.id,
        },
        object_by_id={obj_ancestor.id: obj_ancestor},
        parent_diagram_of_object={obj_ancestor.id: d_parent},
    )
    out = await collect_repo_manifest(d_active, session)  # type: ignore[arg-type]
    # Two RepoLink entries (one ancestor + one descendant) — but they
    # share a slug because supervisor aggregates by URL.
    assert len(out) == 2
    assert {link.slug for link in out} == {"shared"}
    # Ordering: ancestor first (closest-first), descendant second.
    assert out[0].is_ancestor is True
    assert out[1].is_ancestor is False
    # Render block emits ONE bullet listing both linked components.
    block = render_repo_manifest_block(out)
    assert block.count("repo:shared") == 1
    assert "ParentContainer" in block
    assert "ChildLinker" in block


@pytest.mark.asyncio
async def test_total_cap_50_after_combining_ancestor_active_descendant():
    """When ancestors + active-level entries together would exceed 50,
    the cap kicks in and additional entries are dropped — applies across
    BOTH directions, not per-direction."""
    # 3 ancestors with repos + 60 descendant-level repos = 63 candidate
    # entries; only 50 may surface.
    d_active, d_a1, d_a2, d_a3 = (uuid4() for _ in range(4))
    obj_a1 = _FakeObject(name="A1", type=ObjectType.APP, repo_url="https://github.com/me/anc1")
    obj_a2 = _FakeObject(name="A2", type=ObjectType.APP, repo_url="https://github.com/me/anc2")
    obj_a3 = _FakeObject(name="A3", type=ObjectType.APP, repo_url="https://github.com/me/anc3")
    descendants = [
        _FakeObject(
            name=f"D{i:02d}",
            type=ObjectType.SYSTEM,
            repo_url=f"https://github.com/me/d{i:02d}",
        )
        for i in range(60)
    ]
    session = _FakeTreeSession(
        diagram_objects={d_active: descendants},
        child_diagram_of_object={},
        scope_object_of_diagram={
            d_active: obj_a1.id,
            d_a1: obj_a2.id,
            d_a2: obj_a3.id,
        },
        object_by_id={
            obj_a1.id: obj_a1,
            obj_a2.id: obj_a2,
            obj_a3.id: obj_a3,
        },
        parent_diagram_of_object={
            obj_a1.id: d_a1,
            obj_a2.id: d_a2,
            obj_a3.id: d_a3,
        },
    )
    out = await collect_repo_manifest(d_active, session)  # type: ignore[arg-type]
    # Cap applies across the merged list.
    assert len(out) == MAX_MANIFEST_ENTRIES
    # Ancestors come first (closest-first), so all 3 are present even
    # under the cap — the cap eats descendants instead.
    ancestor_slugs = [link.slug for link in out if link.is_ancestor]
    assert ancestor_slugs == ["anc1", "anc2", "anc3"]
    # Render block surfaces the truncation hint.
    block = render_repo_manifest_block(out)
    assert str(MAX_MANIFEST_ENTRIES) in block
    assert "first" in block.lower()


@pytest.mark.asyncio
async def test_ancestor_walk_cycle_guard():
    """Defensive: if a misshapen tree caused d_a → d_b → d_a, the
    ancestor walk must terminate without looping. A cycle is structurally
    impossible in production but the guard means a corrupt DB row never
    hangs the supervisor."""
    d_active, d_other = uuid4(), uuid4()
    obj_a = _FakeObject(
        name="A",
        type=ObjectType.APP,
        repo_url="https://github.com/me/a",
    )
    obj_b = _FakeObject(
        name="B",
        type=ObjectType.APP,
        repo_url="https://github.com/me/b",
    )
    session = _FakeTreeSession(
        diagram_objects={d_active: []},
        child_diagram_of_object={},
        scope_object_of_diagram={
            d_active: obj_a.id,
            d_other: obj_b.id,
        },
        object_by_id={obj_a.id: obj_a, obj_b.id: obj_b},
        parent_diagram_of_object={
            obj_a.id: d_other,
            obj_b.id: d_active,  # cycle: d_active → d_other → d_active
        },
    )
    out = await collect_repo_manifest(d_active, session)  # type: ignore[arg-type]
    # Walk terminates and surfaces the two ancestor entries it found
    # before the cycle would have closed. (Each diagram visited at most
    # once.)
    assert len(out) == 2
    assert {link.slug for link in out} == {"a", "b"}


@pytest.mark.asyncio
async def test_ancestor_filters_non_eligible_types():
    """If an ancestor scope_object is a Group (non-eligible) with a
    stale repo_url, the entry is skipped but the walk continues to the
    next ancestor up."""
    d_active, d_parent = uuid4(), uuid4()
    obj_group = _FakeObject(
        name="Some Group",
        type=ObjectType.GROUP,  # NOT in REPO_LINKABLE_TYPES
        repo_url="https://github.com/me/should-not-surface",
    )
    session = _FakeTreeSession(
        diagram_objects={d_active: []},
        child_diagram_of_object={},
        scope_object_of_diagram={d_active: obj_group.id},
        object_by_id={obj_group.id: obj_group},
        parent_diagram_of_object={obj_group.id: d_parent},
    )
    out = await collect_repo_manifest(d_active, session)  # type: ignore[arg-type]
    # Group is filtered — the stale repo_url never reaches the manifest.
    assert out == []


# ---------------------------------------------------------------------------
# D3 (descendant): pre-existing tests (unaffected by ancestor walk)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_collect_owner_prefixes_when_same_repo_name_across_depths():
    """Two nodes at different depths linked to repos that SHARE a name
    but differ in owner → both slugs are owner-prefixed."""
    d0, d1 = uuid4(), uuid4()
    o_root = _FakeObject(
        name="Auth Service",
        type=ObjectType.SYSTEM,
        repo_url="https://github.com/my-org/auth-service",
    )
    o_inner = _FakeObject(
        name="Auth Service",
        type=ObjectType.APP,
        repo_url="https://github.com/other-org/auth-service",
    )
    session = _FakeTreeSession(
        diagram_objects={d0: [o_root], d1: [o_inner]},
        child_diagram_of_object={o_root.id: d1},
    )
    out = await collect_repo_manifest(d0, session)  # type: ignore[arg-type]
    slugs = [link.slug for link in out]
    assert slugs[0] == "my-org-auth-service"
    assert slugs[1] == "other-org-auth-service"


# ---------------------------------------------------------------------------
# render_repo_manifest_block
# ---------------------------------------------------------------------------


def test_render_block_empty_manifest_returns_empty_string():
    assert render_repo_manifest_block([]) == ""


def test_render_block_populated_manifest_lists_each_entry():
    links = [
        RepoLink(
            node_id=uuid4(),
            node_name="Auth Service",
            node_type="app",
            repo_url="https://github.com/acme/auth",
            repo_branch="main",
            slug="auth-service",
        ),
        RepoLink(
            node_id=uuid4(),
            node_name="Billing",
            node_type="system",
            repo_url="https://github.com/acme/billing",
            repo_branch=None,
            slug="billing",
        ),
    ]
    block = render_repo_manifest_block(links)
    assert "AVAILABLE REPO RESEARCHERS" in block
    assert "repo:auth-service" in block
    assert "repo:billing" in block
    # The default branch is rendered as ``(default)`` when no branch is set.
    assert "(default)" in block
    # The repo url is shortened (no https://github.com/ prefix in the line).
    assert "acme/auth" in block
    assert "https://github.com/acme/auth" not in block


def test_render_block_truncation_hint_when_capped():
    """When the manifest carries exactly MAX_MANIFEST_ENTRIES rows the
    renderer adds a truncation hint so the supervisor can mention the
    cut-off to the user."""
    links = [
        RepoLink(
            node_id=uuid4(),
            node_name=f"S{i:02d}",
            node_type="system",
            repo_url=f"https://github.com/acme/s{i:02d}",
            slug=f"s{i:02d}",
        )
        for i in range(MAX_MANIFEST_ENTRIES)
    ]
    block = render_repo_manifest_block(links)
    assert str(MAX_MANIFEST_ENTRIES) in block
    assert "first" in block.lower()
    # No hint when the list is below the cap.
    block_small = render_repo_manifest_block(links[:5])
    assert str(MAX_MANIFEST_ENTRIES) not in block_small


def test_render_block_aggregates_same_repo_url_across_nodes():
    """When two RepoLink entries share the same repo_url (= same repo
    linked from multiple diagram nodes), the renderer emits ONE bullet
    that lists every component the repo is linked to."""
    same_url = "https://github.com/acme/auth-service"
    links = [
        RepoLink(
            node_id=uuid4(),
            node_name="AuthService",
            node_type="app",
            repo_url=same_url,
            repo_branch="main",
            slug="auth-service",
        ),
        RepoLink(
            node_id=uuid4(),
            node_name="AuthGateway",
            node_type="app",
            repo_url=same_url,
            repo_branch="main",
            slug="auth-service",
        ),
    ]
    block = render_repo_manifest_block(links)
    # One bullet for the shared repo, mentioning both nodes.
    assert block.count("repo:auth-service") == 1
    assert "AuthService" in block
    assert "AuthGateway" in block
    # The new tool naming is referenced in the block intro.
    assert "delegate_to_git_researcher_" in block
