from __future__ import annotations
import time
import threading
from typing import Dict, Optional

import redis
from fastapi import HTTPException, Request
from app.config import settings
from app.utils.logger import logger


TOKEN_BUCKET_LUA = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local rate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local requested = tonumber(ARGV[4])

local tokens = redis.call('HGET', key, 'tokens')
local last_refill = redis.call('HGET', key, 'last_refill')

if not tokens then
    tokens = capacity
    last_refill = now
else
    tokens = tonumber(tokens)
    last_refill = tonumber(last_refill)
    local elapsed = now - last_refill
    tokens = math.min(capacity, tokens + elapsed * rate)
end

if tokens >= requested then
    tokens = tokens - requested
    redis.call('HSET', key, 'tokens', tokens)
    redis.call('HSET', key, 'last_refill', now)
    redis.call('EXPIRE', key, 120)
    return 1
else
    redis.call('HSET', key, 'tokens', tokens)
    redis.call('HSET', key, 'last_refill', now)
    redis.call('EXPIRE', key, 120)
    return 0
end
"""


class RedisTokenBucket:
    """基于 Redis + Lua 的分布式令牌桶"""
    def __init__(self, key_prefix: str, rate: float, capacity: int):
        self.key_prefix = key_prefix
        self.rate = rate
        self.capacity = capacity
        self._script_hash: Optional[str] = None

    def _get_redis(self):
        return redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=settings.REDIS_DB,
            password=settings.REDIS_PASSWORD or None,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )

    def acquire(self, key: str = "global", tokens: int = 1) -> bool:
        try:
            r = self._get_redis()
            redis_key = f"rate:{self.key_prefix}:{key}"
            result = r.eval(
                TOKEN_BUCKET_LUA, 1, redis_key,
                str(self.capacity), str(self.rate),
                str(time.time()), str(tokens),
            )
            return result == 1
        except Exception as e:
            logger.warning(f"Redis rate limiter failed, using memory fallback: {e}")
            return None

    def stats(self, key: str = "global") -> dict:
        try:
            r = self._get_redis()
            redis_key = f"rate:{self.key_prefix}:{key}"
            data = r.hgetall(redis_key)
            return {
                "tokens": round(float(data.get("tokens", self.capacity)), 2),
                "capacity": self.capacity,
                "rate": self.rate,
            }
        except Exception:
            return {"tokens": self.capacity, "capacity": self.capacity, "rate": self.rate}


class MemoryTokenBucket:
    """内存降级令牌桶（无 Redis 时使用）"""
    def __init__(self, rate: float, capacity: int):
        self.rate = rate
        self.capacity = capacity
        self.tokens = float(capacity)
        self.last_refill = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self):
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.last_refill = now

    def acquire(self, tokens: int = 1) -> bool:
        with self._lock:
            self._refill()
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False

    def stats(self) -> dict:
        with self._lock:
            self._refill()
            return {
                "tokens": round(self.tokens, 2),
                "capacity": self.capacity,
                "rate": self.rate,
            }


class RateLimiterRegistry:
    def __init__(self):
        self._redis_global = RedisTokenBucket("global", settings.GLOBAL_RATE, settings.GLOBAL_CAPACITY)
        self._redis_user = RedisTokenBucket("user", settings.USER_RATE, settings.USER_CAPACITY)
        self._mem_global = MemoryTokenBucket(settings.GLOBAL_RATE, settings.GLOBAL_CAPACITY)
        self._mem_users: dict[str, MemoryTokenBucket] = {}
        self._user_lock = threading.Lock()
        self._redis_available: Optional[bool] = None

    def _is_redis_available(self) -> bool:
        if self._redis_available is None:
            try:
                r = redis.Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, socket_connect_timeout=1)
                r.ping()
                self._redis_available = True
                logger.info("Redis available for rate limiting")
            except Exception:
                self._redis_available = False
                logger.info("Redis unavailable, using in-memory rate limiting")
        return self._redis_available

    def check_global(self) -> bool:
        if self._is_redis_available():
            result = self._redis_global.acquire()
            if result is not None:
                return result
        return self._mem_global.acquire()

    def check_user(self, user_id: str) -> bool:
        if self._is_redis_available():
            result = self._redis_user.acquire(user_id)
            if result is not None:
                return result
        with self._user_lock:
            if user_id not in self._mem_users:
                self._mem_users[user_id] = MemoryTokenBucket(settings.USER_RATE, settings.USER_CAPACITY)
            return self._mem_users[user_id].acquire()

    def get_global_stats(self) -> dict:
        if self._is_redis_available():
            return self._redis_global.stats()
        return self._mem_global.stats()

    def get_user_stats(self, user_id: str) -> dict | None:
        if self._is_redis_available():
            stats = self._redis_user.stats(user_id)
            if stats:
                stats["user_id"] = user_id
                return stats
        with self._user_lock:
            bucket = self._mem_users.get(user_id)
            if not bucket:
                return None
            stats = bucket.stats()
            stats["user_id"] = user_id
            return stats


rate_limiter = RateLimiterRegistry()


def apply_rate_limit(user_id: str | None = None):
    if not rate_limiter.check_global():
        logger.warning("Global rate limit exceeded")
        raise HTTPException(status_code=429, detail="全局限流：请求过于频繁，请稍后重试")
    if user_id and not rate_limiter.check_user(user_id):
        logger.warning("User rate limit exceeded", extra={"user_id": user_id})
        raise HTTPException(status_code=429, detail="用户限流：请求频率过高，请稍后重试")


class RateLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        user_id = getattr(request.state, "user_id", None)
        try:
            apply_rate_limit(user_id)
        except HTTPException:
            from fastapi.responses import JSONResponse
            response = JSONResponse(
                status_code=429,
                content={"code": 429, "msg": "请求过于频繁，请稍后重试"},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
