"""GitHub repo read-only tools used by the ``repo_researcher`` node.

Every tool here is read-only and authenticated via the workspace's stored
GitHub PAT (resolved by ``RepoCredentialsService``). The agent never types
the repo URL — ``repo_url`` and ``repo_branch`` are injected by the runtime
into ``ToolContext.chat_context['repo_context']`` when the supervisor
delegates to a ``repo:<slug>`` target.

Per-turn LRU cache:
    A small in-memory cache lives on ``chat_context['_repo_cache']``
    (a list of ``(key, value)`` tuples acting as an LRU, capped at 64
    entries). The runtime initialises it once per supervisor turn so two
    tool calls hitting the same path within one ReAct loop share results.

Error mapping: every ``GitHub*Error`` from ``RepoCredentialsService`` is
caught and translated into a structured ``{status: 'error', code, message}``
response. The ``execute_tool`` wrapper otherwise treats unhandled
exceptions as fatal — that would burn a step and surface an opaque message
to the LLM. Returning the structured payload lets the supervisor / sub-agent
recover (retry with a different path, switch tool, ask the user).
"""
from __future__ import annotations

import base64
import binascii
import json
import logging
from collections import OrderedDict
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.agents.tools.base import ToolContext, tool
from app.services import repo_credentials_service
from app.services.repo_credentials_service import (
    GitHubAuthError,
    GitHubNotFoundError,
    GitHubRateLimitError,
    GitHubServerError,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Hard caps that protect the LLM context window. The LLM still sees a
# truncation hint with the next-offset so it can request more if it needs
# to. Tuned so a single tool result fits well under ~25k context tokens.
_README_CHAR_LIMIT = 50 * 1024
_FILE_CHAR_LIMIT_DEFAULT = 50 * 1024
_TREE_ENTRY_LIMIT = 500
_DIFF_CHAR_LIMIT = 100 * 1024
_ISSUE_BODY_CHAR_LIMIT = 2048
_PR_BODY_CHAR_LIMIT = 2048

# Per-turn LRU cache cap.
_CACHE_MAX_ENTRIES = 64

# Mutation tool prefixes that the read-only enforcer rejects when wired
# into the repo_researcher tool list. Mirrors ``researcher.py``'s set.
_FORBIDDEN_TOOL_PREFIXES = (
    "create_",
    "update_",
    "delete_",
    "place_",
    "move_",
    "unplace_",
    "link_",
    "unlink_",
    "auto_layout_",
)


# ---------------------------------------------------------------------------
# Repo-context resolver + per-turn cache
# ---------------------------------------------------------------------------


class _RepoContextMissing(RuntimeError):
    """Raised when a repo tool is called outside a ``repo_researcher`` turn."""


def _resolve_repo_context(ctx: ToolContext) -> dict[str, str]:
    """Return ``{repo_url, repo_branch, owner, repo}`` for the active repo,
    decoded from ``ctx.chat_context['repo_context']``.

    Raises ``_RepoContextMissing`` when the runtime didn't inject the block —
    that always indicates a wiring bug (a non-repo node calling a repo tool),
    not an LLM problem, so the tool surfaces a structured error rather than
    crashing the run.
    """
    cc = ctx.chat_context if isinstance(ctx.chat_context, dict) else {}
    rc = cc.get("repo_context") if isinstance(cc, dict) else None
    if not isinstance(rc, dict):
        raise _RepoContextMissing(
            "repo tool invoked without chat_context['repo_context']"
        )
    repo_url = rc.get("repo_url")
    if not isinstance(repo_url, str) or not repo_url:
        raise _RepoContextMissing(
            "chat_context['repo_context'] is missing 'repo_url'"
        )
    branch = rc.get("repo_branch")
    if not isinstance(branch, str) or not branch:
        branch = ""  # resolved on first call via repo_get_metadata
    try:
        owner, name = repo_credentials_service.parse_repo_url(repo_url)
    except ValueError as exc:
        raise _RepoContextMissing(str(exc)) from exc
    return {
        "repo_url": repo_url,
        "repo_branch": branch,
        "owner": owner,
        "repo": name,
    }


def _cache(ctx: ToolContext) -> OrderedDict[tuple, Any]:
    """Get or create the per-turn LRU cache attached to ``chat_context``.

    Stores up to ``_CACHE_MAX_ENTRIES`` items; oldest evicted on overflow.
    Concurrent tool calls within one turn hit the same instance — the
    runtime resets it between supervisor visits.
    """
    cc = ctx.chat_context if isinstance(ctx.chat_context, dict) else None
    if cc is None:
        return OrderedDict()
    cache = cc.get("_repo_cache")
    if not isinstance(cache, OrderedDict):
        cache = OrderedDict()
        if isinstance(cc, dict):
            cc["_repo_cache"] = cache
    return cache


def _cache_get(ctx: ToolContext, key: tuple) -> Any | None:
    cache = _cache(ctx)
    if key in cache:
        cache.move_to_end(key)
        return cache[key]
    return None


def _cache_put(ctx: ToolContext, key: tuple, value: Any) -> None:
    cache = _cache(ctx)
    cache[key] = value
    cache.move_to_end(key)
    while len(cache) > _CACHE_MAX_ENTRIES:
        cache.popitem(last=False)


def _frozen_args(args: BaseModel) -> tuple:
    """Sort-stable tuple of args for cache keys (dict isn't hashable)."""
    return tuple(sorted(args.model_dump(exclude_none=True).items()))


# ---------------------------------------------------------------------------
# Error envelope
# ---------------------------------------------------------------------------


def _error_envelope(code: str, message: str) -> dict[str, Any]:
    """Structured error response — mirrors the shape used by ``web_fetch``."""
    return {"status": "error", "code": code, "message": message}


def _wrap_github_errors(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, GitHubAuthError):
        return _error_envelope("github_auth", str(exc))
    if isinstance(exc, GitHubNotFoundError):
        return _error_envelope("github_not_found", str(exc))
    if isinstance(exc, GitHubRateLimitError):
        return _error_envelope("github_rate_limit", str(exc))
    if isinstance(exc, GitHubServerError):
        return _error_envelope("github_server", str(exc))
    if isinstance(exc, _RepoContextMissing):
        return _error_envelope("repo_context_missing", str(exc))
    raise exc


async def _resolve_branch(ctx: ToolContext, repo_ctx: dict[str, str]) -> str:
    """Return ``repo_branch`` from context or resolve via metadata.

    The default branch lookup is itself cached for the rest of the turn.
    """
    if repo_ctx["repo_branch"]:
        return repo_ctx["repo_branch"]
    cache_key = ("__default_branch__", repo_ctx["owner"], repo_ctx["repo"])
    cached = _cache_get(ctx, cache_key)
    if isinstance(cached, str):
        repo_ctx["repo_branch"] = cached
        return cached
    branch = await repo_credentials_service.get_repo_default_branch(
        ctx.db, ctx.workspace_id, repo_ctx["owner"], repo_ctx["repo"]
    )
    _cache_put(ctx, cache_key, branch)
    repo_ctx["repo_branch"] = branch
    return branch


def _truncate(text: str, limit: int) -> tuple[str, bool]:
    """Truncate ``text`` to ``limit`` chars; return ``(out, was_truncated)``."""
    if len(text) <= limit:
        return text, False
    return text[:limit], True


# ---------------------------------------------------------------------------
# Tool input schemas
# ---------------------------------------------------------------------------


class RepoEmptyInput(BaseModel):
    """Tools that take no LLM-side args (repo_url is in runtime context)."""

    pass


class RepoListTreeInput(BaseModel):
    path: str = Field(
        "",
        description=(
            "Subpath to filter on (relative to repo root). Empty = repo root."
        ),
    )
    depth: int = Field(
        2,
        ge=1,
        le=8,
        description=(
            "Max directory depth from ``path``. Default 2 keeps responses "
            "compact on monorepos."
        ),
    )
    recursive: bool = Field(
        False,
        description=(
            "Walk every subdirectory up to ``depth``. When False, only "
            "entries directly under ``path`` are returned."
        ),
    )


class RepoReadFileInput(BaseModel):
    path: str = Field(..., description="File path relative to repo root.")
    offset: int = Field(0, ge=0, description="Starting char offset (decoded utf-8).")
    limit: int = Field(
        _FILE_CHAR_LIMIT_DEFAULT,
        ge=1,
        le=200 * 1024,
        description="Max chars to return after the offset (default 50KB).",
    )


class RepoSearchCodeInput(BaseModel):
    query: str = Field(..., min_length=1, max_length=256)


class RepoStateFilterInput(BaseModel):
    state: Literal["open", "closed", "all"] = "open"


class RepoReadCommitsInput(BaseModel):
    path: str | None = Field(
        None, description="Optional path to scope commits (e.g. 'src/auth')."
    )
    since: str | None = Field(
        None,
        description=(
            "ISO-8601 datetime (YYYY-MM-DDTHH:MM:SSZ) lower bound for commit date."
        ),
    )


class RepoReadDiffInput(BaseModel):
    base: str = Field(..., description="Base ref (commit sha, branch, or tag).")
    head: str = Field(..., description="Head ref (commit sha, branch, or tag).")


# ---------------------------------------------------------------------------
# Tool: repo_get_metadata
# ---------------------------------------------------------------------------


@tool(
    name="repo_get_metadata",
    description=(
        "Return summary metadata for the linked GitHub repo: description, "
        "default_branch, languages, topics, stars, html_url. Use first to "
        "ground yourself before exploring."
    ),
    input_schema=RepoEmptyInput,
    permission="workspace:read",
    permission_target="workspace",
    required_scope="agents:read",
    mutating=False,
)
async def repo_get_metadata(args: RepoEmptyInput, ctx: ToolContext) -> dict:
    try:
        rc = _resolve_repo_context(ctx)
        cache_key = ("repo_get_metadata", rc["owner"], rc["repo"])
        cached = _cache_get(ctx, cache_key)
        if cached is not None:
            return cached
        meta = await repo_credentials_service.lookup_repo(
            ctx.db, ctx.workspace_id, rc["owner"], rc["repo"]
        )
        # Languages endpoint returns ``{lang: byte_count}`` — cheap lookup.
        try:
            lang_resp = await repo_credentials_service.make_request(
                ctx.db,
                ctx.workspace_id,
                "GET",
                f"/repos/{rc['owner']}/{rc['repo']}/languages",
            )
            lang_resp.raise_for_status()
            languages = lang_resp.json() or {}
        except Exception:  # noqa: BLE001 — languages are optional
            logger.debug("repo_get_metadata: languages fetch failed", exc_info=True)
            languages = {}

        result = {
            "description": meta.get("description") or "",
            "default_branch": meta.get("default_branch"),
            "languages": languages,
            "topics": meta.get("topics") or [],
            "stargazers_count": meta.get("stargazers_count") or 0,
            "html_url": meta.get("html_url"),
            "full_name": meta.get("full_name"),
        }
        _cache_put(ctx, cache_key, result)
        return result
    except (GitHubAuthError, GitHubNotFoundError, GitHubRateLimitError, GitHubServerError, _RepoContextMissing) as exc:
        return _wrap_github_errors(exc)


# ---------------------------------------------------------------------------
# Tool: repo_read_readme
# ---------------------------------------------------------------------------


@tool(
    name="repo_read_readme",
    description=(
        "Return the repository's README contents (markdown). Truncated at "
        "50KB with a next_offset hint when larger."
    ),
    input_schema=RepoEmptyInput,
    permission="workspace:read",
    permission_target="workspace",
    required_scope="agents:read",
    mutating=False,
)
async def repo_read_readme(args: RepoEmptyInput, ctx: ToolContext) -> dict:
    try:
        rc = _resolve_repo_context(ctx)
        cache_key = ("repo_read_readme", rc["owner"], rc["repo"])
        cached = _cache_get(ctx, cache_key)
        if cached is not None:
            return cached
        resp = await repo_credentials_service.make_request(
            ctx.db,
            ctx.workspace_id,
            "GET",
            f"/repos/{rc['owner']}/{rc['repo']}/readme",
        )
        if resp.status_code == 404:
            return _error_envelope("github_not_found", "README not found")
        resp.raise_for_status()
        payload = resp.json()
        content_b64 = payload.get("content") or ""
        try:
            decoded = base64.b64decode(content_b64).decode("utf-8", errors="replace")
        except (binascii.Error, ValueError) as exc:
            return _error_envelope("github_bad_payload", f"could not decode README: {exc}")
        truncated_text, was_truncated = _truncate(decoded, _README_CHAR_LIMIT)
        result = {
            "path": payload.get("path") or "README.md",
            "content": truncated_text,
            "truncated": was_truncated,
            "total_size": len(decoded),
            "next_offset": _README_CHAR_LIMIT if was_truncated else None,
            "html_url": payload.get("html_url"),
        }
        _cache_put(ctx, cache_key, result)
        return result
    except (GitHubAuthError, GitHubNotFoundError, GitHubRateLimitError, GitHubServerError, _RepoContextMissing) as exc:
        return _wrap_github_errors(exc)


# ---------------------------------------------------------------------------
# Tool: repo_list_tree
# ---------------------------------------------------------------------------


def _filter_tree(
    items: list[dict],
    *,
    path: str,
    depth: int,
    recursive: bool,
) -> list[dict]:
    """Filter the recursive tree response to entries under ``path`` within
    ``depth`` levels.

    ``items`` is the GitHub git/trees ``tree`` array; each entry has
    ``path`` (full path from repo root), ``type`` (``blob``/``tree``),
    ``size`` (only for blobs), and ``sha``.
    """
    base_segments = [seg for seg in path.split("/") if seg] if path else []
    base_depth = len(base_segments)
    out: list[dict] = []
    for item in items:
        full_path = item.get("path") or ""
        if not full_path:
            continue
        # Prefix filter
        if base_segments:
            segs = full_path.split("/")
            if segs[: len(base_segments)] != base_segments:
                continue
            relative_depth = len(segs) - base_depth
        else:
            relative_depth = full_path.count("/") + 1
        if relative_depth < 1 or relative_depth > depth:
            continue
        if not recursive and relative_depth > 1:
            continue
        entry: dict[str, Any] = {
            "path": full_path,
            "type": item.get("type") or "blob",
        }
        size = item.get("size")
        if isinstance(size, int):
            entry["size"] = size
        out.append(entry)
    return out


@tool(
    name="repo_list_tree",
    description=(
        "List files/directories under a repo path. Default depth=2 to keep "
        "monorepo responses compact; raise ``depth`` and set "
        "``recursive=true`` to walk deeper. Capped at 500 entries."
    ),
    input_schema=RepoListTreeInput,
    permission="workspace:read",
    permission_target="workspace",
    required_scope="agents:read",
    mutating=False,
)
async def repo_list_tree(args: RepoListTreeInput, ctx: ToolContext) -> dict:
    try:
        rc = _resolve_repo_context(ctx)
        ref = await _resolve_branch(ctx, rc)
        cache_key = (
            "repo_list_tree",
            rc["owner"],
            rc["repo"],
            ref,
            args.path,
            args.depth,
            bool(args.recursive),
        )
        cached = _cache_get(ctx, cache_key)
        if cached is not None:
            return cached
        # Fetch the full tree once (cached above), then filter client-side.
        tree_cache_key = ("__tree__", rc["owner"], rc["repo"], ref)
        tree_items = _cache_get(ctx, tree_cache_key)
        if tree_items is None:
            resp = await repo_credentials_service.make_request(
                ctx.db,
                ctx.workspace_id,
                "GET",
                f"/repos/{rc['owner']}/{rc['repo']}/git/trees/{ref}?recursive=true",
            )
            if resp.status_code == 404:
                return _error_envelope(
                    "github_not_found", f"ref '{ref}' not found"
                )
            resp.raise_for_status()
            payload = resp.json() or {}
            tree_items = payload.get("tree") or []
            _cache_put(ctx, tree_cache_key, tree_items)
        filtered = _filter_tree(
            tree_items,
            path=args.path,
            depth=args.depth,
            recursive=args.recursive,
        )
        truncated = len(filtered) > _TREE_ENTRY_LIMIT
        if truncated:
            filtered = filtered[:_TREE_ENTRY_LIMIT]
        result = {
            "path": args.path or "/",
            "ref": ref,
            "entries": filtered,
            "truncated": truncated,
            "total_returned": len(filtered),
        }
        _cache_put(ctx, cache_key, result)
        return result
    except (GitHubAuthError, GitHubNotFoundError, GitHubRateLimitError, GitHubServerError, _RepoContextMissing) as exc:
        return _wrap_github_errors(exc)


# ---------------------------------------------------------------------------
# Tool: repo_read_file
# ---------------------------------------------------------------------------


_LARGE_FILE_THRESHOLD = 1_000_000  # 1MB — switch to /git/blobs above this


@tool(
    name="repo_read_file",
    description=(
        "Return the contents of a file in the repo. Decoded utf-8. Default "
        "limit 50KB; pass ``offset`` to page through larger files (response "
        "carries ``next_offset`` and ``has_more``)."
    ),
    input_schema=RepoReadFileInput,
    permission="workspace:read",
    permission_target="workspace",
    required_scope="agents:read",
    mutating=False,
)
async def repo_read_file(args: RepoReadFileInput, ctx: ToolContext) -> dict:
    try:
        rc = _resolve_repo_context(ctx)
        ref = await _resolve_branch(ctx, rc)
        encoded_path = repo_credentials_service.encode_path(args.path)
        # Cache only the full decoded payload, not the per-call slice — the
        # LLM commonly pages through the same file with growing offsets and
        # we want to spare the second round-trip.
        full_cache_key = (
            "__file_full__",
            rc["owner"],
            rc["repo"],
            ref,
            args.path,
        )
        full_text = _cache_get(ctx, full_cache_key)
        if full_text is None:
            resp = await repo_credentials_service.make_request(
                ctx.db,
                ctx.workspace_id,
                "GET",
                f"/repos/{rc['owner']}/{rc['repo']}/contents/{encoded_path}?ref={ref}",
            )
            if resp.status_code == 404:
                return _error_envelope(
                    "github_not_found", f"file {args.path!r} not found at ref {ref!r}"
                )
            resp.raise_for_status()
            payload = resp.json()
            if isinstance(payload, list):
                return _error_envelope(
                    "github_bad_target",
                    f"path {args.path!r} is a directory; use repo_list_tree",
                )
            size = int(payload.get("size") or 0)
            content_b64 = payload.get("content")
            if size > _LARGE_FILE_THRESHOLD or not content_b64:
                # /contents inlines blobs up to 1MB; for larger files (or
                # blank-content responses for symlinks etc.) fetch the raw blob.
                sha = payload.get("sha")
                if not isinstance(sha, str):
                    return _error_envelope(
                        "github_bad_payload",
                        "file metadata missing sha for large-blob fallback",
                    )
                blob_resp = await repo_credentials_service.make_request(
                    ctx.db,
                    ctx.workspace_id,
                    "GET",
                    f"/repos/{rc['owner']}/{rc['repo']}/git/blobs/{sha}",
                )
                blob_resp.raise_for_status()
                blob_payload = blob_resp.json()
                content_b64 = blob_payload.get("content") or ""
            try:
                decoded = base64.b64decode(content_b64).decode("utf-8", errors="replace")
            except (binascii.Error, ValueError) as exc:
                return _error_envelope("github_bad_payload", f"could not decode file: {exc}")
            full_text = decoded
            _cache_put(ctx, full_cache_key, full_text)
        total = len(full_text)
        end = min(args.offset + args.limit, total)
        slice_text = full_text[args.offset : end]
        truncated = end < total
        return {
            "path": args.path,
            "ref": ref,
            "content": slice_text,
            "truncated": truncated,
            "total_size": total,
            "has_more": truncated,
            "next_offset": end if truncated else None,
        }
    except (GitHubAuthError, GitHubNotFoundError, GitHubRateLimitError, GitHubServerError, _RepoContextMissing) as exc:
        return _wrap_github_errors(exc)


# ---------------------------------------------------------------------------
# Tool: repo_search_code
# ---------------------------------------------------------------------------


@tool(
    name="repo_search_code",
    description=(
        "Substring code search via the GitHub Search API. Limited to the "
        "repo's default branch (API constraint) — use repo_read_file on a "
        "specific ref if you need to inspect code on a non-default branch. "
        "Returns the top 30 hits with a short snippet, file path, and "
        "html_url. Indexing latency means very recent commits may be "
        "missing."
    ),
    input_schema=RepoSearchCodeInput,
    permission="workspace:read",
    permission_target="workspace",
    required_scope="agents:read",
    mutating=False,
)
async def repo_search_code(args: RepoSearchCodeInput, ctx: ToolContext) -> dict:
    try:
        rc = _resolve_repo_context(ctx)
        cache_key = (
            "repo_search_code",
            rc["owner"],
            rc["repo"],
            args.query,
        )
        cached = _cache_get(ctx, cache_key)
        if cached is not None:
            return cached
        # GitHub Search API requires the user to URL-encode the query.
        from urllib.parse import quote_plus

        scoped = f"{args.query} repo:{rc['owner']}/{rc['repo']}"
        url = f"/search/code?q={quote_plus(scoped)}&per_page=30"
        # text-match preview headers — gives us snippets per hit.
        headers = {"Accept": "application/vnd.github.text-match+json"}
        resp = await repo_credentials_service.make_request(
            ctx.db,
            ctx.workspace_id,
            "GET",
            url,
            headers=headers,
        )
        resp.raise_for_status()
        payload = resp.json() or {}
        items = payload.get("items") or []
        hits: list[dict] = []
        for item in items[:30]:
            text_matches = item.get("text_matches") or []
            snippet = ""
            if text_matches and isinstance(text_matches[0], dict):
                snippet = text_matches[0].get("fragment") or ""
            hits.append(
                {
                    "path": item.get("path"),
                    "name": item.get("name"),
                    "snippet": snippet[:512],
                    "html_url": item.get("html_url"),
                    "score": item.get("score"),
                }
            )
        result = {
            "query": args.query,
            "total_count": payload.get("total_count") or 0,
            "incomplete_results": bool(payload.get("incomplete_results")),
            "hits": hits,
        }
        _cache_put(ctx, cache_key, result)
        return result
    except (GitHubAuthError, GitHubNotFoundError, GitHubRateLimitError, GitHubServerError, _RepoContextMissing) as exc:
        return _wrap_github_errors(exc)


# ---------------------------------------------------------------------------
# Tool: repo_read_issues
# ---------------------------------------------------------------------------


def _project_issue(item: dict) -> dict:
    body = item.get("body") or ""
    truncated_body, was_truncated = _truncate(body, _ISSUE_BODY_CHAR_LIMIT)
    return {
        "number": item.get("number"),
        "title": item.get("title"),
        "body": truncated_body,
        "body_truncated": was_truncated,
        "state": item.get("state"),
        "labels": [
            (lab.get("name") if isinstance(lab, dict) else str(lab))
            for lab in (item.get("labels") or [])
        ],
        "created_at": item.get("created_at"),
        "html_url": item.get("html_url"),
    }


@tool(
    name="repo_read_issues",
    description=(
        "List the most recent issues (page size 30). Pull requests are "
        "filtered out — use repo_read_pulls for those. Bodies are truncated "
        "at 2KB."
    ),
    input_schema=RepoStateFilterInput,
    permission="workspace:read",
    permission_target="workspace",
    required_scope="agents:read",
    mutating=False,
)
async def repo_read_issues(args: RepoStateFilterInput, ctx: ToolContext) -> dict:
    try:
        rc = _resolve_repo_context(ctx)
        cache_key = ("repo_read_issues", rc["owner"], rc["repo"], args.state)
        cached = _cache_get(ctx, cache_key)
        if cached is not None:
            return cached
        resp = await repo_credentials_service.make_request(
            ctx.db,
            ctx.workspace_id,
            "GET",
            f"/repos/{rc['owner']}/{rc['repo']}/issues?state={args.state}&per_page=30",
        )
        resp.raise_for_status()
        items = resp.json() or []
        issues = [
            _project_issue(item)
            for item in items
            if isinstance(item, dict) and "pull_request" not in item
        ]
        result = {"state": args.state, "issues": issues}
        _cache_put(ctx, cache_key, result)
        return result
    except (GitHubAuthError, GitHubNotFoundError, GitHubRateLimitError, GitHubServerError, _RepoContextMissing) as exc:
        return _wrap_github_errors(exc)


# ---------------------------------------------------------------------------
# Tool: repo_read_pulls
# ---------------------------------------------------------------------------


def _project_pull(item: dict) -> dict:
    body = item.get("body") or ""
    truncated_body, was_truncated = _truncate(body, _PR_BODY_CHAR_LIMIT)
    head = item.get("head") or {}
    base = item.get("base") or {}
    return {
        "number": item.get("number"),
        "title": item.get("title"),
        "body": truncated_body,
        "body_truncated": was_truncated,
        "state": item.get("state"),
        "head": head.get("ref") if isinstance(head, dict) else None,
        "base": base.get("ref") if isinstance(base, dict) else None,
        "additions": item.get("additions"),
        "deletions": item.get("deletions"),
        "changed_files": item.get("changed_files"),
        "html_url": item.get("html_url"),
        "created_at": item.get("created_at"),
    }


@tool(
    name="repo_read_pulls",
    description=(
        "List the most recent pull requests (page size 30). Bodies are "
        "truncated at 2KB. Use repo_read_diff to inspect actual code "
        "changes for a single PR."
    ),
    input_schema=RepoStateFilterInput,
    permission="workspace:read",
    permission_target="workspace",
    required_scope="agents:read",
    mutating=False,
)
async def repo_read_pulls(args: RepoStateFilterInput, ctx: ToolContext) -> dict:
    try:
        rc = _resolve_repo_context(ctx)
        cache_key = ("repo_read_pulls", rc["owner"], rc["repo"], args.state)
        cached = _cache_get(ctx, cache_key)
        if cached is not None:
            return cached
        resp = await repo_credentials_service.make_request(
            ctx.db,
            ctx.workspace_id,
            "GET",
            f"/repos/{rc['owner']}/{rc['repo']}/pulls?state={args.state}&per_page=30",
        )
        resp.raise_for_status()
        items = resp.json() or []
        pulls = [_project_pull(item) for item in items if isinstance(item, dict)]
        result = {"state": args.state, "pulls": pulls}
        _cache_put(ctx, cache_key, result)
        return result
    except (GitHubAuthError, GitHubNotFoundError, GitHubRateLimitError, GitHubServerError, _RepoContextMissing) as exc:
        return _wrap_github_errors(exc)


# ---------------------------------------------------------------------------
# Tool: repo_read_commits
# ---------------------------------------------------------------------------


def _project_commit(item: dict) -> dict:
    commit = item.get("commit") or {}
    author = commit.get("author") or {}
    return {
        "sha": item.get("sha"),
        "message": commit.get("message") or "",
        "author": {
            "name": author.get("name"),
            "email": author.get("email"),
            "date": author.get("date"),
        },
        "html_url": item.get("html_url"),
    }


@tool(
    name="repo_read_commits",
    description=(
        "List the 30 most recent commits, optionally scoped to a path or "
        "lower-bounded by a ``since`` ISO-8601 datetime."
    ),
    input_schema=RepoReadCommitsInput,
    permission="workspace:read",
    permission_target="workspace",
    required_scope="agents:read",
    mutating=False,
)
async def repo_read_commits(args: RepoReadCommitsInput, ctx: ToolContext) -> dict:
    try:
        rc = _resolve_repo_context(ctx)
        cache_key = (
            "repo_read_commits",
            rc["owner"],
            rc["repo"],
            args.path or "",
            args.since or "",
        )
        cached = _cache_get(ctx, cache_key)
        if cached is not None:
            return cached
        params: list[str] = ["per_page=30"]
        if args.path:
            from urllib.parse import quote

            params.append(f"path={quote(args.path)}")
        if args.since:
            from urllib.parse import quote_plus

            params.append(f"since={quote_plus(args.since)}")
        url = f"/repos/{rc['owner']}/{rc['repo']}/commits?{'&'.join(params)}"
        resp = await repo_credentials_service.make_request(
            ctx.db, ctx.workspace_id, "GET", url
        )
        resp.raise_for_status()
        items = resp.json() or []
        commits = [_project_commit(item) for item in items if isinstance(item, dict)]
        result = {"path": args.path, "since": args.since, "commits": commits}
        _cache_put(ctx, cache_key, result)
        return result
    except (GitHubAuthError, GitHubNotFoundError, GitHubRateLimitError, GitHubServerError, _RepoContextMissing) as exc:
        return _wrap_github_errors(exc)


# ---------------------------------------------------------------------------
# Tool: repo_read_diff
# ---------------------------------------------------------------------------


@tool(
    name="repo_read_diff",
    description=(
        "Compute a unified diff between two refs (commit sha, branch, or "
        "tag). Capped at 100KB with a truncation hint when larger."
    ),
    input_schema=RepoReadDiffInput,
    permission="workspace:read",
    permission_target="workspace",
    required_scope="agents:read",
    mutating=False,
)
async def repo_read_diff(args: RepoReadDiffInput, ctx: ToolContext) -> dict:
    try:
        rc = _resolve_repo_context(ctx)
        cache_key = (
            "repo_read_diff",
            rc["owner"],
            rc["repo"],
            args.base,
            args.head,
        )
        cached = _cache_get(ctx, cache_key)
        if cached is not None:
            return cached
        from urllib.parse import quote

        base = quote(args.base, safe="")
        head = quote(args.head, safe="")
        url = f"/repos/{rc['owner']}/{rc['repo']}/compare/{base}...{head}"
        # ``Accept: application/vnd.github.diff`` returns the raw unified diff.
        resp = await repo_credentials_service.make_request(
            ctx.db,
            ctx.workspace_id,
            "GET",
            url,
            headers={"Accept": "application/vnd.github.diff"},
        )
        if resp.status_code == 404:
            return _error_envelope(
                "github_not_found",
                f"compare {args.base!r}...{args.head!r} not found",
            )
        resp.raise_for_status()
        diff_text = resp.text or ""
        truncated_text, was_truncated = _truncate(diff_text, _DIFF_CHAR_LIMIT)
        result = {
            "base": args.base,
            "head": args.head,
            "diff": truncated_text,
            "truncated": was_truncated,
            "total_size": len(diff_text),
        }
        _cache_put(ctx, cache_key, result)
        return result
    except (GitHubAuthError, GitHubNotFoundError, GitHubRateLimitError, GitHubServerError, _RepoContextMissing) as exc:
        return _wrap_github_errors(exc)


# ---------------------------------------------------------------------------
# Public helpers used by repo_researcher node
# ---------------------------------------------------------------------------


REPO_TOOL_NAMES: tuple[str, ...] = (
    "repo_get_metadata",
    "repo_read_readme",
    "repo_list_tree",
    "repo_read_file",
    "repo_search_code",
    "repo_read_issues",
    "repo_read_pulls",
    "repo_read_commits",
    "repo_read_diff",
)


def is_repo_tool(name: str) -> bool:
    return name in REPO_TOOL_NAMES


def _is_forbidden_tool_name(name: str) -> bool:
    return any(name.startswith(p) for p in _FORBIDDEN_TOOL_PREFIXES)


# Sanity: ensure the silent ``json`` import isn't flagged unused.
_ = json
