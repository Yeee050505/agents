from __future__ import annotations
from typing import List

from app.utils.logger import logger


class ShortTermMemory:
    def __init__(self, max_turns: int = 10):
        self._sessions: dict[str, List[dict]] = {}
        self.max_turns = max_turns

    def get_history(self, session_id: str) -> List[dict]:
        return self._sessions.get(session_id, [])

    def add_turn(self, session_id: str, user_msg: str, assistant_msg: str):
        self._sessions.setdefault(session_id, [])
        self._sessions[session_id].append({"role": "user", "content": user_msg})
        self._sessions[session_id].append({"role": "assistant", "content": assistant_msg})
        if len(self._sessions[session_id]) > self.max_turns * 2:
            self._sessions[session_id] = self._sessions[session_id][-self.max_turns * 2:]

    def clear(self, session_id: str):
        self._sessions.pop(session_id, None)

    def format_context(self, session_id: str) -> str:
        history = self.get_history(session_id)
        if not history:
            return ""
        lines = []
        for m in history[-6:]:
            role = "用户" if m["role"] == "user" else "助手"
            lines.append(f"{role}: {m['content'][:200]}")
        return "\n".join(lines)


short_memory = ShortTermMemory()
