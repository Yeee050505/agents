from __future__ import annotations
import asyncio
import json
import time
from typing import List, Dict, Optional
from app.utils.logger import logger

_memory_store: Dict[str, dict] = {}
MAX_HISTORY_LENGTH = 20
SESSION_TTL = 3600

_REDIS_REACHABLE: Optional[bool] = None


async def _redis_reachable() -> bool:
    global _REDIS_REACHABLE
    if _REDIS_REACHABLE is not None:
        return _REDIS_REACHABLE
    try:
        from app.config import settings
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(settings.REDIS_HOST, settings.REDIS_PORT),
            timeout=2,
        )
        writer.close()
        await writer.wait_closed()
        _REDIS_REACHABLE = True
    except Exception:
        _REDIS_REACHABLE = False
    return _REDIS_REACHABLE


async def get_history(session_id: str) -> List[Dict[str, str]]:
    if await _redis_reachable():
        try:
            import redis.asyncio as aioredis
            from app.config import settings

            r = aioredis.Redis(
                host=settings.REDIS_HOST, port=settings.REDIS_PORT,
                db=settings.REDIS_DB, password=settings.REDIS_PASSWORD or None,
                decode_responses=True,
            )
            try:
                data = await r.get(f"session:{session_id}")
                if data:
                    return json.loads(data)
            finally:
                await r.aclose()
        except Exception:
            pass

    entry = _memory_store.get(session_id)
    if entry and time.time() - entry["ts"] < SESSION_TTL:
        return entry["messages"]
    return []


async def save_history(session_id: str, messages: List[Dict[str, str]]):
    recent = messages[-MAX_HISTORY_LENGTH:]

    if await _redis_reachable():
        try:
            import redis.asyncio as aioredis
            from app.config import settings

            r = aioredis.Redis(
                host=settings.REDIS_HOST, port=settings.REDIS_PORT,
                db=settings.REDIS_DB, password=settings.REDIS_PASSWORD or None,
                decode_responses=True,
            )
            try:
                await r.setex(f"session:{session_id}", SESSION_TTL, json.dumps(recent, ensure_ascii=False))
                return
            finally:
                await r.aclose()
        except Exception:
            pass

    _memory_store[session_id] = {"messages": recent, "ts": time.time()}


async def clear_history(session_id: str):
    _memory_store.pop(session_id, None)
    if await _redis_reachable():
        try:
            import redis.asyncio as aioredis
            from app.config import settings

            r = aioredis.Redis(
                host=settings.REDIS_HOST, port=settings.REDIS_PORT,
                db=settings.REDIS_DB, password=settings.REDIS_PASSWORD or None,
            )
            try:
                await r.delete(f"session:{session_id}")
            finally:
                await r.aclose()
        except Exception:
            pass
