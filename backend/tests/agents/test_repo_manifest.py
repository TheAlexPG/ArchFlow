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
    """Sessions that handle BOTH the diagram-objects query (returns objects
    placed on a diagram) and the child-diagram-id query (returns the id of
    a diagram whose ``scope_object_id`` equals a given object id).

    The walk dispatches on the SQL string the production code generates;
    we use a coarse heuristic (look for ``FROM diagrams`` vs
    ``FROM model_objects``) which is robust enough for the in-process
    tests we run here.
    """

    def __init__(
        self,
        *,
        diagram_objects: dict[UUID, list[_FakeObject]],
        child_diagram_of_object: dict[UUID, UUID],
    ) -> None:
        self._objects_by_diagram = diagram_objects
        self._child_by_object = child_diagram_of_object
        self.call_count = 0
        self.execute = AsyncMock(side_effect=self._execute)

    async def _execute(self, stmt) -> Any:
        self.call_count += 1
        sql = str(stmt).lower()
        # Object-list query joins diagram_objects and filters by diagram_id.
        if "from model_objects" in sql or "join diagram_objects" in sql:
            diagram_id = _extract_uuid_param(stmt, "diagram_id")
            return _ListResult(self._objects_by_diagram.get(diagram_id, []))
        # Child-diagram-id query selects from diagrams.
        if "from diagrams" in sql:
            object_id = _extract_uuid_param(stmt, "scope_object_id")
            child_id = self._child_by_object.get(object_id)
            return _ScalarResult(child_id)
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
