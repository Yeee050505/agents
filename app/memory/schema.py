from __future__ import annotations
import uuid
import time
from dataclasses import dataclass, field, asdict
from typing import List, Optional


@dataclass
class MemoryFragment:
    content: str
    user_id: str
    category: str = "fact"  # preference / fact / experience
    memory_id: str = ""
    source_session: str = ""
    timestamp: float = 0.0
    access_count: int = 0
    embedding: List[float] = field(default_factory=list)

    def __post_init__(self):
        if not self.memory_id:
            self.memory_id = str(uuid.uuid4())
        if not self.timestamp:
            self.timestamp = time.time()

    def to_dict(self) -> dict:
        d = asdict(self)
        d["embedding"] = self.embedding
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "MemoryFragment":
        return cls(**d)


MEMORY_CATEGORIES = ("preference", "fact", "experience")
MAX_MEMORIES_PER_USER = 500
MEMORY_EMBED_DIM = 512
