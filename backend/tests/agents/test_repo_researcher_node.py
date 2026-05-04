"""Tests for the repo_researcher node and its supervisor / graph integration.

Covers:
- ``REPO_RESEARCHER_TOOL_NAMES`` is the 9 ``repo_*`` tools and contains no
  mutating tools.
- ``make_repo_researcher_config`` resolves the registry and renders the
  prompt template with runtime placeholders.
- ``_build_repo_tool_schemas`` filters out forbidden / mutating tool names
  if any sneak into the registry (read-only enforcement).
- The graph's supervisor router maps ``delegate_to_git_researcher_<slug>``
  to the ``repo_researcher`` node.
- ``build_repo_delegation_tools`` renders one tool per manifest entry and
  the supervisor's brief extractor recognises it as ``repo:<slug>``.
- ``_resolve_repo_context_from_brief`` finds the matching manifest entry.
- The supervisor's repo manifest block renders empty when no manifest is
  present (graceful degradation when the workspace has no token).
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from app.agents.builtin.general.graph import (
    _DELEGATE_REPO_PREFIX,
    _resolve_repo_context_from_brief,
    _supervisor_routes_next,
)
from app.agents.builtin.general.manifest import RepoLink
from app.agents.builtin.general.nodes import supervisor as sv_module
from app.agents.builtin.general.nodes.repo_researcher import (
    REPO_RESEARCHER_TOOL_NAMES,
    _build_repo_tool_schemas,
    _is_forbidden_tool_name,
    make_repo_researcher_config,
    render_repo_researcher_prompt,
)
from app.agents.tools.repo_tools import REPO_TOOL_NAMES


@pytest.fixture(autouse=True)
def _ensure_repo_tools_registered():
    """Other tool tests call ``clear_tools()`` and re-register their own
    subset; we re-register the 9 ``repo_*`` handlers here so this file is
    insensitive to test ordering."""
    from app.agents.tools import repo_tools as _rt
    from app.agents.tools.base import Tool as _Tool, register_tool

    for attr in vars(_rt).values():
        if isinstance(attr, _Tool) and attr.name in REPO_TOOL_NAMES:
            register_tool(attr)
    yield


# ---------------------------------------------------------------------------
# Tool-name surface
# ---------------------------------------------------------------------------


def test_repo_researcher_tool_names_matches_registry_listing():
    assert tuple(REPO_RESEARCHER_TOOL_NAMES) == REPO_TOOL_NAMES


def test_repo_researcher_no_mutating_tool_names():
    """All declared tools must be read-only — no create/update/delete/place."""
    for name in REPO_RESEARCHER_TOOL_NAMES:
        assert not _is_forbidden_tool_name(name), (
            f"{name!r} matches a forbidden mutation prefix"
        )


# ---------------------------------------------------------------------------
# NodeConfig factory + prompt rendering
# ---------------------------------------------------------------------------


def _noop_executor(*_a, **_kw):  # pragma: no cover — placeholder
    raise AssertionError("tool executor must not be called in config tests")


def test_render_repo_researcher_prompt_substitutes_placeholders():
    text = render_repo_researcher_prompt(
        repo_url="https://github.com/acme/foo",
        repo_branch="develop",
        repo_node_name="Foo Service",
        repo_node_type="app",
    )
    assert "https://github.com/acme/foo" in text
    assert "develop" in text
    assert "Foo Service" in text
    assert "app" in text
    # Placeholder tokens must be gone.
    assert "{repo_url}" not in text
    assert "{repo_branch_display}" not in text
    assert "{repo_node_name}" not in text
    assert "{repo_node_type}" not in text


def test_render_repo_researcher_prompt_uses_default_branch_label_when_blank():
    text = render_repo_researcher_prompt(
        repo_url="https://github.com/acme/foo",
        repo_branch=None,
        repo_node_name="Foo",
        repo_node_type="system",
    )
    assert "(default branch)" in text


def test_make_repo_researcher_config_basics():
    cfg = make_repo_researcher_config(
        _noop_executor,
        repo_url="https://github.com/acme/foo",
        repo_branch="main",
        repo_node_name="Foo",
        repo_node_type="app",
    )
    assert cfg.name == "repo_researcher"
    assert cfg.output_schema is None  # free-form text
    assert cfg.enable_streaming is False
    # Tool schemas resolved from the registry — must be all 9 repo_* tools.
    tool_names = {
        (t.get("function") or {}).get("name") for t in cfg.tools
    }
    expected = set(REPO_TOOL_NAMES)
    assert tool_names == expected


# ---------------------------------------------------------------------------
# Read-only enforcer
# ---------------------------------------------------------------------------


def test_build_repo_tool_schemas_drops_planted_mutation_name(monkeypatch):
    """If a developer accidentally adds a write tool to ``REPO_TOOL_NAMES``,
    the schema builder filters it out instead of letting it reach the LLM.
    """
    from app.agents.builtin.general.nodes import repo_researcher as rr

    # Patch the in-memory list to include a forbidden name; ``_build_repo_tool_schemas``
    # must filter it out without raising.
    monkeypatch.setattr(
        rr,
        "REPO_RESEARCHER_TOOL_NAMES",
        list(REPO_TOOL_NAMES) + ["delete_object"],
        raising=True,
    )
    schemas = _build_repo_tool_schemas()
    names = {(s.get("function") or {}).get("name") for s in schemas}
    assert "delete_object" not in names


# ---------------------------------------------------------------------------
# Supervisor brief extraction + dynamic tool building
# ---------------------------------------------------------------------------


def test_build_repo_delegation_tools_renders_one_per_unique_repo_url():
    """Each unique repo URL produces exactly one
    ``delegate_to_git_researcher_<slug>`` tool. Tool name carries the new
    git-researcher prefix so the supervisor LLM can't confuse it with
    the plain ``delegate_to_researcher`` (which has no git access)."""
    state = {
        "repo_manifest": [
            {
                "node_id": str(uuid4()),
                "node_name": "Auth",
                "node_type": "app",
                "repo_url": "https://github.com/acme/auth",
                "repo_branch": "main",
                "slug": "auth",
            },
            {
                "node_id": str(uuid4()),
                "node_name": "Billing",
                "node_type": "system",
                "repo_url": "https://github.com/acme/billing",
                "repo_branch": None,
                "slug": "billing",
            },
        ]
    }
    tools = sv_module.build_repo_delegation_tools(state)  # type: ignore[arg-type]
    names = {(t.get("function") or {}).get("name") for t in tools}
    assert names == {
        "delegate_to_git_researcher_auth",
        "delegate_to_git_researcher_billing",
    }


def test_build_repo_delegation_tools_aggregates_same_repo_url():
    """When two manifest entries share a repo URL (same repo linked from
    two diagram nodes), the supervisor sees ONE tool whose description
    lists both linked components."""
    same_url = "https://github.com/my-org/auth-service"
    state = {
        "repo_manifest": [
            {
                "node_id": str(uuid4()),
                "node_name": "AuthService",
                "node_type": "app",
                "repo_url": same_url,
                "repo_branch": "main",
                "slug": "auth-service",
            },
            {
                "node_id": str(uuid4()),
                "node_name": "AuthGateway",
                "node_type": "app",
                "repo_url": same_url,
                "repo_branch": "main",
                "slug": "auth-service",
            },
        ]
    }
    tools = sv_module.build_repo_delegation_tools(state)  # type: ignore[arg-type]
    names = [(t.get("function") or {}).get("name") for t in tools]
    # ONE tool emitted for the shared repo URL.
    assert names == ["delegate_to_git_researcher_auth-service"]
    desc = (tools[0].get("function") or {}).get("description") or ""
    # Both linked components surface in the description.
    assert "AuthService" in desc
    assert "AuthGateway" in desc
    # And the connector matches the multi-component spec example.
    assert "and" in desc.lower()


def test_supervisor_sees_multiple_repo_targets():
    """D3: with three manifest entries the supervisor must see three
    distinct ``delegate_to_git_researcher_<slug>`` tools — one per entry — and the
    rendered system block must list all three."""
    state = {
        "repo_manifest": [
            {
                "node_id": str(uuid4()),
                "node_name": "Auth Service",
                "node_type": "app",
                "repo_url": "https://github.com/acme/auth",
                "repo_branch": "main",
                "slug": "auth-service",
            },
            {
                "node_id": str(uuid4()),
                "node_name": "Billing System",
                "node_type": "system",
                "repo_url": "https://github.com/acme/billing",
                "repo_branch": None,
                "slug": "billing-system",
            },
            {
                "node_id": str(uuid4()),
                "node_name": "Data Warehouse",
                "node_type": "store",
                "repo_url": "https://github.com/acme/dwh",
                "repo_branch": "develop",
                "slug": "data-warehouse",
            },
        ]
    }
    tools = sv_module.build_repo_delegation_tools(state)  # type: ignore[arg-type]
    names = {(t.get("function") or {}).get("name") for t in tools}
    assert names == {
        "delegate_to_git_researcher_auth-service",
        "delegate_to_git_researcher_billing-system",
        "delegate_to_git_researcher_data-warehouse",
    }
    # System block lists every entry by slug.
    block = sv_module.render_repo_manifest_block(state)  # type: ignore[arg-type]
    assert "repo:auth-service" in block
    assert "repo:billing-system" in block
    assert "repo:data-warehouse" in block
    # Tool descriptions carry the per-repo metadata so the LLM doesn't
    # need to cross-reference the system block at delegation time.
    descs = {
        (t.get("function") or {}).get("name"): (t.get("function") or {}).get("description")
        for t in tools
    }
    assert "acme/auth" in descs["delegate_to_git_researcher_auth-service"]
    assert "acme/billing" in descs["delegate_to_git_researcher_billing-system"]
    assert "acme/dwh" in descs["delegate_to_git_researcher_data-warehouse"]


def test_supervisor_resolves_correct_repo_context_for_each_slug():
    """Three separate ``delegate_to_git_researcher_<slug>`` calls each route to the
    matching manifest entry — no cross-talk, each delegation gets the
    right repo_url / repo_branch / node_name."""
    auth_id, billing_id, dwh_id = str(uuid4()), str(uuid4()), str(uuid4())
    manifest = [
        {
            "node_id": auth_id,
            "node_name": "Auth Service",
            "node_type": "app",
            "repo_url": "https://github.com/acme/auth",
            "repo_branch": "main",
            "slug": "auth-service",
        },
        {
            "node_id": billing_id,
            "node_name": "Billing System",
            "node_type": "system",
            "repo_url": "https://github.com/acme/billing",
            "repo_branch": None,
            "slug": "billing-system",
        },
        {
            "node_id": dwh_id,
            "node_name": "Data Warehouse",
            "node_type": "store",
            "repo_url": "https://github.com/acme/dwh",
            "repo_branch": "develop",
            "slug": "data-warehouse",
        },
    ]
    expected = {
        "auth-service": ("https://github.com/acme/auth", "main", "Auth Service", "app"),
        "billing-system": ("https://github.com/acme/billing", None, "Billing System", "system"),
        "data-warehouse": ("https://github.com/acme/dwh", "develop", "Data Warehouse", "store"),
    }
    for slug, (repo_url, branch, node_name, node_type) in expected.items():
        state = {
            "delegate_brief": {
                "kind": f"repo:{slug}",
                "instruction": "explain it",
                "reason": None,
            },
            "repo_manifest": manifest,
        }
        rc = _resolve_repo_context_from_brief(state)  # type: ignore[arg-type]
        assert rc is not None, f"failed to resolve repo:{slug}"
        assert rc["slug"] == slug
        assert rc["repo_url"] == repo_url
        assert rc["repo_branch"] == branch
        assert rc["repo_node_name"] == node_name
        assert rc["repo_node_type"] == node_type


def test_supervisor_brief_extractor_recognises_repo_delegation():
    messages = [
        {"role": "user", "content": "describe auth"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {
                        "name": "delegate_to_git_researcher_auth",
                        "arguments": '{"question": "summarise the auth service"}',
                    },
                }
            ],
        },
    ]
    brief = sv_module._extract_delegate_brief(messages)
    assert brief == {
        "kind": "repo:auth",
        "instruction": "summarise the auth service",
        "reason": None,
    }


def test_supervisor_router_directs_repo_delegate_to_repo_researcher():
    state = {
        "messages": [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {
                            "name": "delegate_to_git_researcher_auth",
                            "arguments": "{}",
                        },
                    }
                ],
            },
        ]
    }
    assert _supervisor_routes_next(state) == "repo_researcher"
    # Sanity: the prefix constant matches the new git-researcher form.
    assert _DELEGATE_REPO_PREFIX == "delegate_to_git_researcher_"


def test_supervisor_router_falls_back_when_repo_manifest_unknown():
    """Even with no manifest in state, the router still dispatches to
    ``repo_researcher`` — the node itself decides whether the slug is
    resolvable. This keeps the routing decision pure-functional.
    """
    state = {
        "messages": [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {
                            "name": "delegate_to_git_researcher_unknown",
                            "arguments": "{}",
                        },
                    }
                ],
            },
        ]
    }
    assert _supervisor_routes_next(state) == "repo_researcher"


# ---------------------------------------------------------------------------
# repo_context resolver
# ---------------------------------------------------------------------------


def test_resolve_repo_context_finds_matching_manifest_entry():
    state = {
        "delegate_brief": {"kind": "repo:auth", "instruction": "x", "reason": None},
        "repo_manifest": [
            {
                "node_id": str(uuid4()),
                "node_name": "Auth",
                "node_type": "app",
                "repo_url": "https://github.com/acme/auth",
                "repo_branch": "main",
                "slug": "auth",
            }
        ],
    }
    rc = _resolve_repo_context_from_brief(state)  # type: ignore[arg-type]
    assert rc is not None
    assert rc["repo_url"] == "https://github.com/acme/auth"
    assert rc["repo_branch"] == "main"
    assert rc["repo_node_name"] == "Auth"
    assert rc["repo_node_type"] == "app"
    assert rc["slug"] == "auth"


def test_resolve_repo_context_returns_none_when_slug_missing():
    state = {
        "delegate_brief": {"kind": "repo:nope", "instruction": "x", "reason": None},
        "repo_manifest": [
            {
                "node_id": str(uuid4()),
                "node_name": "Auth",
                "node_type": "app",
                "repo_url": "https://github.com/acme/auth",
                "slug": "auth",
            }
        ],
    }
    assert _resolve_repo_context_from_brief(state) is None  # type: ignore[arg-type]


def test_resolve_repo_context_returns_none_for_non_repo_kind():
    state = {
        "delegate_brief": {"kind": "researcher", "instruction": "x", "reason": None},
        "repo_manifest": [],
    }
    assert _resolve_repo_context_from_brief(state) is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Supervisor manifest system block
# ---------------------------------------------------------------------------


def test_supervisor_manifest_block_empty_when_no_links():
    """No token / no repos → block renders nothing → supervisor sees no
    repo:* targets in its prompt (graceful degradation per spec §5)."""
    state = {"repo_manifest": []}
    assert sv_module.render_repo_manifest_block(state) == ""  # type: ignore[arg-type]


def test_supervisor_manifest_block_renders_when_populated():
    state = {
        "repo_manifest": [
            {
                "node_id": str(uuid4()),
                "node_name": "Auth Service",
                "node_type": "app",
                "repo_url": "https://github.com/acme/auth",
                "repo_branch": "main",
                "slug": "auth-service",
            }
        ]
    }
    out = sv_module.render_repo_manifest_block(state)  # type: ignore[arg-type]
    assert "AVAILABLE REPO RESEARCHERS" in out
    assert "repo:auth-service" in out


# ---------------------------------------------------------------------------
# RepoLink Pydantic model sanity
# ---------------------------------------------------------------------------


def test_repo_link_round_trips_through_dict():
    link = RepoLink(
        node_id=uuid4(),
        node_name="Auth",
        node_type="app",
        repo_url="https://github.com/acme/auth",
        repo_branch="main",
        slug="auth",
    )
    dumped = link.model_dump(mode="json")
    rebuilt = RepoLink.model_validate(dumped)
    assert rebuilt == link


# ---------------------------------------------------------------------------
# Forbidden type guard
# ---------------------------------------------------------------------------


def test_repo_link_rejects_non_repo_linkable_type():
    """The literal type guard prevents component / actor types from
    accidentally landing in the manifest."""
    with pytest.raises(Exception):  # noqa: PT011
        RepoLink(
            node_id=uuid4(),
            node_name="Bad",
            node_type="component",  # type: ignore[arg-type]
            repo_url="https://github.com/acme/bad",
            slug="bad",
        )
