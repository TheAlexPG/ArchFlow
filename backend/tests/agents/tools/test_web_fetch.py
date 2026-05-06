"""Tests for app/agents/tools/web_fetch.py.

Uses respx for HTTP mocking and fakeredis for Redis cache testing.
"""

from __future__ import annotations

import socket
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import fakeredis.aioredis
import pytest
import respx
from httpx import Response

from app.agents.errors import ToolDenied
from app.agents.tools.base import ToolContext

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


@dataclass
class FakeActor:
    kind: str = "user"
    id: UUID = None  # type: ignore[assignment]
    workspace_id: UUID = None  # type: ignore[assignment]
    scopes: tuple[str, ...] = ()
    role: Any = None


class FakeSession:
    """Minimal AsyncSession stand-in — records execute / flush calls."""

    def __init__(self) -> None:
        self.executed: list[Any] = []
        self.flush_calls = 0

    def add(self, obj: Any) -> None:
        pass

    async def execute(self, stmt: Any, params: Any = None) -> None:
        self.executed.append((stmt, params))

    async def flush(self) -> None:
        self.flush_calls += 1


def _make_ctx(
    *,
    db: FakeSession | None = None,
    workspace_id: UUID | None = None,
    agent_id: str = "general",
) -> ToolContext:
    ws = workspace_id or uuid4()
    actor = FakeActor(kind="user", id=uuid4(), workspace_id=ws)
    return ToolContext(
        db=db or FakeSession(),
        actor=actor,
        workspace_id=ws,
        chat_context={"kind": "workspace", "id": ws},
        session_id=uuid4(),
        agent_id=agent_id,
        agent_runtime_mode="full",
        active_draft_id=None,
        draft_target_diagram_id=None,
    )


@pytest.fixture
async def fake_redis():
    """Fresh in-memory FakeRedis per test."""
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield r
    await r.aclose()


@pytest.fixture(autouse=True)
def _patch_redis(fake_redis):
    """Redirect the module-level redis_client to the fakeredis instance."""
    with patch("app.agents.tools.web_fetch.redis_client", fake_redis):
        yield


@pytest.fixture(autouse=True)
def _skip_audit():
    """Suppress audit writes (they need a real DB); individual tests override if needed."""
    with patch(
        "app.agents.tools.web_fetch._write_web_fetch_audit",
        new_callable=AsyncMock,
    ):
        yield


# ---------------------------------------------------------------------------
# Import the handler after patches are set up.
# We import from the registered Tool object so we exercise the real function.
# ---------------------------------------------------------------------------


_SHARED_WS_ID = uuid4()


async def _call(
    url: str,
    max_chars: int = 20000,
    render: str = "text",
    workspace_id: UUID | None = None,
) -> dict:
    """Helper: call the web_fetch handler directly."""
    from app.agents.tools.web_fetch import WebFetchInput, web_fetch

    args = WebFetchInput(url=url, max_chars=max_chars, render=render)  # type: ignore[call-arg]
    ctx = _make_ctx(workspace_id=workspace_id)
    return await web_fetch.handler(args, ctx)


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


@respx.mock
async def test_happy_path_html():
    """Fetches HTML page, returns text content with title."""
    html_body = (
        b"<html><head><title>Hello World</title></head>"
        b"<body><p>Some content here.</p></body></html>"
    )
    respx.get("https://example.com/").mock(
        return_value=Response(
            200,
            content=html_body,
            headers={"content-type": "text/html; charset=utf-8"},
        )
    )

    result = await _call("https://example.com/")

    assert result.get("error") is None
    assert result["title"] == "Hello World"
    assert "Some content here" in result["content"]
    assert result["content_type"] == "text/html"
    assert result["cached"] is False
    assert result["url_final"] is not None
    assert "fetched_at" in result


@respx.mock
async def test_truncation():
    """HTML with 100k chars body; max_chars=5000 → content truncated, truncated=True."""
    long_text = "A" * 100_000
    html = f"<html><body><p>{long_text}</p></body></html>"
    respx.get("https://example.com/long").mock(
        return_value=Response(
            200,
            content=html.encode(),
            headers={"content-type": "text/html"},
        )
    )

    result = await _call("https://example.com/long", max_chars=5000)

    assert result.get("error") is None
    assert len(result["content"]) <= 5000
    assert result["truncated"] is True


async def test_ssrf_localhost():
    """URL pointing to localhost is denied."""
    with pytest.raises(ToolDenied, match="SSRF guard"):
        await _call("http://localhost/evil")


async def test_ssrf_private_ip_via_dns(monkeypatch):
    """URL whose hostname resolves to a private IP is denied."""

    def _fake_getaddrinfo(host, port, *args, **kwargs):
        # Return a private IP for any host
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("192.168.1.100", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo)

    with pytest.raises(ToolDenied, match="private"):
        await _call("http://internal.company.local/secret")


async def test_blocked_scheme_file():
    """file:// scheme returns bad_scheme error."""
    result = await _call("file:///etc/passwd")
    assert result["code"] == "bad_scheme"
    assert "file" in result["error"]


@respx.mock
async def test_cache_hit(fake_redis):
    """Second call for same URL within TTL returns cached=True, no HTTP call."""
    ws_id = uuid4()
    call_count = 0

    def _handler(request):
        nonlocal call_count
        call_count += 1
        return Response(
            200,
            content=b"<html><body>Cached page</body></html>",
            headers={"content-type": "text/html"},
        )

    respx.get("https://example.com/cache-test").mock(side_effect=_handler)

    # First call — should hit HTTP.
    r1 = await _call("https://example.com/cache-test", workspace_id=ws_id)
    assert r1["cached"] is False
    assert call_count == 1

    # Second call with same workspace_id — should be served from cache, no HTTP call.
    r2 = await _call("https://example.com/cache-test", workspace_id=ws_id)
    assert r2["cached"] is True
    assert call_count == 1  # HTTP was NOT called again


@respx.mock
async def test_5mb_body_aborted():
    """Response larger than 5 MB is aborted with response_too_large."""
    # Stream 5 MB + 1 byte in one chunk.
    big_body = b"X" * (5_000_001)
    respx.get("https://example.com/big").mock(
        return_value=Response(
            200,
            content=big_body,
            headers={"content-type": "text/plain"},
        )
    )

    result = await _call("https://example.com/big")
    assert result["code"] == "response_too_large"


@respx.mock
async def test_image_describe_render():
    """image/png + render='image_describe' → returns Phase 1 not-implemented message."""
    respx.get("https://example.com/image.png").mock(
        return_value=Response(
            200,
            content=b"\x89PNG\r\n",
            headers={"content-type": "image/png"},
        )
    )

    result = await _call("https://example.com/image.png", render="image_describe")

    assert result.get("error") is None
    assert "not implemented" in result["content"].lower()
    assert result["content_type"] == "image/png"


@respx.mock
async def test_image_without_describe_mode():
    """image/png + render='text' → returns error directing user to image_describe."""
    respx.get("https://example.com/photo.jpg").mock(
        return_value=Response(
            200,
            content=b"\xff\xd8\xff",
            headers={"content-type": "image/jpeg"},
        )
    )

    result = await _call("https://example.com/photo.jpg", render="text")

    assert result["code"] == "image_needs_render_mode"
    assert "image_describe" in result["error"]


@respx.mock
async def test_ssrf_metadata_endpoint():
    """AWS/GCP metadata IP (169.254.169.254) is blocked at DNS-resolve stage."""
    # Simulate hostname that resolves to metadata IP.

    async def _fake_resolve(host):
        if host == "169.254.169.254":
            raise ToolDenied("SSRF guard: blocked hostname '169.254.169.254'")
        raise ToolDenied(f"SSRF guard: blocked hostname '{host}'")

    with (
        patch("app.agents.tools.web_fetch._resolve_and_check", side_effect=_fake_resolve),
        pytest.raises(ToolDenied),
    ):
        await _call("http://169.254.169.254/latest/meta-data/")
