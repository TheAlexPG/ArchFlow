import redis.asyncio as aioredis

from app.core.config import settings

# Single shared async Redis client. redis-py connection pools are lazy and
# thread-safe; creating one module-level client is the standard pattern.
redis_client: aioredis.Redis = aioredis.from_url(
    settings.redis_url, encoding="utf-8", decode_responses=True
)
