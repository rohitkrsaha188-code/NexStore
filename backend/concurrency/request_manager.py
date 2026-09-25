"""Request manager: track in-flight mutation operations per object."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class InFlightRequest:
    request_id: str
    object_id: str
    operation: str
    started_at: str


class RequestManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._inflight: dict[str, InFlightRequest] = {}

    def begin(self, request_id: str, object_id: str, operation: str) -> None:
        with self._lock:
            self._inflight[request_id] = InFlightRequest(
                request_id=request_id, object_id=object_id,
                operation=operation, started_at=datetime.now(timezone.utc).isoformat(),
            )

    def end(self, request_id: str) -> None:
        with self._lock:
            self._inflight.pop(request_id, None)

    def inflight_for_object(self, object_id: str) -> list[InFlightRequest]:
        with self._lock:
            return [r for r in self._inflight.values() if r.object_id == object_id]

    def total_inflight(self) -> int:
        with self._lock:
            return len(self._inflight)


request_manager = RequestManager()
