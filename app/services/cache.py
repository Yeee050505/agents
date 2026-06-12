from __future__ import annotations
import json
import hashlib
from typing import Any, Optional, Callable
import redis.asyncio as aioredis
from app.config import settings
from app.utils.logger import logger


class CacheService:
    def __init__(self):
        self._client: Optional[aioredis.Redis] = None

    async def init(self):
        self._client = aioredis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=settings.REDIS_DB,
            password=settings.REDIS_PASSWORD or None,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        try:
            await self._client.ping()
            logger.info("Redis connected")
        except Exception as e:
            logger.warning(f"Redis unavailable, cache disabled: {e}")
            self._client = None

    async def close(self):
        if self._client:
            await self._client.close()

    def _is_ready(self) -> bool:
        return self._client is not None

    def _make_key(self, prefix: str, key: str) -> str:
        return f"{prefix}:{hashlib.md5(key.encode()).hexdigest()}"

    # Cache Penetration: store null marker for short TTL
    NULL_MARKER = "__NULL__"

    async def get_or_compute(
        self,
        prefix: str,
        key: str,
        compute_func: Callable,
        ttl: int = 300,
        stale_ttl: int = 3600,
    ) -> Any:
        if not self._is_ready():
            return await compute_func()

        cache_key = self._make_key(prefix, key)
        cached = await self._client.get(cache_key)

        if cached is not None:
            if cached == self.NULL_MARKER:
                return None
            return json.loads(cached)

        value = await compute_func()

        if value is None:
            # Cache penetration protection: store null for short time
            await self._client.setex(cache_key, 60, self.NULL_MARKER)
            return None

        # Cache avalanche protection: add jitter to TTL
        import random
        jitter = random.randint(0, 60)
        await self._client.setex(cache_key, ttl + jitter, json.dumps(value, default=str))
        return value

    async def invalidate(self, prefix: str, key: str):
        if not self._is_ready():
            return
        cache_key = self._make_key(prefix, key)
        await self._client.delete(cache_key)

    async def invalidate_prefix(self, prefix: str):
        if not self._is_ready():
            return
        cursor = 0
        pattern = f"{prefix}:*"
        while True:
            cursor, keys = await self._client.scan(cursor=cursor, match=pattern, count=100)
            if keys:
                await self._client.delete(*keys)
            if cursor == 0:
                break


cache = CacheService()
