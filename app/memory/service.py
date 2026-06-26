from __future__ import annotations
from typing import List, Optional

from app.memory.schema import MemoryFragment
from app.memory.store import memory_store
from app.memory.extractor import extract_facts
from app.utils.logger import logger


class MemoryService:
    async def recall(self, query: str, user_id: str, k: int = 5) -> str:
        """语义召回用户的记忆片段，返回格式化文本供注入 system prompt"""
        if not query or not user_id:
            return ""

        from app.rag.embedding import embed_service

        try:
            q_vec = await embed_service.embed_one(query)
        except Exception:
            return ""

        hits = memory_store.search(user_id, q_vec, k=k)
        if not hits:
            return ""

        lines = ["以下是关于该用户已知的信息（来自历史对话记忆）："]
        for h in hits:
            lines.append(f"- [{h.category}] {h.content}")
        return "\n".join(lines)

    async def extract(
        self,
        conversation: str,
        user_id: str,
        llm_func,
        session_id: str = "",
    ):
        """后台异步提取记忆，不阻塞响应"""
        if not conversation or not user_id:
            return

        facts = await extract_facts(conversation, llm_func)
        if not facts:
            return

        fragments = []
        for f in facts:
            frag = MemoryFragment(
                content=f["content"],
                category=f["category"],
                user_id=user_id,
                source_session=session_id,
            )
            # 生成 embedding
            try:
                from app.rag.embedding import embed_service
                frag.embedding = await embed_service.embed_one(f["content"])
            except Exception:
                pass
            fragments.append(frag)

        memory_store.append(user_id, fragments)

    async def list_memories(self, user_id: str) -> List[dict]:
        return memory_store.list_memories(user_id)

    async def delete_memory(self, user_id: str, memory_id: str) -> bool:
        return memory_store.delete_memory(user_id, memory_id)


memory_service = MemoryService()
