from __future__ import annotations
import asyncio
import hashlib
import time
from abc import ABC, abstractmethod
from typing import List, Optional, Tuple

import numpy as np

from app.config import settings
from app.services.cache import cache
from app.utils.logger import logger


# ---- L2 归一化 ----

def l2_normalize(vectors: List[List[float]]) -> List[List[float]]:
    arr = np.array(vectors, dtype=np.float64)
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    return (arr / norms).tolist()


# ---- 文本预处理（简版，与 preprocess 配合） ----

from app.rag.preprocess import clean_text as _clean


# ---- 缓存 ----

EMBED_CACHE_PREFIX = "emb"

async def _get_or_compute_embed(text: str, compute_fn, ttl: int = 3600) -> List[float]:
    """缓存穿透/雪崩防护：走 cache.get_or_compute"""
    return await cache.get_or_compute(
        prefix=EMBED_CACHE_PREFIX,
        key=text,
        compute_func=compute_fn,
        ttl=ttl,
        stale_ttl=ttl * 3,
    )


# ---- 熔断器 ----

class EmbedCircuitBreaker:
    def __init__(self, threshold: int = 3, recovery: float = 30.0):
        self.threshold = threshold
        self.recovery = recovery
        self._failures = 0
        self._last_fail = 0.0
        self._state = "closed"

    def record_success(self):
        self._failures = 0
        self._state = "closed"

    def record_failure(self):
        self._failures += 1
        self._last_fail = time.time()
        if self._failures >= self.threshold:
            self._state = "open"

    @property
    def is_open(self) -> bool:
        if self._state == "open":
            if time.time() - self._last_fail > self.recovery:
                self._state = "half-open"
                return False
            return True
        return False


# ---- 嵌入器基类 ----

class BaseEmbedder(ABC):
    @abstractmethod
    async def embed(self, texts: List[str]) -> List[List[float]]:
        ...

    async def embed_one(self, text: str) -> List[float]:
        return (await self.embed([text]))[0]


# ---- 本地 BGE 嵌入器 ----

class LocalBGEEmbedder(BaseEmbedder):
    def __init__(self, model_name: str = "BAAI/bge-small-zh-v1.5"):
        self._model_name = model_name
        self._model = None
        self._ready = False

    async def _ensure_model(self):
        if self._ready:
            return
        loop = asyncio.get_running_loop()

        def _load():
            from sentence_transformers import SentenceTransformer
            return SentenceTransformer(self._model_name, device="cpu", local_files_only=True)

        try:
            self._model = await loop.run_in_executor(None, _load)
            self._ready = True
            logger.info(f"BGE embedder loaded: {self._model_name} (dim={self._model.get_embedding_dimension()})")
        except Exception as e:
            logger.warning(f"BGE model load failed (try downloading first): {e}")
            try:
                self._model = await loop.run_in_executor(None, lambda: SentenceTransformer(self._model_name, device="cpu"))
                self._ready = True
                logger.info(f"BGE embedder loaded (online): {self._model_name} (dim={self._model.get_embedding_dimension()})")
            except Exception as e2:
                logger.warning(f"BGE model load failed (online): {e2}")
                self._ready = False

    async def embed(self, texts: List[str]) -> List[List[float]]:
        await self._ensure_model()
        if not self._ready or not texts:
            return [[0.0] * 512] * len(texts)

        loop = asyncio.get_running_loop()
        cleaned = [_clean(t) for t in texts]

        def _encode():
            with _suppress_stdout_stderr():
                return self._model.encode(cleaned, show_progress_bar=False, normalize_embeddings=True)

        vecs = await loop.run_in_executor(None, _encode)
        return vecs.tolist()


# ---- 在线 API 嵌入器 ----

class OnlineEmbedder(BaseEmbedder):
    def __init__(self, api_key: str, base_url: str, model: str = "text-embedding-ada-002"):
        if not api_key:
            raise ValueError("API key required for online embedder")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model

    async def embed(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        import httpx

        cleaned = [_clean(t) for t in texts]
        url = f"{self._base_url}/embeddings"

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                url,
                json={"model": self._model, "input": cleaned},
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
            resp.raise_for_status()
            data = resp.json()
            ordered = sorted(data["data"], key=lambda x: x["index"])
            return [item["embedding"] for item in ordered]


# ---- 上下文管理器：压制 sentence-transformers 的 INFO 日志 ----

import contextlib
import io
import sys


@contextlib.contextmanager
def _suppress_stdout_stderr():
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = io.StringIO(), io.StringIO()
    try:
        yield
    finally:
        sys.stdout, sys.stderr = old_out, old_err


# ---- 统一嵌入服务 ----

class EmbeddingService:
    """统一嵌入服务，支持：
    - 双模式切换（online / local / auto）
    - 自动熔断降级（online → local → 零向量兜底）
    - 向量缓存（Redis）
    - L2 归一化
    - 批量处理
    """

    def __init__(self):
        self._mode = settings.EMBED_MODE
        self._online_cb = EmbedCircuitBreaker(threshold=2, recovery=30.0)
        self._local_cb = EmbedCircuitBreaker(threshold=2, recovery=30.0)
        self._dim = 512  # BGE 默认维度

        self._online: Optional[OnlineEmbedder] = None
        self._local: Optional[LocalBGEEmbedder] = None

        if settings.EMBED_ONLINE_KEY:
            try:
                self._online = OnlineEmbedder(
                    api_key=settings.EMBED_ONLINE_KEY,
                    base_url=settings.EMBED_ONLINE_URL,
                    model=settings.EMBED_ONLINE_MODEL,
                )
            except Exception as e:
                logger.warning(f"Online embedder init failed: {e}")

        try:
            self._local = LocalBGEEmbedder(model_name=settings.EMBED_LOCAL_MODEL)
        except Exception as e:
            logger.warning(f"Local embedder init failed: {e}")
            self._local = None

        logger.info(f"Embedding service: mode={self._mode}")

    async def embed(self, texts: List[str], use_cache: bool = True) -> List[List[float]]:
        if not texts:
            return []

        async def compute_all():
            cleaned = [_clean(t) for t in texts]
            vecs = await self._try_embed(cleaned)
            if vecs is None:
                vecs = [[0.0] * self._dim] * len(cleaned)
            return l2_normalize(vecs)

        if not use_cache:
            return await compute_all()

        async def compute_one(t: str):
            cleaned = _clean(t)
            vecs = await self._try_embed([cleaned])
            return l2_normalize(vecs)[0] if vecs else [0.0] * self._dim

        tasks = [_get_or_compute_embed(t, lambda t=t: compute_one(t)) for t in texts]
        results = await asyncio.gather(*tasks)
        return l2_normalize(results)

    async def embed_one(self, text: str) -> List[float]:
        return (await self.embed([text]))[0]

    async def _try_embed(self, texts: List[str]) -> Optional[List[List[float]]]:
        """多级尝试：online → local → None（零向量）"""
        candidates = []

        if self._online and not self._online_cb.is_open and (self._mode in ("online", "auto")):
            candidates.append(("online", self._online.embed(texts), self._online_cb))

        if self._local and not self._local_cb.is_open and (self._mode in ("local", "auto")):
            candidates.append(("local", self._local.embed(texts), self._local_cb))

        for name, coro, cb in candidates:
            try:
                vecs = await coro
                if vecs and any(any(v != 0 for v in row) for row in vecs):
                    cb.record_success()
                    return vecs
                cb.record_failure()
                logger.warning(f"{name} embed returned zero vectors")
            except Exception as e:
                cb.record_failure()
                logger.warning(f"{name} embed failed: {e}")

        return None


embed_service = EmbeddingService()
