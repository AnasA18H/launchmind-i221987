"""In-process message bus (Option A: shared queues per agent)."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from schemas import validate_message


class MessageBus:
    def __init__(self) -> None:
        self._queues: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._history: list[dict[str, Any]] = []

    def send(self, msg: dict[str, Any]) -> None:
        validate_message(msg)
        self._history.append(msg)
        to_agent = msg["to_agent"]
        self._queues[to_agent].append(msg)

    def receive_all(self, agent_name: str) -> list[dict[str, Any]]:
        """Drain inbox for agent_name (FIFO)."""
        q = self._queues.get(agent_name, [])
        self._queues[agent_name] = []
        return list(q)

    def peek_inbox(self, agent_name: str) -> list[dict[str, Any]]:
        return list(self._queues.get(agent_name, []))

    def history(self) -> list[dict[str, Any]]:
        return list(self._history)

    def clear(self) -> None:
        self._queues.clear()
        self._history.clear()
