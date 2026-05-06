"""Agent invocation rate limiter backed by Redis.

Uses a simple INCR + EXPIRE (nx=True) approach per bucket.  Granularity is
one second — good enough for the ≥ 600 req/h windows described in spec §5.10.
Atomicity: a pipeline issues INCR and EXPIRE together; the tiny race between
the two commands is acceptable at this window granularity.

Key schema
----------
  rl:api_key:hour:{actor_id}      TTL 3600
  rl:api_key:day:{actor_id}       TTL 86400
  rl:user:day:{actor_id}          TTL 86400
  rl:workspace:day:{workspace_id} TTL 86400
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Literal
from uuid import UUID

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class RateLimitScope(StrEnum):
    API_KEY_HOUR = "api_key:hour"
    API_KEY_DAY = "api_key:day"
    USER_DAY = "user:day"
    WORKSPACE_DAY = "workspace:day"


class RateLimitExceeded(Exception):  # noqa: N818
    def __init__(self, scope: str, limit: int, retry_after_seconds: int) -> None:
        self.scope = scope
        self.limit = limit
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"Rate limit exceeded for {scope}: {limit}")


# ---------------------------------------------------------------------------
# Key helpers
# ---------------------------------------------------------------------------

_TTL: dict[RateLimitScope, int] = {
    RateLimitScope.API_KEY_HOUR: 3600,
    RateLimitScope.API_KEY_DAY: 86400,
    RateLimitScope.USER_DAY: 86400,
    RateLimitScope.WORKSPACE_DAY: 86400,
}


def _redis_key(scope: RateLimitScope, actor_id: UUID, workspace_id: UUID) -> str:
    if scope == RateLimitScope.WORKSPACE_DAY:
        return f"rl:workspace:day:{workspace_id}"
    if scope == RateLimitScope.API_KEY_HOUR:
        return f"rl:api_key:hour:{actor_id}"
    if scope == RateLimitScope.API_KEY_DAY:
        return f"rl:api_key:day:{actor_id}"
    # USER_DAY
    return f"rl:user:day:{actor_id}"


def _scopes_for_actor(
    actor_kind: Literal["api_key", "user"],
) -> tuple[RateLimitScope, ...]:
    if actor_kind == "api_key":
        return (
            RateLimitScope.API_KEY_HOUR,
            RateLimitScope.API_KEY_DAY,
            RateLimitScope.WORKSPACE_DAY,
        )
    return (RateLimitScope.USER_DAY, RateLimitScope.WORKSPACE_DAY)


# ---------------------------------------------------------------------------
# Core function
# ---------------------------------------------------------------------------


async def check_and_consume(
    *,
    redis,
    actor_kind: Literal["api_key", "user"],
    actor_id: UUID,
    workspace_id: UUID,
    limits: dict[RateLimitScope, int],
) -> None:
    """Increment each applicable bucket and raise RateLimitExceeded on first hit.

    Uses INCR + EXPIRE(nx=True) pipeline so the TTL is only set on the first
    write, preserving the rolling window.  The INCR is not rolled back on
    exceed — the spec allows the small race; the bucket naturally drains when
    the key expires.
    """
    applicable = _scopes_for_actor(actor_kind)

    for scope in applicable:
        if scope not in limits:
            continue

        limit = limits[scope]
        key = _redis_key(scope, actor_id, workspace_id)
        ttl = _TTL[scope]

        pipe = redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, ttl, nx=True)
        results = await pipe.execute()
        count: int = results[0]

        if count > limit:
            remaining_ttl = await redis.ttl(key)
            raise RateLimitExceeded(
                scope=scope,
                limit=limit,
                retry_after_seconds=max(remaining_ttl, 1),
            )


# ---------------------------------------------------------------------------
# Default limits helper
# ---------------------------------------------------------------------------


def default_limits_from_config() -> dict[RateLimitScope, int]:
    """Build a limits dict from the global ``Settings`` (operator-level config).

    Rate limits are no longer per-workspace knobs — they live in env vars
    (``AGENT_RATE_LIMIT_*``). See ``app.core.config.Settings`` for defaults.
    """
    from app.core.config import settings

    return {
        RateLimitScope.API_KEY_HOUR: int(settings.agent_rate_limit_api_key_per_hour),
        RateLimitScope.API_KEY_DAY: int(settings.agent_rate_limit_api_key_per_day),
        RateLimitScope.USER_DAY: int(settings.agent_rate_limit_user_per_day),
        RateLimitScope.WORKSPACE_DAY: int(settings.agent_rate_limit_workspace_per_day),
    }


# DEPRECATED: rate limits moved from per-workspace settings to env config.
# Thin alias kept so existing callers/tests keep working; ignores its argument
# and reads from the global Settings.
def default_limits_for_workspace(settings=None) -> dict[RateLimitScope, int]:  # noqa: ARG001
    return default_limits_from_config()
