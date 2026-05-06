"""web_fetch tool — fetch http(s) URL with SSRF guard + size/timeout limits + Redis cache.
SUPERVISOR + RESEARCHER tool only (declared in their tool sets)."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import re
import socket
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field

from app.agents.errors import ToolDenied
from app.agents.tools.base import ToolContext, tool
from app.core.redis import redis_client

logger = logging.getLogger(__name__)


ALLOWED_SCHEMES = {"http", "https"}
BLOCKED_HOSTNAMES = {"localhost", "metadata.google.internal", "169.254.169.254"}
TIMEOUT_SECONDS = 10
MAX_BYTES = 5_000_000
MAX_REDIRECTS = 3
USER_AGENT = "ArchFlow-Agent/0.1 (+https://archflow.io/agents)"
CACHE_TTL_SECONDS = 1800  # 30 min


class WebFetchInput(BaseModel):
    url: str
    max_chars: int = Field(20000, ge=500, le=100000)
    render: Literal["text", "markdown", "image_describe"] = "text"


def _is_private_ip(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr)
        return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
    except ValueError:
        return False


async def _resolve_and_check(host: str) -> None:
    """Async DNS resolution + SSRF check. Raises ToolDenied on private IPs / blocked hosts."""
    if host.lower() in BLOCKED_HOSTNAMES:
        raise ToolDenied(f"SSRF guard: blocked hostname '{host}'")

    # Run blocking getaddrinfo in a thread so we don't block the event loop.
    import asyncio

    try:
        infos = await asyncio.get_event_loop().run_in_executor(
            None, lambda: socket.getaddrinfo(host, None)
        )
    except OSError as exc:
        raise ToolDenied(f"DNS resolution failed for '{host}': {exc}") from exc

    for info in infos:
        addr = info[4][0]
        if _is_private_ip(addr):
            raise ToolDenied(
                f"SSRF guard: '{host}' resolves to private/loopback address {addr}"
            )
        # Also check against blocked string patterns (e.g. 169.254.169.254).
        if addr in BLOCKED_HOSTNAMES:
            raise ToolDenied(f"SSRF guard: blocked IP address '{addr}'")


def _strip_html_to_text(html: str, *, max_chars: int) -> tuple[str, str | None]:
    """Parse HTML into plain text and extract the page title.

    Uses BeautifulSoup when available; falls back to regex stripping.
    Returns (text, title_or_None).
    Truncates text to max_chars.
    """
    title: str | None = None

    try:
        from bs4 import BeautifulSoup  # type: ignore[import]

        soup = BeautifulSoup(html, "html.parser")

        # Extract title tag.
        title_tag = soup.find("title")
        if title_tag:
            title = title_tag.get_text(strip=True) or None

        # Remove script / style / nav / footer tags.
        for tag in soup(["script", "style", "noscript", "nav", "footer", "head"]):
            tag.decompose()

        text = soup.get_text(separator="\n", strip=True)
    except Exception:  # BeautifulSoup not available or parse error
        # Regex fallback: extract title, strip <script>/<style>, strip all tags.
        title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        if title_match:
            title = re.sub(r"<[^>]+>", "", title_match.group(1)).strip() or None

        # Strip <script>…</script> and <style>…</style> blocks.
        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.IGNORECASE | re.DOTALL)
        # Strip all remaining tags.
        text = re.sub(r"<[^>]+>", " ", text)
        # Collapse whitespace.
        text = re.sub(r"\s+", " ", text).strip()

    truncated_text = text[:max_chars]
    return truncated_text, title


async def _write_web_fetch_audit(
    ctx: ToolContext,
    *,
    url: str,
    content_type: str,
    success: bool,
) -> None:
    """Write an audit log entry for a web_fetch call.

    Uses a raw SQL insert because ActivityAction enum doesn't include
    'agent.web_fetch' — this avoids a schema migration in Phase 1 while
    still persisting the event for compliance/debugging.
    """
    from sqlalchemy import text

    actor = ctx.actor
    user_id = getattr(actor, "id", None) if getattr(actor, "kind", None) == "user" else None

    try:
        await ctx.db.execute(
            text(
                "INSERT INTO activity_log "
                "(id, target_type, target_id, action, changes, user_id, workspace_id, created_at) "
                "VALUES "
                "(:id, 'diagram', :workspace_id, 'agent.web_fetch', :changes::jsonb, "
                " :user_id, :workspace_id, NOW())"
            ),
            {
                "id": str(__import__("uuid").uuid4()),
                "workspace_id": str(ctx.workspace_id),
                "user_id": str(user_id) if user_id else None,
                "changes": json.dumps(
                    {
                        "url": url,
                        "content_type": content_type,
                        "success": success,
                        "source": f"agent:{ctx.agent_id}",
                        "agent_session_id": str(ctx.session_id),
                    }
                ),
            },
        )
        try:
            await ctx.db.flush()
        except Exception:  # pragma: no cover
            logger.exception("flush failed for web_fetch audit row")
    except Exception:  # pragma: no cover
        logger.exception("web_fetch audit write failed")


@tool(
    name="web_fetch",
    description=(
        "Fetch text content from an http(s) URL. Use for URLs the user pasted. "
        "Returns title + content (truncated). "
        "render='text' (default) → plain text; 'markdown' → preserve some structure; "
        "'image_describe' → for image URLs (Phase 2: deferred)."
    ),
    input_schema=WebFetchInput,
    permission="workspace:read",
    permission_target="workspace",
    required_scope="agents:read",
    mutating=False,
)
async def web_fetch(args: WebFetchInput, ctx: ToolContext) -> dict:
    """Flow:
    1. Validate scheme (http/https).
    2. Parse URL, resolve hostname → IP. Reject private/loopback/blocked.
    3. Cache lookup: key = f'webfetch:{ctx.workspace_id}:{sha1(url)}', TTL 30 min.
    4. httpx.AsyncClient with timeout=10, follow_redirects=True, max_redirects=3.
    5. Stream-read body, abort if > MAX_BYTES.
    6. Content-Type dispatch: html/plain → strip; image/* → image_describe path.
    7. Cache response (JSON) for 30 min.
    8. Return structured result dict.
    9. Audit write (agent.web_fetch).
    """
    url = args.url.strip()

    # ── 1. Scheme check ───────────────────────────────────────────
    parsed = urlparse(url)
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        return {
            "error": f"unsupported scheme '{parsed.scheme}': only http/https are allowed",
            "code": "bad_scheme",
        }

    host = parsed.hostname or ""
    if not host:
        return {"error": "URL has no hostname", "code": "bad_url"}

    # ── 2. SSRF guard ─────────────────────────────────────────────
    try:
        await _resolve_and_check(host)
    except ToolDenied:
        raise  # Let execute_tool surface it as denied
    except Exception as exc:
        return {"error": str(exc), "code": "ssrf_error"}

    # ── 3. Cache lookup ───────────────────────────────────────────
    url_hash = hashlib.sha1(url.encode(), usedforsecurity=False).hexdigest()
    cache_key = f"webfetch:{ctx.workspace_id}:{url_hash}"

    try:
        cached_raw = await redis_client.get(cache_key)
        if cached_raw:
            result = json.loads(cached_raw)
            result["cached"] = True
            return result
    except Exception:
        logger.warning("Redis cache read failed for web_fetch key=%s", cache_key)

    # ── 4-5. HTTP fetch ───────────────────────────────────────────
    timeout = httpx.Timeout(TIMEOUT_SECONDS)
    headers = {"User-Agent": USER_AGENT}

    url_final = url
    content_type = "unknown"
    title: str | None = None
    content = ""
    truncated = False

    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            max_redirects=MAX_REDIRECTS,
            timeout=timeout,
            headers=headers,
        ) as client, client.stream("GET", url) as response:
            response.raise_for_status()
            url_final = str(response.url)
            content_type = response.headers.get("content-type", "").split(";")[0].strip()

            # Stream body with size limit.
            body_bytes = bytearray()
            async for chunk in response.aiter_bytes(chunk_size=65536):
                body_bytes.extend(chunk)
                if len(body_bytes) > MAX_BYTES:
                    await response.aclose()
                    await _write_web_fetch_audit(
                        ctx, url=url, content_type=content_type, success=False
                    )
                    return {
                        "error": "response body exceeded 5 MB limit",
                        "code": "response_too_large",
                    }

    except httpx.HTTPStatusError as exc:
        await _write_web_fetch_audit(ctx, url=url, content_type="unknown", success=False)
        return {
            "error": f"HTTP {exc.response.status_code}: {exc.response.reason_phrase}",
            "code": "http_error",
        }
    except httpx.TooManyRedirects:
        await _write_web_fetch_audit(ctx, url=url, content_type="unknown", success=False)
        return {"error": "too many redirects", "code": "too_many_redirects"}
    except httpx.RequestError as exc:
        await _write_web_fetch_audit(ctx, url=url, content_type="unknown", success=False)
        return {"error": f"request failed: {exc}", "code": "request_error"}

    body_str = body_bytes.decode("utf-8", errors="replace")

    # ── 6. Content-Type dispatch ──────────────────────────────────
    ct_base = content_type.lower()

    if ct_base.startswith("image/"):
        if args.render == "image_describe":
            await _write_web_fetch_audit(ctx, url=url, content_type=content_type, success=True)
            return {
                "url_final": url_final,
                "content_type": content_type,
                "title": None,
                "content": "image describe not implemented in Phase 1",
                "truncated": False,
                "fetched_at": datetime.now(tz=UTC).isoformat(),
                "cached": False,
            }
        else:
            await _write_web_fetch_audit(ctx, url=url, content_type=content_type, success=False)
            return {
                "error": "use render=image_describe for image URLs",
                "code": "image_needs_render_mode",
            }

    if ct_base.startswith("text/html") or ct_base.startswith("text/plain"):
        stripped, title = _strip_html_to_text(body_str, max_chars=args.max_chars)
        content = stripped
        truncated = len(body_str) > args.max_chars if ct_base.startswith("text/plain") else (
            # For HTML the original text before stripping may be larger; compare stripped len
            # against max_chars threshold.
            len(stripped) == args.max_chars
        )
    else:
        await _write_web_fetch_audit(ctx, url=url, content_type=content_type, success=False)
        return {
            "error": f"unsupported content-type: {content_type}",
            "code": "unsupported_content_type",
        }

    fetched_at = datetime.now(tz=UTC).isoformat()
    result = {
        "url_final": url_final,
        "content_type": content_type,
        "title": title,
        "content": content,
        "truncated": truncated,
        "fetched_at": fetched_at,
        "cached": False,
    }

    # ── 7. Write cache ────────────────────────────────────────────
    try:
        cache_payload = json.dumps(result)
        await redis_client.set(cache_key, cache_payload, ex=CACHE_TTL_SECONDS)
    except Exception:
        logger.warning("Redis cache write failed for web_fetch key=%s", cache_key)

    # ── 8. Audit ──────────────────────────────────────────────────
    await _write_web_fetch_audit(ctx, url=url, content_type=content_type, success=True)

    return result
