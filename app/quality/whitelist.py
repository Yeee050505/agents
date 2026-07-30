from __future__ import annotations
import json
import re
import time
from pathlib import Path
from typing import Optional
from app.utils.logger import logger

WHITELIST_FILE = Path(__file__).parent.parent.parent / "data" / "quality" / "white_list.json"


class WhitelistEntry:
    def __init__(self, id: str, question: str, answer: str, keywords: list[str] | None = None,
                 source: str = "manual", created_at: float = 0):
        self.id = id
        self.question = question
        self.answer = answer
        self.keywords = keywords or []
        self.source = source
        self.created_at = created_at or time.time()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "question": self.question,
            "answer": self.answer,
            "keywords": self.keywords,
            "source": self.source,
            "created_at": self.created_at,
        }


class Whitelist:
    def __init__(self):
        self._entries: list[WhitelistEntry] = []
        self._load()

    def _load(self):
        if WHITELIST_FILE.exists():
            try:
                data = json.loads(WHITELIST_FILE.read_text(encoding="utf-8"))
                self._entries = [WhitelistEntry(**e) for e in data.get("entries", [])]
                logger.info(f"Whitelist: loaded {len(self._entries)} entries")
            except Exception as e:
                logger.warning(f"Whitelist load failed: {e}")

    def _save(self):
        WHITELIST_FILE.parent.mkdir(parents=True, exist_ok=True)
        WHITELIST_FILE.write_text(
            json.dumps({"entries": [e.to_dict() for e in self._entries]}, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

    def add(self, question: str, answer: str, keywords: list[str] | None = None, source: str = "manual") -> WhitelistEntry:
        import uuid
        entry = WhitelistEntry(str(uuid.uuid4())[:8], question, answer, keywords, source)
        self._entries.append(entry)
        self._save()
        logger.info(f"Whitelist added: {question[:40]}")
        return entry

    def delete(self, entry_id: str) -> bool:
        before = len(self._entries)
        self._entries = [e for e in self._entries if e.id != entry_id]
        if len(self._entries) < before:
            self._save()
            return True
        return False

    def match(self, query: str) -> Optional[WhitelistEntry]:
        """Return entry if query matches by keyword or fuzzy question match."""
        q = query.lower().strip()
        for e in self._entries:
            if q == e.question.lower().strip():
                return e
            for kw in e.keywords:
                if kw.lower() in q:
                    return e
        for e in self._entries:
            if self._fuzzy_match(q, e.question.lower().strip()):
                return e
        return None

    def _fuzzy_match(self, a: str, b: str) -> bool:
        if not a or not b:
            return False
        shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
        return shorter in longer or self._char_overlap(a, b) > 0.8

    def _char_overlap(self, a: str, b: str) -> float:
        common = sum(1 for c in a if c in b)
        return common / max(len(a), 1)

    def list_all(self) -> list[dict]:
        return [e.to_dict() for e in self._entries]

    def count(self) -> int:
        return len(self._entries)


whitelist = Whitelist()
