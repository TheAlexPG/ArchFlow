"""GitHub credentials + thin REST client for the repo-researcher agent.

Responsibilities:
- Validate a Personal Access Token by hitting ``GET /user``.
- Pull the workspace's stored token and dispatch authenticated requests
  with retry/backoff (max 3, exponential, capped at 30 s; retries on
  5xx + 429).
- Lookup a single repo's metadata (used by the inspector validate-on-blur
  endpoint).
- Parse repo URLs into ``(owner, name)`` tuples for the D2 tool layer.

The agent's tool surface (D2) layers per-tool helpers on top of
``make_request`` — keep this module focused on credentials + HTTP.

NOTE: tokens are never logged. Errors include the response status only.
"""
from __future__ import annotations

import asyncio
import random
import re
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import workspace_service

GITHUB_API = "https://api.github.com"
USER_AGENT = "ArchFlow/1.0 (+https://github.com/)"

# Default headers required by the GitHub REST API.
_BASE_HEADERS: dict[str, str] = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": USER_AGENT,
}

_MAX_RETRIES = 3
_BACKOFF_BASE_SECONDS = 1.0
_BACKOFF_CAP_SECONDS = 30.0
_DEFAULT_TIMEOUT_SECONDS = 10.0


class GitHubAuthError(Exception):
    """Raised when GitHub returns 401 — token is missing/invalid."""


class GitHubNotFoundError(Exception):
    """Raised when GitHub returns 404 — the resource does not exist or
    the token cannot see it."""


class GitHubRateLimitError(Exception):
    """Retry budget exhausted on a 429 / abuse-detection response."""


class GitHubServerError(Exception):
    """5xx that survived the retry budget."""


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def validate_token(token: str) -> dict[str, Any] | None:
    """Hit ``GET /user`` with the supplied token.

    Returns the user payload (login, id, …) on a 2xx response.
    Returns ``None`` on 401 (token rejected by GitHub).
    Raises ``GitHubServerError`` on persistent 5xx; ``GitHubRateLimitError``
    on persistent 429. Other 4xx surface as ``httpx.HTTPStatusError``.
    """
    if not token or not token.strip():
        return None
    headers = {**_BASE_HEADERS, **_auth_header(token.strip())}
    async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT_SECONDS) as client:
        resp = await _request_with_retries(
            client, "GET", f"{GITHUB_API}/user", headers=headers
        )
    if resp.status_code == 200:
        return resp.json()
    if resp.status_code == 401:
        return None
    # Other failures (forbidden, rate-limited, server errors) — let the
    # caller decide how to surface them.
    resp.raise_for_status()
    return None  # pragma: no cover — raise_for_status above exits non-2xx.


async def _request_with_retries(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    **kwargs: Any,
) -> httpx.Response:
    """Issue ``method url`` with up to 3 retries on 5xx / 429.

    Exponential backoff with full jitter, capped at 30 s.
    """
    attempt = 0
    last_exc: Exception | None = None
    while attempt < _MAX_RETRIES:
        try:
            resp = await client.request(method, url, headers=headers, **kwargs)
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            last_exc = exc
        else:
            # Success or non-retryable error path.
            if resp.status_code < 500 and resp.status_code != 429:
                return resp
            # Rate limit on the secondary path: respect Retry-After if present.
            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                if retry_after is not None:
                    try:
                        delay = min(
                            float(retry_after),
                            _BACKOFF_CAP_SECONDS,
                        )
                    except ValueError:
                        delay = _backoff_delay(attempt)
                else:
                    delay = _backoff_delay(attempt)
            else:
                delay = _backoff_delay(attempt)
            attempt += 1
            if attempt >= _MAX_RETRIES:
                if resp.status_code == 429:
                    raise GitHubRateLimitError(
                        f"GitHub rate limit hit after {_MAX_RETRIES} attempts"
                    )
                raise GitHubServerError(
                    f"GitHub returned {resp.status_code} after "
                    f"{_MAX_RETRIES} attempts"
                )
            await asyncio.sleep(delay)
            continue

        # Transport/timeout exception path.
        attempt += 1
        if attempt >= _MAX_RETRIES:
            assert last_exc is not None
            raise last_exc
        await asyncio.sleep(_backoff_delay(attempt))

    # Unreachable — the loop always returns or raises.
    raise GitHubServerError("GitHub request failed without response")  # pragma: no cover


def _backoff_delay(attempt: int) -> float:
    """Exponential backoff with full jitter, capped at _BACKOFF_CAP_SECONDS."""
    base = min(_BACKOFF_CAP_SECONDS, _BACKOFF_BASE_SECONDS * (2**attempt))
    return random.uniform(0, base)  # noqa: S311 — non-crypto backoff jitter


async def make_request(
    db: AsyncSession,
    workspace_id: UUID,
    method: str,
    url: str,
    **kwargs: Any,
) -> httpx.Response:
    """Pull workspace token, attach Authorization header, dispatch.

    Pass ``url`` as either an absolute URL or a path starting with ``/``;
    in the latter case it's prefixed with ``https://api.github.com``.
    """
    token = await workspace_service.get_github_token(db, workspace_id)
    if token is None:
        raise GitHubAuthError(
            f"Workspace {workspace_id} has no GitHub token configured"
        )

    if url.startswith("/"):
        full_url = f"{GITHUB_API}{url}"
    else:
        full_url = url

    headers = kwargs.pop("headers", None) or {}
    merged_headers = {**_BASE_HEADERS, **_auth_header(token), **headers}

    timeout = kwargs.pop("timeout", _DEFAULT_TIMEOUT_SECONDS)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await _request_with_retries(
            client, method, full_url, headers=merged_headers, **kwargs
        )
    if resp.status_code == 401:
        raise GitHubAuthError(
            "GitHub rejected the workspace token (401). "
            "The token may have been revoked or expired."
        )
    return resp


async def lookup_repo(
    db: AsyncSession, workspace_id: UUID, owner: str, repo: str
) -> dict[str, Any]:
    """Fetch repo metadata via ``GET /repos/{owner}/{repo}``.

    Raises:
        GitHubAuthError – workspace has no token / token rejected.
        GitHubNotFoundError – repo does not exist or is invisible to the token.
    """
    resp = await make_request(
        db, workspace_id, "GET", f"/repos/{owner}/{repo}"
    )
    if resp.status_code == 404:
        raise GitHubNotFoundError(f"Repo {owner}/{repo} not found")
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Helpers used by the D2 repo-researcher tool layer
# ---------------------------------------------------------------------------


_GITHUB_URL_RE = re.compile(
    r"^https?://github\.com/([A-Za-z0-9][A-Za-z0-9-_.]*)/([A-Za-z0-9][A-Za-z0-9-_.]*?)(?:\.git)?/?$"
)


def parse_repo_url(repo_url: str) -> tuple[str, str]:
    """Return ``(owner, name)`` from a canonical ``https://github.com/{owner}/{name}``.

    The object service stores repo URLs in canonical form (see
    ``object_service.normalize_repo_url``) so this regex is intentionally
    narrow. Raises ``ValueError`` for anything else — the manifest collector
    rejects the entry rather than letting a malformed URL reach a tool.
    """
    if not repo_url:
        raise ValueError("repo_url is empty")
    m = _GITHUB_URL_RE.match(repo_url.strip())
    if m is None:
        raise ValueError(
            f"repo_url {repo_url!r} is not in canonical "
            "https://github.com/{owner}/{name} form"
        )
    return m.group(1), m.group(2)


async def get_repo_default_branch(
    db: AsyncSession, workspace_id: UUID, owner: str, repo: str
) -> str:
    """Return the repo's default branch name. Raises the same errors as
    ``lookup_repo`` — auth / not-found / 5xx.
    """
    payload = await lookup_repo(db, workspace_id, owner, repo)
    branch = payload.get("default_branch")
    if not isinstance(branch, str) or not branch:
        # GitHub's REST API has always populated this field for active repos;
        # surface a server error rather than passing ``None`` to a tool which
        # would 404 on every subsequent /git/trees/{ref} call.
        raise GitHubServerError(
            f"GitHub did not return default_branch for {owner}/{repo}"
        )
    return branch


def encode_path(path: str) -> str:
    """URL-encode a repo path for use in ``/contents/{+path}`` etc.

    GitHub accepts ``/`` in the path component, so we only escape the special
    characters that would otherwise break the URL. Slash-encoded paths confuse
    the API, so we keep them.
    """
    from urllib.parse import quote

    return quote(path, safe="/")
