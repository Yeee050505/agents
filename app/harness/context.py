from __future__ import annotations
import time
from typing import Optional
from app.utils.logger import logger

MAX_RAW_CONTEXT = 3000
MAX_TOTAL = 4000

_COMPRESS_PROMPT = """将以下对话历史压缩为一段简短摘要，保留关键信息（用户偏好、已确认的事实、重要结论）。
忽略问候、感谢、临时上下文。只输出摘要文本，不要额外说明。"""


def should_compress(context: str) -> bool:
    return len(context) > MAX_RAW_CONTEXT


async def compress(context: str, recent_turns: list[dict]) -> str:
    if not should_compress(context):
        return context

    try:
        from app.services.llm_pool import llm_pool
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import SystemMessage, HumanMessage
        from app.config import settings

        inst = await llm_pool.get_next_instance()
        if not inst:
            return _truncate(context)

        llm = ChatOpenAI(
            model=settings.LLM_MODEL,
            openai_api_key=inst.api_key,
            openai_api_base=settings.LLM_BASE_URL,
            timeout=15,
            temperature=0.1,
            max_retries=1,
        )

        result = await llm.ainvoke([
            SystemMessage(content=_COMPRESS_PROMPT),
            HumanMessage(content=context),
        ])
        compressed = result.content.strip()

        # Keep last 1 turn as-is for immediate continuity
        recent_text = _format_recent(recent_turns)

        merged = f"[历史摘要] {compressed}"
        if recent_text:
            merged += f"\n\n[最近对话]\n{recent_text}"

        await inst.record_success()
        logger.info(f"Context compressed: {len(context)} → {len(merged)} chars")
        return merged

    except Exception as e:
        logger.warning(f"Context compression failed: {e}")
        return _truncate(context)


def _format_recent(turns: list[dict]) -> str:
    if not turns:
        return ""
    lines = []
    for m in turns[-2:]:
        role = "用户" if m.get("role") == "user" else "助手"
        lines.append(f"{role}: {m.get('content', '')[:300]}")
    return "\n".join(lines)


def _truncate(text: str, max_len: int = MAX_TOTAL) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + f"\n...（省略 {len(text) - max_len} 字符）"
