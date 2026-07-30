from __future__ import annotations
import asyncio
import json
import uuid
import time
from pathlib import Path
from typing import List, Optional
import numpy as np

from app.utils.logger import logger

MEMORY_FILE = Path(__file__).parent.parent.parent / "data" / "long_term_memory.json"

EXTRACT_PROMPT = """从以下对话中提取值得长期记住的信息。
只提取：用户偏好、纠正过的事实、讨论过的关键结论。
忽略：问候语、感谢、临时上下文、无实质内容的对话。

规则：
1. 每条一句话，保持简洁，去掉修饰词
2. 如果没有什么值得记住的，返回空
3. 多条用 | 分隔"""


_EMBED_FAILED = "_EMBED_FAILED"

class LongTermMemory:
    def __init__(self, dim: int = 768, top_k: int = 3):
        self._memories: List[dict] = []
        self._dim = dim
        self._top_k = top_k
        self._embedder = None
        self._load()

    @property
    def _model(self):
        if self._embedder is _EMBED_FAILED:
            return None
        if self._embedder is not None:
            return self._embedder
        try:
            from app.config import settings
            model_name = settings.EMBED_LOCAL_MODEL or "BAAI/bge-base-zh-v1.5"

            # Quick connectivity check — skip download if HuggingFace unreachable
            import urllib.request
            import urllib.error
            host = model_name.split("/")[0] if "/" in model_name else "huggingface.co"
            req = urllib.request.Request(f"https://{host}", method="HEAD")
            urllib.request.urlopen(req, timeout=3)

            from sentence_transformers import SentenceTransformer
            self._embedder = SentenceTransformer(model_name, device="cpu")
            logger.info(f"LongTermMemory: embedder loaded ({model_name})")
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as conn_err:
            logger.warning(f"LongTermMemory: {host} unreachable ({conn_err}) — falling back to zero vectors")
            self._embedder = _EMBED_FAILED
        except Exception as e:
            logger.warning(f"LongTermMemory: embedder failed ({e}) — falling back to zero vectors")
            self._embedder = _EMBED_FAILED
        return None if self._embedder is _EMBED_FAILED else self._embedder

    def _load(self):
        if MEMORY_FILE.exists():
            try:
                data = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
                self._memories = data.get("memories", [])
                logger.info(f"LongTermMemory: loaded {len(self._memories)} memories")
            except Exception as e:
                logger.warning(f"LongTermMemory: load failed: {e}")

    def _save(self):
        MEMORY_FILE.write_text(
            json.dumps({"memories": self._memories}, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

    def _embed(self, texts: List[str]) -> List[List[float]]:
        model = self._model
        if model is None or not texts:
            return [[0.0] * self._dim] * len(texts)
        try:
            vecs = model.encode(texts, show_progress_bar=False, normalize_embeddings=True)
            return vecs.tolist()
        except Exception as e:
            logger.warning(f"LongTermMemory embed failed: {e}")
            return [[0.0] * self._dim] * len(texts)

    async def _extract(self, user_msg: str, assistant_msg: str) -> List[str]:
        """LLM 精炼提取值得记住的信息"""
        from app.config import settings
        from app.services.llm_pool import llm_pool
        inst = await llm_pool.get_next_instance()
        if not inst:
            return []
        try:
            from langchain_openai import ChatOpenAI
            from langchain_core.messages import SystemMessage, HumanMessage
            llm = ChatOpenAI(
                model=settings.LLM_MODEL,
                openai_api_key=inst.api_key,
                openai_api_base=settings.LLM_BASE_URL,
                timeout=15,
                temperature=0.1,
                max_retries=1,
            )
            prompt = f"用户: {user_msg}\n助手: {assistant_msg}"
            result = await asyncio.wait_for(
                llm.ainvoke([SystemMessage(content=EXTRACT_PROMPT), HumanMessage(content=prompt)]),
                timeout=15,
            )
            await inst.record_success()
            raw = result.content.strip()
            if not raw or raw == "空":
                return []
            items = [s.strip() for s in raw.split("|") if s.strip()]
            return items[:3]
        except Exception as e:
            await inst.record_failure()
            logger.warning(f"LongTermMemory extract failed: {e}")
            return []

    def _dedup(self, text: str, threshold: float = 0.85) -> bool:
        """检查是否已有相似记忆，余弦相似度"""
        if not self._memories or self._model is None or not self._memories[0].get("embedding"):
            return False
        vec = self._embed([text])[0]
        if all(v == 0 for v in vec):
            return False
        arr = np.array([m["embedding"] for m in self._memories if m.get("embedding")], dtype=np.float64)
        sims = arr @ np.array(vec, dtype=np.float64)
        best = float(np.max(sims)) if sims.size > 0 else 0
        return best > threshold

    async def process_turn(self, session_id: str, user_msg: str, assistant_msg: str):
        extracted = await self._extract(user_msg, assistant_msg)
        if not extracted:
            return
        texts = [e for e in extracted if not self._dedup(e)]
        if not texts:
            return
        vecs = self._embed(texts)
        for i, t in enumerate(texts):
            self._memories.append({
                "id": str(uuid.uuid4()),
                "text": t,
                "embedding": vecs[i],
                "timestamp": time.time(),
                "session_id": session_id,
            })
        self._save()
        logger.info(f"LongTermMemory: stored {len(texts)} new memories")

    def retrieve(self, query: str, k: Optional[int] = None) -> List[str]:
        if not self._memories:
            return []
        k = k or self._top_k
        if self._model is None:
            return [m["text"] for m in self._memories[:k]]
        q_vec = self._embed([query])[0]
        arr = np.array([m["embedding"] for m in self._memories if m.get("embedding")], dtype=np.float64)
        if arr.size == 0:
            return [m["text"] for m in self._memories[:k]]
        sims = arr @ np.array(q_vec, dtype=np.float64)
        top_indices = np.argsort(sims)[-k:][::-1]
        return [self._memories[i]["text"] for i in top_indices if sims[i] > 0.3]

    def stats(self) -> dict:
        return {"total": len(self._memories), "file": str(MEMORY_FILE)}


long_memory = LongTermMemory()
