"""Sliding-window rate limiter backed by Redis sorted sets.

One SET per (caller, window) pair. Each request is added with the current
timestamp as both member and score; stale entries (outside the window) are
trimmed before counting. This gives true sliding-window semantics without
needing background cleanup.
"""
import time
import uuid
from dataclasses import dataclass

from app.core.redis import redis_client


@dataclass
class RateLimit:
    """A single sliding-window bucket."""

    limit: int
    window_seconds: int

    @property
    def key_fragment(self) -> str:
        return f"{self.window_seconds}s"


# Default buckets. 60 requests/minute AND 1000 requests/hour — whichever runs
# out first triggers the 429. These are deliberately permissive; tighten per
# deploy via env if needed.
DEFAULT_LIMITS: tuple[RateLimit, ...] = (
    RateLimit(limit=60, window_seconds=60),
    RateLimit(limit=1000, window_seconds=3600),
)


@dataclass
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    # Epoch seconds when the current window's oldest entry rolls off, which
    # equals the point at which the client can make another request if they
    # are at the cap.
    reset_at: int
    retry_after: int  # 0 when allowed


async def check(
    caller_id: str, scope: str = "default", limits: tuple[RateLimit, ...] = DEFAULT_LIMITS
) -> RateLimitResult:
    """Attempt to consume one token under every bucket in `limits`.

    Returns the tightest bucket (the one with the least remaining capacity).
    When any bucket is exhausted the call is denied and the response carries
    its retry-after.
    """
    now_ms = int(time.time() * 1000)
    request_id = f"{now_ms}-{uuid.uuid4().hex[:8]}"

    worst: RateLimitResult | None = None

    for bucket in limits:
        key = f"rl:{scope}:{caller_id}:{bucket.key_fragment}"
        window_ms = bucket.window_seconds * 1000
        cutoff = now_ms - window_ms

        async with redis_client.pipeline(transaction=True) as pipe:
            pipe.zremrangebyscore(key, 0, cutoff)
            pipe.zadd(key, {request_id: now_ms})
            pipe.zcard(key)
            pipe.pexpire(key, window_ms)
            results = await pipe.execute()
        count: int = results[2]

        if count > bucket.limit:
            # Over the limit — undo our own ZADD so retry-counting is honest.
            await redis_client.zrem(key, request_id)
            oldest = await redis_client.zrange(key, 0, 0, withscores=True)
            reset_ms = int(oldest[0][1]) + window_ms if oldest else now_ms + window_ms
            retry_after = max(1, (reset_ms - now_ms) // 1000)
            candidate = RateLimitResult(
                allowed=False,
                limit=bucket.limit,
                remaining=0,
                reset_at=reset_ms // 1000,
                retry_after=int(retry_after),
            )
        else:
            remaining = bucket.limit - count
            oldest = await redis_client.zrange(key, 0, 0, withscores=True)
            reset_ms = int(oldest[0][1]) + window_ms if oldest else now_ms + window_ms
            candidate = RateLimitResult(
                allowed=True,
                limit=bucket.limit,
                remaining=remaining,
                reset_at=reset_ms // 1000,
                retry_after=0,
            )

        if worst is None or candidate.remaining < worst.remaining or (
            not candidate.allowed and worst.allowed
        ):
            worst = candidate

    assert worst is not None
    return worst
