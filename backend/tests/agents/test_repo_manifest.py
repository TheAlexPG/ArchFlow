"""Tests for app/agents/builtin/general/manifest.py.

Covers:
- Slug derivation (kebab-case, ASCII fallback).
- Slug collision suffix when two nodes share a name.
- Filtering: only system / app / store types are exposed.
- Render block: empty manifest → empty string; populated → block markdown.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from app.agents.builtin.general.manifest import (
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
# collect_repo_manifest
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


class _FakeScalars:
    def __init__(self, items: list[Any]) -> None:
        self._items = list(items)

    def all(self) -> list[Any]:
        return list(self._items)


class _FakeResult:
    def __init__(self, items: list[Any]) -> None:
        self._items = list(items)

    def scalars(self) -> _FakeScalars:
        return _FakeScalars(self._items)


class _FakeSession:
    def __init__(self, items: list[Any]) -> None:
        self.execute = AsyncMock(return_value=_FakeResult(items))


@pytest.mark.asyncio
async def test_collect_repo_manifest_returns_empty_for_no_diagram():
    session = _FakeSession(items=[])
    out = await collect_repo_manifest(None, session)  # type: ignore[arg-type]
    assert out == []


@pytest.mark.asyncio
async def test_collect_repo_manifest_handles_db_failure():
    """Defensive: a query error returns an empty list, not a crash."""
    session = _FakeSession(items=[])
    session.execute = AsyncMock(side_effect=RuntimeError("db down"))
    out = await collect_repo_manifest(uuid4(), session)  # type: ignore[arg-type]
    assert out == []


@pytest.mark.asyncio
async def test_collect_repo_manifest_returns_links_for_eligible_objects():
    objs = [
        _FakeObject(
            name="Auth Service",
            type=ObjectType.APP,
            repo_url="https://github.com/acme/auth",
            repo_branch="main",
        ),
        _FakeObject(
            name="Billing System",
            type=ObjectType.SYSTEM,
            repo_url="https://github.com/acme/billing",
        ),
    ]
    session = _FakeSession(items=objs)
    out = await collect_repo_manifest(uuid4(), session)  # type: ignore[arg-type]
    assert len(out) == 2
    slugs = sorted(link.slug for link in out)
    assert slugs == ["auth-service", "billing-system"]
    types = sorted(link.node_type for link in out)
    assert types == ["app", "system"]


@pytest.mark.asyncio
async def test_collect_repo_manifest_disambiguates_collisions():
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
    session = _FakeSession(items=[obj_a, obj_b])
    out = await collect_repo_manifest(uuid4(), session)  # type: ignore[arg-type]
    slugs = sorted(link.slug for link in out)
    assert "auth" in slugs
    # The second one is suffixed with a 4-char uuid fragment.
    assert any(s.startswith("auth-") and len(s) == len("auth-") + 4 for s in slugs)


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
