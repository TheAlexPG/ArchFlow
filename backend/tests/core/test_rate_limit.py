import uuid

import pytest

from app.core.rate_limit import RateLimit, check
from app.core.redis import redis_client


@pytest.fixture
async def caller_scope():
    caller = f"test-{uuid.uuid4().hex[:8]}"
    yield caller
    # Cleanup the sorted sets this caller created.
    async for key in redis_client.scan_iter(f"rl:*:{caller}:*"):
        await redis_client.delete(key)


async def test_sliding_window_allows_up_to_limit(caller_scope):
    limits = (RateLimit(limit=3, window_seconds=60),)
    for i in range(3):
        r = await check(caller_scope, scope="t", limits=limits)
        assert r.allowed, f"request {i} was denied but should fit in the window"
        assert r.remaining == 3 - i - 1
    # 4th call blows it
    r = await check(caller_scope, scope="t", limits=limits)
    assert not r.allowed
    assert r.remaining == 0
    assert r.retry_after >= 1


async def test_tightest_bucket_wins(caller_scope):
    # 1000/hour and 2/min — after 2 calls, the minute bucket should deny even
    # though the hour bucket has plenty of room.
    limits = (
        RateLimit(limit=1000, window_seconds=3600),
        RateLimit(limit=2, window_seconds=60),
    )
    for _ in range(2):
        r = await check(caller_scope, scope="t2", limits=limits)
        assert r.allowed
    r = await check(caller_scope, scope="t2", limits=limits)
    assert not r.allowed
    assert r.limit == 2, "retry should surface the tightest bucket"
