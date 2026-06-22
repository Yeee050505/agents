from __future__ import annotations
import asyncio
import hashlib
import time
from typing import Optional
from app.config import settings
from app.utils.logger import logger


class LLMResponseCache:
    def __init__(self, max_size: int = 1000, ttl: int = 3600):
        self._cache: dict[str, tuple[str, float]] = {}
        self._max_size = max_size
        self._ttl = ttl
        self._lock = asyncio.Lock()
        self._hits = 0
        self._misses = 0

    def _make_key(self, system_prompt: str, user_message: str, temperature: float) -> str:
        content = f"{system_prompt}|||{user_message}|||{temperature:.1f}"
        return hashlib.sha256(content.encode()).hexdigest()

    async def get(self, system_prompt: str, user_message: str, temperature: float) -> Optional[str]:
        key = self._make_key(system_prompt, user_message, temperature)
        async with self._lock:
            entry = self._cache.get(key)
            if entry:
                value, expiry = entry
                if time.time() < expiry:
                    self._hits += 1
                    return value
                del self._cache[key]
            self._misses += 1
            return None

    async def set(self, system_prompt: str, user_message: str, temperature: float, value: str):
        key = self._make_key(system_prompt, user_message, temperature)
        async with self._lock:
            if len(self._cache) >= self._max_size:
                oldest = min(self._cache.keys(), key=lambda k: self._cache[k][1])
                del self._cache[oldest]
            self._cache[key] = (value, time.time() + self._ttl)

    async def invalidate(self, system_prompt: str, user_message: str, temperature: float):
        key = self._make_key(system_prompt, user_message, temperature)
        async with self._lock:
            self._cache.pop(key, None)

    def stats(self) -> dict:
        return {
            "size": len(self._cache),
            "max_size": self._max_size,
            "ttl": self._ttl,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": f"{self._hits / max(self._hits + self._misses, 1) * 100:.1f}%",
        }


llm_cache = LLMResponseCache()
