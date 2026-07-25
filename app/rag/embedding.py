from __future__ import annotations
from typing import List


class StubEmbedder:
    async def embed(self, texts: List[str]) -> List[List[float]]:
        return [[0.0] * 384] * len(texts)

    async def embed_one(self, text: str) -> List[float]:
        return [0.0] * 384


embed_service = StubEmbedder()
