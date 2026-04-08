"""Validate inter-agent messages per LaunchMind assignment schema."""
from __future__ import annotations

import re
from typing import Any

MESSAGE_TYPES = frozenset({"task", "result", "revision_request", "confirmation"})
AGENT_NAMES = frozenset({"ceo", "product", "engineer", "marketing", "qa"})


def validate_message(msg: dict[str, Any]) -> None:
    if not isinstance(msg, dict):
        raise ValueError("message must be a dict")
    required = ("message_id", "from_agent", "to_agent", "message_type", "payload", "timestamp")
    for k in required:
        if k not in msg:
            raise ValueError(f"missing field: {k}")
    if not isinstance(msg["message_id"], str) or not msg["message_id"]:
        raise ValueError("message_id must be non-empty string")
    if msg["from_agent"] not in AGENT_NAMES:
        raise ValueError(f"from_agent must be one of {sorted(AGENT_NAMES)}")
    if msg["to_agent"] not in AGENT_NAMES:
        raise ValueError(f"to_agent must be one of {sorted(AGENT_NAMES)}")
    if msg["message_type"] not in MESSAGE_TYPES:
        raise ValueError(f"message_type must be one of {sorted(MESSAGE_TYPES)}")
    if not isinstance(msg["payload"], dict):
        raise ValueError("payload must be an object")
    ts = msg["timestamp"]
    if not isinstance(ts, str) or not _iso8601_ok(ts):
        raise ValueError("timestamp must be ISO 8601 string")
    if "parent_message_id" in msg and msg["parent_message_id"] is not None:
        if not isinstance(msg["parent_message_id"], str):
            raise ValueError("parent_message_id must be string or omitted")


_ISO8601_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)


def _iso8601_ok(s: str) -> bool:
    return bool(_ISO8601_RE.match(s))


def make_message(
    *,
    message_id: str,
    from_agent: str,
    to_agent: str,
    message_type: str,
    payload: dict[str, Any],
    timestamp: str,
    parent_message_id: str | None = None,
) -> dict[str, Any]:
    m: dict[str, Any] = {
        "message_id": message_id,
        "from_agent": from_agent,
        "to_agent": to_agent,
        "message_type": message_type,
        "payload": payload,
        "timestamp": timestamp,
    }
    if parent_message_id is not None:
        m["parent_message_id"] = parent_message_id
    validate_message(m)
    return m
