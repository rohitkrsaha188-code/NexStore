"""Fine-grained named locks keyed by resource (per-object serialization).

Reads run without locks; metadata mutations on the same object serialize here
in addition to the global SQLite write lock, keeping critical sections small.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from collections import defaultdict


class LockManager:
    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._locks: dict[str, threading.RLock] = {}
        self._counts: dict[str, int] = defaultdict(int)

    @contextmanager
    def acquire(self, key: str):
        with self._guard:
            lock = self._locks.setdefault(key, threading.RLock())
            self._counts[key] += 1
        lock.acquire()
        try:
            yield
        finally:
            lock.release()
            with self._guard:
                self._counts[key] -= 1
                if self._counts[key] <= 0 and not lock._is_owned():
                    self._locks.pop(key, None)


lock_manager = LockManager()
