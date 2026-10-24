"""CAS operational repository and create-only object archive interfaces.

Repository callbacks contain no external side effects. In-memory implementations
are explicitly local/test only, and can be reused across service instances in tests.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from threading import RLock
from typing import Protocol

from .study_config import canonical


class IntegrityError(RuntimeError):
    pass


class Conflict(RuntimeError):
    pass


@dataclass
class Snapshot:
    session: dict
    records: dict[str, dict]


class Repository(Protocol):
    durable: bool
    def read(self, sid: str) -> Snapshot: ...
    def cas(self, sid: str, revision: int | None, session: dict, writes: dict[str, dict]) -> bool: ...
    def probe(self) -> None: ...


class Archive(Protocol):
    durable: bool
    def put(self, name: str, value: dict) -> None: ...
    def probe(self) -> None: ...


class MemoryRepository:
    durable = False

    def __init__(self):
        self.lock = RLock()
        self.sessions = {}

    def read(self, sid):
        with self.lock:
            if sid not in self.sessions:
                raise KeyError(sid)
            return deepcopy(self.sessions[sid])

    def cas(self, sid, revision, session, writes):
        with self.lock:
            old = self.sessions.get(sid)
            if (old is None and revision is not None) or (old is not None and old.session["revision"] != revision):
                return False
            records = deepcopy(old.records) if old else {}
            records.update(deepcopy(writes))
            new = deepcopy(session)
            new["revision"] = 0 if revision is None else revision + 1
            self.sessions[sid] = Snapshot(new, records)
            return True

    def probe(self):
        return None


class MemoryArchive:
    durable = False

    def __init__(self):
        self.lock = RLock()
        self.objects = {}

    def put(self, name, value):
        content = canonical(value)
        with self.lock:
            if name in self.objects and self.objects[name] != content:
                raise IntegrityError("immutable object content differs")
            self.objects[name] = content

    def probe(self):
        return None
