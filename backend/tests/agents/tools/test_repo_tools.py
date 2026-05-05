"""Tests for app/agents/tools/repo_tools.py.

Each tool is exercised via its handler with a mocked ``make_request`` so
the test suite stays offline. Errors from ``RepoCredentialsService`` are
mapped to structured ``{status: "error"}`` envelopes.
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from httpx import Request, Response

from app.agents.tools.base import ToolContext
from app.agents.tools.repo_tools import (
    REPO_TOOL_NAMES,
    RepoEmptyInput,
    RepoListTreeInput,
    RepoReadCommitsInput,
    RepoReadDiffInput,
    RepoReadFileInput,
    RepoSearchCodeInput,
    RepoStateFilterInput,
    repo_get_metadata,
    repo_list_tree,
    repo_read_commits,
    repo_read_diff,
    repo_read_file,
    repo_read_issues,
    repo_read_pulls,
    repo_read_readme,
    repo_search_code,
)
from app.services.repo_credentials_service import (
    GitHubAuthError,
    GitHubNotFoundError,
    GitHubRateLimitError,
    GitHubServerError,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@dataclass
class _FakeActor:
    kind: str = "user"
    id: UUID = None  # type: ignore[assignment]
    workspace_id: UUID = None  # type: ignore[assignment]
    scopes: tuple[str, ...] = ()
    role: Any = None


class _FakeSession:
    def add(self, _obj: Any) -> None:  # pragma: no cover — unused
        pass

    async def execute(self, *_a: Any, **_kw: Any) -> Any:  # pragma: no cover
        raise AssertionError("DB call must not happen in repo tool tests")

    async def flush(self) -> None:  # pragma: no cover
        pass


def _ctx(*, repo_url: str = "https://github.com/octocat/hello", branch: str = "main") -> ToolContext:
    ws = uuid4()
    return ToolContext(
        db=_FakeSession(),
        actor=_FakeActor(kind="user", id=uuid4(), workspace_id=ws),
        workspace_id=ws,
        chat_context={
            "kind": "diagram",
            "id": str(uuid4()),
            "repo_context": {"repo_url": repo_url, "repo_branch": branch},
        },
        session_id=uuid4(),
        agent_id="repo_researcher",
        agent_runtime_mode="full",
    )


def _resp(payload: Any, *, status: int = 200, text: str | None = None) -> Response:
    """Build a fake httpx.Response.

    ``payload`` is JSON-encoded by the response. Pass ``text=`` for raw-body
    responses (e.g. ``Accept: application/vnd.github.diff``). A synthetic
    ``Request`` instance is attached so ``raise_for_status`` doesn't trip
    on the missing-request guard.
    """
    body = text if text is not None else json.dumps(payload)
    resp = Response(status_code=status, text=body)
    resp.request = Request("GET", "https://api.github.com/_test")
    return resp


def _patch_make_request(side_effect: Any):
    """Convenience: patch make_request with the given side_effect / return."""
    return patch(
        "app.services.repo_credentials_service.make_request",
        new=AsyncMock(side_effect=side_effect),
    )


# ---------------------------------------------------------------------------
# Smoke / wiring
# ---------------------------------------------------------------------------


def test_repo_tool_names_exposes_nine_tools():
    assert len(REPO_TOOL_NAMES) == 9
    # All start with the repo_ prefix; matches what the LLM sees.
    assert all(n.startswith("repo_") for n in REPO_TOOL_NAMES)


# ---------------------------------------------------------------------------
# repo_get_metadata
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repo_get_metadata_happy_path():
    repo_payload = {
        "description": "hello world",
        "default_branch": "main",
        "topics": ["github", "octocat"],
        "stargazers_count": 42,
        "html_url": "https://github.com/octocat/hello",
        "full_name": "octocat/hello",
    }
    languages_payload = {"Python": 1234, "Markdown": 56}

    async def _fake(*_args, **kwargs):
        url = _args[3] if len(_args) > 3 else kwargs.get("url")
        if url.endswith("/languages"):
            return _resp(languages_payload)
        return _resp(repo_payload)

    with patch(
        "app.services.repo_credentials_service.lookup_repo",
        new=AsyncMock(return_value=repo_payload),
    ), _patch_make_request(_fake):
        result = await repo_get_metadata.handler(RepoEmptyInput(), _ctx())

    assert result["description"] == "hello world"
    assert result["default_branch"] == "main"
    assert result["languages"] == languages_payload
    assert result["topics"] == ["github", "octocat"]
    assert result["stargazers_count"] == 42
    assert result["html_url"].endswith("/octocat/hello")


@pytest.mark.asyncio
async def test_repo_get_metadata_auth_error_returns_envelope():
    with patch(
        "app.services.repo_credentials_service.lookup_repo",
        new=AsyncMock(side_effect=GitHubAuthError("token rejected")),
    ):
        result = await repo_get_metadata.handler(RepoEmptyInput(), _ctx())
    assert result == {
        "status": "error",
        "code": "github_auth",
        "message": "token rejected",
    }


@pytest.mark.asyncio
async def test_repo_get_metadata_not_found_returns_envelope():
    with patch(
        "app.services.repo_credentials_service.lookup_repo",
        new=AsyncMock(side_effect=GitHubNotFoundError("repo gone")),
    ):
        result = await repo_get_metadata.handler(RepoEmptyInput(), _ctx())
    assert result["status"] == "error"
    assert result["code"] == "github_not_found"


@pytest.mark.asyncio
async def test_repo_get_metadata_rate_limit_envelope():
    with patch(
        "app.services.repo_credentials_service.lookup_repo",
        new=AsyncMock(side_effect=GitHubRateLimitError("slow down")),
    ):
        result = await repo_get_metadata.handler(RepoEmptyInput(), _ctx())
    assert result["code"] == "github_rate_limit"


@pytest.mark.asyncio
async def test_repo_get_metadata_server_error_envelope():
    with patch(
        "app.services.repo_credentials_service.lookup_repo",
        new=AsyncMock(side_effect=GitHubServerError("502")),
    ):
        result = await repo_get_metadata.handler(RepoEmptyInput(), _ctx())
    assert result["code"] == "github_server"


@pytest.mark.asyncio
async def test_repo_get_metadata_missing_repo_context():
    """If chat_context has no repo_context block, the tool returns a structured
    error rather than crashing the run."""
    ctx = _ctx()
    # Strip the repo_context the helper installed.
    assert isinstance(ctx.chat_context, dict)
    ctx.chat_context.pop("repo_context", None)
    result = await repo_get_metadata.handler(RepoEmptyInput(), ctx)
    assert result["status"] == "error"
    assert result["code"] == "repo_context_missing"


# ---------------------------------------------------------------------------
# repo_read_readme
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repo_read_readme_decodes_base64():
    body = "# Hello\n\nA tiny readme.\n"
    payload = {
        "path": "README.md",
        "content": base64.b64encode(body.encode()).decode(),
        "html_url": "https://github.com/octocat/hello/blob/main/README.md",
    }
    with _patch_make_request(lambda *_a, **_kw: _resp(payload)):
        result = await repo_read_readme.handler(RepoEmptyInput(), _ctx())
    assert result["content"] == body
    assert result["truncated"] is False
    assert result["next_offset"] is None


@pytest.mark.asyncio
async def test_repo_read_readme_truncates_large_content():
    big = "x" * (60 * 1024)
    payload = {
        "path": "README.md",
        "content": base64.b64encode(big.encode()).decode(),
    }
    with _patch_make_request(lambda *_a, **_kw: _resp(payload)):
        result = await repo_read_readme.handler(RepoEmptyInput(), _ctx())
    assert result["truncated"] is True
    assert len(result["content"]) == 50 * 1024
    assert result["next_offset"] == 50 * 1024
    assert result["total_size"] == len(big)


# ---------------------------------------------------------------------------
# repo_list_tree
# ---------------------------------------------------------------------------


def _tree_payload(items: list[dict]) -> dict:
    return {"sha": "deadbeef", "tree": items}


@pytest.mark.asyncio
async def test_repo_list_tree_filters_by_depth_and_path():
    items = [
        {"path": "src", "type": "tree"},
        {"path": "src/main.py", "type": "blob", "size": 100},
        {"path": "src/lib", "type": "tree"},
        {"path": "src/lib/util.py", "type": "blob", "size": 50},
        {"path": "tests", "type": "tree"},
        {"path": "tests/test_x.py", "type": "blob", "size": 30},
    ]
    with _patch_make_request(lambda *_a, **_kw: _resp(_tree_payload(items))):
        result = await repo_list_tree.handler(
            RepoListTreeInput(path="src", depth=1, recursive=False),
            _ctx(),
        )
    paths = [e["path"] for e in result["entries"]]
    # depth=1, no recursion → only direct children of "src/"
    assert "src/main.py" in paths
    assert "src/lib" in paths
    assert "src/lib/util.py" not in paths


@pytest.mark.asyncio
async def test_repo_list_tree_recursive_flag_walks_subdirs():
    items = [
        {"path": "src", "type": "tree"},
        {"path": "src/a/b/c.py", "type": "blob", "size": 10},
    ]
    with _patch_make_request(lambda *_a, **_kw: _resp(_tree_payload(items))):
        result = await repo_list_tree.handler(
            RepoListTreeInput(path="src", depth=4, recursive=True),
            _ctx(),
        )
    paths = [e["path"] for e in result["entries"]]
    assert "src/a/b/c.py" in paths


@pytest.mark.asyncio
async def test_repo_list_tree_caps_at_500_entries():
    items = [
        {"path": f"f{i}.py", "type": "blob", "size": i}
        for i in range(600)
    ]
    with _patch_make_request(lambda *_a, **_kw: _resp(_tree_payload(items))):
        result = await repo_list_tree.handler(
            RepoListTreeInput(path="", depth=1),
            _ctx(),
        )
    assert result["truncated"] is True
    assert result["total_returned"] == 500


# ---------------------------------------------------------------------------
# repo_read_file
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repo_read_file_returns_decoded_slice():
    body = "line1\nline2\nline3\n"
    payload = {
        "size": len(body),
        "sha": "abc123",
        "content": base64.b64encode(body.encode()).decode(),
    }
    with _patch_make_request(lambda *_a, **_kw: _resp(payload)):
        result = await repo_read_file.handler(
            RepoReadFileInput(path="src/main.py", offset=0, limit=10),
            _ctx(),
        )
    assert result["content"] == body[:10]
    assert result["truncated"] is True
    assert result["has_more"] is True
    assert result["next_offset"] == 10
    assert result["total_size"] == len(body)


@pytest.mark.asyncio
async def test_repo_read_file_directory_returns_envelope():
    payload = [{"name": "a", "type": "dir"}]
    with _patch_make_request(lambda *_a, **_kw: _resp(payload)):
        result = await repo_read_file.handler(
            RepoReadFileInput(path="src"),
            _ctx(),
        )
    assert result["status"] == "error"
    assert result["code"] == "github_bad_target"


@pytest.mark.asyncio
async def test_repo_read_file_404_envelope():
    with _patch_make_request(lambda *_a, **_kw: _resp({}, status=404)):
        result = await repo_read_file.handler(
            RepoReadFileInput(path="nope"),
            _ctx(),
        )
    assert result["status"] == "error"
    assert result["code"] == "github_not_found"


# ---------------------------------------------------------------------------
# repo_search_code
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repo_search_code_projects_hits():
    items = [
        {
            "path": "src/auth.py",
            "name": "auth.py",
            "html_url": "https://github.com/octocat/hello/blob/main/src/auth.py",
            "score": 1.5,
            "text_matches": [
                {"fragment": "def login(): pass"}
            ],
        }
    ]
    with _patch_make_request(
        lambda *_a, **_kw: _resp(
            {"total_count": 1, "incomplete_results": False, "items": items}
        )
    ):
        result = await repo_search_code.handler(
            RepoSearchCodeInput(query="login"), _ctx()
        )
    assert result["total_count"] == 1
    assert len(result["hits"]) == 1
    assert result["hits"][0]["snippet"] == "def login(): pass"


# ---------------------------------------------------------------------------
# repo_read_issues
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repo_read_issues_drops_pull_requests():
    items = [
        {
            "number": 1,
            "title": "real issue",
            "body": "body",
            "state": "open",
            "labels": [{"name": "bug"}],
            "created_at": "2024-01-01T00:00:00Z",
            "html_url": "https://...",
        },
        {
            # PR — has a pull_request key per GitHub API; must be dropped.
            "number": 2,
            "title": "secret pr",
            "pull_request": {"url": "..."},
        },
    ]
    with _patch_make_request(lambda *_a, **_kw: _resp(items)):
        result = await repo_read_issues.handler(
            RepoStateFilterInput(state="open"), _ctx()
        )
    numbers = {i["number"] for i in result["issues"]}
    assert numbers == {1}


@pytest.mark.asyncio
async def test_repo_read_issues_truncates_long_body():
    long_body = "x" * 5000
    items = [
        {
            "number": 1,
            "title": "t",
            "body": long_body,
            "state": "open",
            "labels": [],
            "created_at": "2024-01-01T00:00:00Z",
            "html_url": "https://...",
        }
    ]
    with _patch_make_request(lambda *_a, **_kw: _resp(items)):
        result = await repo_read_issues.handler(
            RepoStateFilterInput(state="open"), _ctx()
        )
    issue = result["issues"][0]
    assert issue["body_truncated"] is True
    assert len(issue["body"]) == 2048


# ---------------------------------------------------------------------------
# repo_read_pulls / repo_read_commits / repo_read_diff
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repo_read_pulls_projects_diffstat_fields():
    items = [
        {
            "number": 7,
            "title": "feature",
            "body": "body",
            "state": "open",
            "head": {"ref": "feature"},
            "base": {"ref": "main"},
            "additions": 10,
            "deletions": 2,
            "changed_files": 1,
            "html_url": "https://...",
            "created_at": "2024-01-01",
        }
    ]
    with _patch_make_request(lambda *_a, **_kw: _resp(items)):
        result = await repo_read_pulls.handler(
            RepoStateFilterInput(state="open"), _ctx()
        )
    pull = result["pulls"][0]
    assert pull["head"] == "feature"
    assert pull["base"] == "main"
    assert pull["additions"] == 10
    assert pull["changed_files"] == 1


@pytest.mark.asyncio
async def test_repo_read_commits_projects_author_fields():
    items = [
        {
            "sha": "abc",
            "html_url": "https://...",
            "commit": {
                "message": "fix: auth",
                "author": {
                    "name": "Octo",
                    "email": "o@o.com",
                    "date": "2024-01-01T00:00:00Z",
                },
            },
        }
    ]
    with _patch_make_request(lambda *_a, **_kw: _resp(items)):
        result = await repo_read_commits.handler(
            RepoReadCommitsInput(path="src"), _ctx()
        )
    commit = result["commits"][0]
    assert commit["sha"] == "abc"
    assert commit["author"]["name"] == "Octo"
    assert commit["author"]["email"] == "o@o.com"


@pytest.mark.asyncio
async def test_repo_read_diff_caps_text_at_100kb():
    long_diff = "+a\n" * 60_000  # ~180KB
    with _patch_make_request(lambda *_a, **_kw: _resp({}, text=long_diff)):
        result = await repo_read_diff.handler(
            RepoReadDiffInput(base="main", head="feat"), _ctx()
        )
    assert result["truncated"] is True
    assert len(result["diff"]) == 100 * 1024


# ---------------------------------------------------------------------------
# Per-turn LRU cache
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repo_get_metadata_cache_avoids_second_http_call():
    """Two consecutive calls in the same turn share the per-turn cache."""
    repo_payload = {
        "description": "hi",
        "default_branch": "main",
        "topics": [],
        "stargazers_count": 1,
        "html_url": "x",
        "full_name": "x/y",
    }
    languages_payload = {"Python": 1}

    async def _fake(*_a, **_kw):
        url = _a[3] if len(_a) > 3 else _kw.get("url")
        if url.endswith("/languages"):
            return _resp(languages_payload)
        return _resp(repo_payload)

    ctx = _ctx()
    lookup_mock = AsyncMock(return_value=repo_payload)
    with patch(
        "app.services.repo_credentials_service.lookup_repo", new=lookup_mock
    ), _patch_make_request(_fake):
        await repo_get_metadata.handler(RepoEmptyInput(), ctx)
        await repo_get_metadata.handler(RepoEmptyInput(), ctx)
    # ``lookup_repo`` should be called exactly once thanks to the cache.
    assert lookup_mock.await_count == 1
