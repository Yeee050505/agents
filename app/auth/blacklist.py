from __future__ import annotations
import time
import threading
from typing import Dict


class Blacklist:
    def __init__(self):
        self._store: dict[str, float] = {}
        self._lock = threading.Lock()

    def add(self, user_id: str, ttl: float = 3600.0):
        with self._lock:
            self._store[user_id] = time.time() + ttl

    def remove(self, user_id: str):
        with self._lock:
            self._store.pop(user_id, None)

    def is_blacklisted(self, user_id: str) -> bool:
        with self._lock:
            expire = self._store.get(user_id)
            if expire is None:
                return False
            if time.time() > expire:
                del self._store[user_id]
                return False
            return True

    def _cleanup(self):
        now = time.time()
        with self._lock:
            expired = [uid for uid, exp in self._store.items() if now > exp]
            for uid in expired:
                del self._store[uid]


blacklist = Blacklist()
