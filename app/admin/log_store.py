from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any


class InMemoryLogStore:
    def __init__(self, max_items: int = 200):
        self._logs = deque(maxlen=max_items)

    def insert_log(self, record: dict[str, Any]) -> dict[str, Any]:
        self._logs.appendleft(record)
        return record

    def recent_logs(self, limit: int = 50) -> list[dict[str, Any]]:
        return list(self._logs)[:limit]


@lru_cache(maxsize=1)
def get_log_store() -> InMemoryLogStore:
    return InMemoryLogStore()


def create_log(user: str, state: str) -> dict[str, Any]:
    record = {
        "user": user,
        "state": state,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    return get_log_store().insert_log(record)


def get_recent_logs(limit: int = 50) -> list[dict[str, Any]]:
    return get_log_store().recent_logs(limit=limit)
