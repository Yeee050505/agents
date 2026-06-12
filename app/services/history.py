from __future__ import annotations
import json
import time
from typing import List, Dict, Optional
from app.utils.logger import logger

# 内存会话存储（Redis 不可用时的降级方案）
_memory_store: Dict[str, dict] = {}
MAX_HISTORY_LENGTH = 20
SESSION_TTL = 3600  # 1小时过期


async def get_history(session_id: str) -> List[Dict[str, str]]:
    """获取会话历史"""
    # 尝试 Redis
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
            await r.close()
    except Exception:
        pass

    # 内存降级
    entry = _memory_store.get(session_id)
    if entry and time.time() - entry["ts"] < SESSION_TTL:
        return entry["messages"]
    return []


async def save_history(session_id: str, messages: List[Dict[str, str]]):
    """保存会话历史"""
    recent = messages[-MAX_HISTORY_LENGTH:]

    # 尝试 Redis
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
            await r.close()
    except Exception:
        pass

    # 内存降级
    _memory_store[session_id] = {"messages": recent, "ts": time.time()}


async def clear_history(session_id: str):
    """清除会话"""
    _memory_store.pop(session_id, None)
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
            await r.close()
    except Exception:
        pass
