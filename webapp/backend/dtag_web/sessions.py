"""In-memory respondent session store.

Each stored object is an ``EngineSession`` owning an isolated
``DTAGSession``; loaded native models are shared through the engine's
``ModelRegistry``, never through the store. The interface (add/get/remove/
all) is what a Redis or database backed store would need to implement.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional


class SessionStore:
    def __init__(self, max_sessions: int = 200, ttl_seconds: float = 24 * 3600):
        self.max_sessions = max(1, int(max_sessions))
        self.ttl_seconds = float(ttl_seconds)
        self._lock = threading.Lock()
        self._items: Dict[str, Any] = {}

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    def _expire(self) -> None:
        now = time.time()
        for sid in [s for s, es in self._items.items() if now - es.last_used > self.ttl_seconds]:
            self._items.pop(sid, None)
        while len(self._items) >= self.max_sessions:
            oldest = min(self._items.values(), key=lambda es: es.last_used)
            self._items.pop(oldest.id, None)

    def add(self, es: Any) -> None:
        with self._lock:
            self._expire()
            self._items[es.id] = es

    def get(self, session_id: str) -> Optional[Any]:
        with self._lock:
            es = self._items.get(session_id)
            if es is not None and time.time() - es.last_used > self.ttl_seconds:
                self._items.pop(session_id, None)
                return None
            return es

    def remove(self, session_id: str) -> bool:
        with self._lock:
            return self._items.pop(session_id, None) is not None

    def all(self) -> List[Any]:
        with self._lock:
            return list(self._items.values())
