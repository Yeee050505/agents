from __future__ import annotations
import hashlib
import json
import time
from pathlib import Path
from typing import List, Optional

import numpy as np

from app.memory.schema import MemoryFragment, MAX_MEMORIES_PER_USER
from app.utils.logger import logger

MEMORY_DIR = Path(__file__).parent.parent.parent / "data" / "memory"


def _user_path(user_id: str) -> Path:
    safe = user_id.replace("/", "_").replace("\\", "_")
    return MEMORY_DIR / f"user_{safe}.json"


class MemoryStore:
    def __init__(self):
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)

    # --- read / write ---

    def load(self, user_id: str) -> List[MemoryFragment]:
        p = _user_path(user_id)
        if not p.exists():
            return []
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return [MemoryFragment.from_dict(d) for d in data.get("memories", [])]
        except Exception as e:
            logger.warning(f"Memory load failed: {user_id}: {e}")
            return []

    def save(self, user_id: str, fragments: List[MemoryFragment]):
        p = _user_path(user_id)
        p.write_text(
            json.dumps({"memories": [f.to_dict() for f in fragments]}, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

    # --- CRUD ---

    def list_memories(self, user_id: str) -> List[dict]:
        return [f.to_dict() for f in self.load(user_id)]

    def delete_memory(self, user_id: str, memory_id: str) -> bool:
        fragments = self.load(user_id)
        before = len(fragments)
        fragments = [f for f in fragments if f.memory_id != memory_id]
        if len(fragments) == before:
            return False
        self.save(user_id, fragments)
        return True

    def clear_user(self, user_id: str):
        p = _user_path(user_id)
        if p.exists():
            p.unlink()

    # --- append with dedup ---

    def append(self, user_id: str, new_fragments: List[MemoryFragment]):
        existing = self.load(user_id)
        existing_hashes = {hashlib.md5(f.content.encode()).hexdigest() for f in existing}

        added = 0
        for f in new_fragments:
            h = hashlib.md5(f.content.encode()).hexdigest()
            if h not in existing_hashes:
                existing.append(f)
                existing_hashes.add(h)
                added += 1

        if added == 0:
            return

        # LRU 淘汰
        if len(existing) > MAX_MEMORIES_PER_USER:
            existing.sort(key=lambda x: (x.access_count, -x.timestamp))
            existing = existing[-MAX_MEMORIES_PER_USER:]

        self.save(user_id, existing)
        if added:
            logger.info(f"Memory: +{added} fragments for user {user_id} (total={len(existing)})")

    # --- vector search ---

    def search(self, user_id: str, query_vec: List[float], k: int = 5) -> List[MemoryFragment]:
        fragments = self.load(user_id)
        if not fragments or not query_vec:
            return []

        vecs = np.array([f.embedding for f in fragments if f.embedding], dtype=np.float64)
        if vecs.shape[0] == 0:
            return []

        q = np.array(query_vec, dtype=np.float64)
        scores = (vecs @ q).tolist()

        top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:k]
        top_fragments = []
        for i in top_indices:
            if scores[i] > 0.3:
                fragments[i].access_count += 1
                top_fragments.append(fragments[i])

        if top_fragments:
            self.save(user_id, fragments)

        return top_fragments


memory_store = MemoryStore()
