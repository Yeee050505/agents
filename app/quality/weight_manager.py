from __future__ import annotations
import json
import time
from pathlib import Path
from typing import Optional
from app.utils.logger import logger

WEIGHT_FILE = Path(__file__).parent.parent.parent / "data" / "quality" / "chunk_weights.json"


class WeightManager:
    def __init__(self):
        self._weights: dict[str, float] = {}  # key: "{doc_id}_{chunk_idx}"
        self._history: list[dict] = []
        self._load()

    def _load(self):
        if WEIGHT_FILE.exists():
            try:
                data = json.loads(WEIGHT_FILE.read_text(encoding="utf-8"))
                self._weights = data.get("weights", {})
                self._history = data.get("history", [])
                logger.info(f"WeightManager: loaded {len(self._weights)} weights, {len(self._history)} history entries")
            except Exception as e:
                logger.warning(f"WeightManager load failed: {e}")

    def _save(self):
        WEIGHT_FILE.parent.mkdir(parents=True, exist_ok=True)
        WEIGHT_FILE.write_text(
            json.dumps({"weights": self._weights, "history": self._history[-1000:]},
                       ensure_ascii=False, default=str),
            encoding="utf-8",
        )

    def _key(self, doc_id: str, chunk_idx: int) -> str:
        return f"{doc_id}_{chunk_idx}"

    def get_weight(self, doc_id: str, chunk_idx: int) -> float:
        return self._weights.get(self._key(doc_id, chunk_idx), 1.0)

    def adjust_weight(self, doc_id: str, chunk_idx: int, delta: float) -> float:
        k = self._key(doc_id, chunk_idx)
        old = self._weights.get(k, 1.0)
        new = max(0.0, min(2.0, old + delta))
        self._weights[k] = new
        self._history.append({
            "doc_id": doc_id,
            "chunk_idx": chunk_idx,
            "old": old,
            "new": new,
            "delta": delta,
            "timestamp": time.time(),
        })
        self._save()
        return new

    def reset_weight(self, doc_id: str, chunk_idx: int) -> float:
        k = self._key(doc_id, chunk_idx)
        old = self._weights.pop(k, 1.0)
        self._history.append({
            "doc_id": doc_id, "chunk_idx": chunk_idx,
            "old": old, "new": 1.0, "delta": -(old - 1.0),
            "timestamp": time.time(), "action": "reset",
        })
        self._save()
        return 1.0

    def find_chunks_by_query(self, query: str) -> list[dict]:
        from app.rag import rag_engine
        results = rag_engine.search(query, k=20)
        return [
            {"doc_id": r["doc_id"], "chunk_idx": r.get("chunk_idx", 0), "content": r.get("content", "")[:100]}
            for r in results
        ]

    def decay_weights(self, half_life_days: float = 30):
        """Time-based weight decay toward 1.0."""
        now = time.time()
        half_life = half_life_days * 86400
        changed = 0
        for k, v in list(self._weights.items()):
            entry = next((h for h in reversed(self._history) if h.get("doc_id") + "_" + str(h.get("chunk_idx", 0)) == k), None)
            if entry:
                age = now - entry["timestamp"]
                decay_factor = 2 ** (-age / half_life)
                new_v = 1.0 + (v - 1.0) * decay_factor
                if abs(new_v - 1.0) < 0.01:
                    del self._weights[k]
                else:
                    self._weights[k] = round(new_v, 4)
                changed += 1
        if changed:
            self._save()
            logger.info(f"WeightManager: decayed {changed} weights")

    def get_all_weights(self) -> dict:
        return dict(self._weights)

    def get_history(self, limit: int = 100) -> list[dict]:
        return self._history[-limit:]

    def rollback(self, minutes: int = 30) -> int:
        """Rollback all weight changes within the last N minutes."""
        cutoff = time.time() - minutes * 60
        rolled = 0
        for entry in self._history:
            if entry["timestamp"] >= cutoff:
                k = self._key(entry["doc_id"], entry["chunk_idx"])
                self._weights[k] = entry["old"]
                rolled += 1
        self._save()
        logger.info(f"WeightManager: rolled back {rolled} changes from last {minutes}min")
        return rolled


weight_manager = WeightManager()
